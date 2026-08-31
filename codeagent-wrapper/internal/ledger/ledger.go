// Package ledger appends one durable record for each vendor call.
package ledger

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
	"unicode/utf8"

	"github.com/goccy/go-json"

	"codeagent-wrapper/internal/logger"
)

const maxLineBytes = 4096

var writeMu sync.Mutex

// Tokens is the token usage reported by a backend.
// A nil Tokens pointer means the backend did not report usage.
type Tokens struct {
	In       int `json:"in"`
	CachedIn int `json:"cached_in"`
	// Input written into a cache rather than served from one. claude bills it
	// as fresh input and it dwarfs `in` on a cold call, so leaving it out
	// understated the call and made `in` mean different things per backend.
	// Omitted when zero: only claude reports it.
	CacheWrite int `json:"cached_write,omitempty"`
	Out        int `json:"out"`
}

// Call captures the metadata for one vendor invocation.
type Call struct {
	Timestamp time.Time
	Duration  time.Duration
	Role      string
	Backend   string
	Model     string
	// ModelDefault is what the vendor's own config declares it falls back
	// to, filled only when Model is empty -- which is every `--backend`
	// override without an explicit `--model`. Declared, not observed: it
	// says which model the vendor was configured to reach for, never that
	// this model served the turn. ModelResolved below is that claim, and
	// only claude makes it.
	ModelDefault string
	Effort       string
	// Ground is which of omo's four delegation grounds the caller named --
	// "1".."4", empty when unstated. Declared by the caller, never inferred:
	// an empty ground means the obligation was skipped, which is itself the
	// number a routing review wants.
	Ground    string
	Mode      string
	WorkDir   string
	Exit      int
	OK        bool
	TaskChars int
	MsgChars  int
	Tokens    *Tokens
	Log       string
	PID       int
	Err       string

	// CostUSD and ModelResolved come from the backend, and today only claude
	// reports either. Model above is what the role was *configured* with;
	// ModelResolved is what actually served the turn. The two differ often
	// enough (`claude-opus-5` vs `claude-opus-5[1m]`) that comparing roles on
	// the configured string alone compares labels rather than models.
	//
	// CostUSD is a pointer for the same reason Tokens is: a fully cached turn
	// can genuinely cost 0, and "the backend said zero" is a different fact
	// from "the backend does not report cost" -- which is every call codex and
	// agy make. A bare float64 with omitempty erases that difference silently.
	CostUSD       *float64
	ModelResolved string
}

type entry struct {
	Timestamp     string   `json:"ts"`
	Duration      int64    `json:"dur_ms"`
	Role          string   `json:"role,omitempty"`
	Backend       string   `json:"backend"`
	Model         string   `json:"model,omitempty"`
	ModelDefault  string   `json:"model_default,omitempty"`
	ModelResolved string   `json:"model_resolved,omitempty"`
	Effort        string   `json:"effort,omitempty"`
	Ground        string   `json:"ground,omitempty"`
	Mode          string   `json:"mode,omitempty"`
	WorkDir       string   `json:"workdir,omitempty"`
	Exit          int      `json:"exit"`
	OK            bool     `json:"ok"`
	TaskChars     int      `json:"task_chars"`
	MsgChars      int      `json:"msg_chars"`
	Tokens        *Tokens  `json:"tokens,omitempty"`
	CostUSD       *float64 `json:"cost_usd,omitempty"`
	Log           string   `json:"log,omitempty"`
	PID           int      `json:"pid"`
	Err           string   `json:"err,omitempty"`
	Truncated     bool     `json:"truncated,omitempty"`
}

