// Package ledger appends one durable record for each vendor call.
package ledger

import (
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
	Out      int `json:"out"`
}

// Call captures the metadata for one vendor invocation.
type Call struct {
	Timestamp time.Time
	Duration  time.Duration
	Role      string
	Backend   string
	Model     string
	Effort    string
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
	CostUSD       float64
	ModelResolved string
}

type entry struct {
	Timestamp string  `json:"ts"`
	Duration  int64   `json:"dur_ms"`
	Role          string `json:"role,omitempty"`
	Backend       string `json:"backend"`
	Model         string `json:"model,omitempty"`
	ModelResolved string `json:"model_resolved,omitempty"`
	Effort        string `json:"effort,omitempty"`
	Mode      string  `json:"mode,omitempty"`
	WorkDir   string  `json:"workdir,omitempty"`
	Exit      int     `json:"exit"`
	OK        bool    `json:"ok"`
	TaskChars int     `json:"task_chars"`
	MsgChars  int     `json:"msg_chars"`
	Tokens    *Tokens `json:"tokens,omitempty"`
	CostUSD   float64 `json:"cost_usd,omitempty"`
	Log       string  `json:"log,omitempty"`
	PID       int     `json:"pid"`
	Err       string  `json:"err,omitempty"`
	Truncated bool    `json:"truncated,omitempty"`
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
	if testing.Testing() && os.Getenv("CODEAGENT_LEDGER") == "" {
		return
	}

	path, err := ledgerPath()
	if err != nil {
		logger.LogWarn("ledger: resolve path: " + err.Error())
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

	if _, err := f.Write(line); err != nil {
		logger.LogWarn("ledger: append record: " + err.Error())
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
		if !shortenLongest(&e) {
			return line, nil
		}
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