// Record appends a call record. Ledger failures are deliberately best-effort so
// they never affect the vendor invocation.
func Record(call Call) {
	// A test run is not vendor usage. Every test that drives the executor
	// reaches this function, and measured once on this machine a single
	// `go test ./...` left 65 rows in the real ledger against 5 genuine calls
	// -- backends named `cat`, `sleep`, and temp-directory shell scripts. The
	// ledger exists to be a denominator, and a denominator that a test suite
	// can inflate thirteenfold is not one.
	//
	// An explicit CODEAGENT_LEDGER still writes, so the ledger's own tests
	// exercise the real path by pointing it at a temp file.
	path, err := ledgerPath()
	if err != nil {
		logger.LogWarn("ledger: resolve path: " + err.Error())
		return
	}

	// The comparison is against the resolved *default* path rather than
	// against an unset CODEAGENT_LEDGER: someone who exports that variable to
	// their real ledger would otherwise have every `go test` write to it.
	// Tests that point it at a temp file still exercise the real write path.
	if testing.Testing() {
		if def, derr := defaultLedgerPath(); derr != nil || path == def {
			return
		}
	}

	// An existing path that is not a regular file is not a ledger. Measured:
	// a FIFO here blocks the open forever, and because the mutex is held the
	// whole process stops with it -- a best-effort write turning into a hang
	// in every parallel task. Refusing is the only way to keep the contract.
	if info, statErr := os.Lstat(path); statErr == nil && !info.Mode().IsRegular() {
		logger.LogWarn("ledger: refusing to write to a non-regular file: " + path)
		return
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		logger.LogWarn("ledger: create directory: " + err.Error())
		return
	}

	line, err := marshalLine(call)
	if err != nil {
		logger.LogWarn("ledger: encode record: " + err.Error())
		return
	}

	writeMu.Lock()
	defer writeMu.Unlock()

	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		logger.LogWarn("ledger: open file: " + err.Error())
		return
	}

	// A short write leaves a fragment that the next append lands behind,
	// corrupting this row and the one after it. Finish the line if we can, and
	// close it with a newline if we cannot, so the damage stops at one row.
	written := 0
	for written < len(line) {
		n, werr := f.Write(line[written:])
		written += n
		if werr != nil || n == 0 {
			if werr != nil {
				logger.LogWarn("ledger: append record: " + werr.Error())
			}
			if written > 0 && line[written-1] != '\n' {
				_, _ = f.Write([]byte{'\n'})
			}
			break
		}
	}
	if err := f.Close(); err != nil {
		logger.LogWarn("ledger: close file: " + err.Error())
	}
	// ponytail: no rotation; add when calls.jsonl outgrows a few MB
}

func ledgerPath() (string, error) {
	if path := os.Getenv("CODEAGENT_LEDGER"); path != "" {
		return path, nil
	}
	return defaultLedgerPath()
}

func defaultLedgerPath() (string, error) {
	stateHome := os.Getenv("XDG_STATE_HOME")
	if stateHome == "" {
		home := os.Getenv("HOME")
		if home == "" {
			var err error
			home, err = os.UserHomeDir()
			if err != nil {
				return "", err
			}
		}
		stateHome = filepath.Join(home, ".local", "state")
	}
	return filepath.Join(stateHome, "codeagent-wrapper", "calls.jsonl"), nil
}

func marshalLine(call Call) ([]byte, error) {
	e := entry{
		Timestamp:     call.Timestamp.Format(time.RFC3339Nano),
		Duration:      call.Duration.Milliseconds(),
		Role:          call.Role,
		Backend:       call.Backend,
		Model:         call.Model,
		ModelDefault:  call.ModelDefault,
		Ground:        call.Ground,
		ModelResolved: call.ModelResolved,
		Effort:        call.Effort,
		Mode:          call.Mode,
		WorkDir:       call.WorkDir,
		Exit:          call.Exit,
		OK:            call.OK,
		TaskChars:     call.TaskChars,
		MsgChars:      call.MsgChars,
		Tokens:        call.Tokens,
		CostUSD:       call.CostUSD,
		Log:           call.Log,
		PID:           call.PID,
		Err:           truncate(call.Err, 200),
	}

	for {
		line, err := json.Marshal(e)
		if err != nil {
			return nil, err
		}
		line = append(line, '\n')
		if len(line) < maxLineBytes {
			return line, nil
		}

		e.Truncated = true
		if shortenLongest(&e) {
			continue
		}

		// Every shortenable field is already empty and the row still does not
		// fit. Only `backend` can still be long -- one resolved from a command
		// *path* rather than a name. Cut it to its last path element, and if
		// even that leaves the row oversized, give up on the row rather than on
		// the file: a line past 4096 B is no longer an atomic append, so
		// writing it would let concurrent wrappers interleave and corrupt every
		// row around it. A dropped row costs one measurement.
		if trimmed := filepath.Base(e.Backend); trimmed != e.Backend && trimmed != "." {
			e.Backend = trimmed
			continue
		}
		return nil, fmt.Errorf("record does not fit in %d bytes even when reduced", maxLineBytes)
	}
}

func shortenLongest(e *entry) bool {
	// Backend is deliberately absent: it is the one string field the record is
	// useless without, and a row that says `"backend":""` is worse than a long
	// one. Everything here can be cut to a stub and still leave a usable row.
	fields := []*string{&e.Err, &e.WorkDir, &e.Log, &e.Role, &e.Model, &e.ModelResolved, &e.Effort, &e.Mode}
	longest := fields[0]
	for _, field := range fields[1:] {
		if len(*field) > len(*longest) {
			longest = field
		}
	}
	if *longest == "" {
		return false
	}
	if len(*longest) == 1 {
		*longest = ""
		return true
	}
	limit := len(*longest) / 2
	for limit > 0 && !utf8.RuneStart((*longest)[limit]) {
		limit--
	}
	*longest = strings.TrimSpace((*longest)[:limit])
	return true
}

func truncate(value string, limit int) string {
	if utf8.RuneCountInString(value) <= limit {
		return value
	}
	return string([]rune(value)[:limit])
}
