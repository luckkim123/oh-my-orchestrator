package ledger

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

// Every test that drives the executor reaches Record, and before this guard one
// `go test ./...` left 65 rows in the real ledger against 5 genuine vendor
// calls. A denominator a test suite can inflate is not a denominator.
func TestRecordSkipsTheDefaultPathUnderTest(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_STATE_HOME", "")
	t.Setenv("CODEAGENT_LEDGER", "")

	Record(Call{Timestamp: time.Now(), Backend: "cat", Exit: 0, OK: true})

	defaultPath := filepath.Join(home, ".local", "state", "codeagent-wrapper", "calls.jsonl")
	if _, err := os.Stat(defaultPath); !os.IsNotExist(err) {
		t.Fatalf("a test run wrote to the default ledger at %s (stat err = %v)", defaultPath, err)
	}
}

// Keying the guard on an unset CODEAGENT_LEDGER let anyone who exports it have
// every `go test` write to their real ledger -- reproduced, three fake rows.
func TestRecordSkipsTheDefaultPathEvenWhenNamedExplicitly(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_STATE_HOME", "")
	defaultPath := filepath.Join(home, ".local", "state", "codeagent-wrapper", "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", defaultPath)

	Record(Call{Timestamp: time.Now(), Backend: "cat", Exit: 0, OK: true})

	if _, err := os.Stat(defaultPath); !os.IsNotExist(err) {
		t.Fatalf("a test run wrote to the real ledger because the env var named it (stat err = %v)", err)
	}
}

// A FIFO here blocked the open forever with the mutex held, stalling every
// parallel task in the process. Best-effort has to mean it, so a path that
// exists and is not a regular file is refused.
func TestRecordRefusesANonRegularFile(t *testing.T) {
	fifo := filepath.Join(t.TempDir(), "calls.jsonl")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Skipf("cannot create a FIFO here: %v", err)
	}
	t.Setenv("CODEAGENT_LEDGER", fifo)

	done := make(chan struct{})
	go func() {
		Record(testCall())
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Record blocked on a FIFO: the vendor call would hang behind it")
	}
}

// Tokens uses a pointer so a reported zero survives; cost has to do the same.
func TestRecordDistinguishesAReportedZeroCostFromNoCostAtAll(t *testing.T) {
	zero := 0.0

	reported := filepath.Join(t.TempDir(), "reported.jsonl")
	t.Setenv("CODEAGENT_LEDGER", reported)
	call := testCall()
	call.CostUSD = &zero
	Record(call)

	var got map[string]json.RawMessage
	decodeRecord(t, reported, &got)
	raw, ok := got["cost_usd"]
	if !ok {
		t.Fatal("cost_usd absent when the backend reported 0 -- indistinguishable from a backend that reports none")
	}
	if string(raw) != "0" {
		t.Fatalf("cost_usd = %s, want 0", raw)
	}

	unreported := filepath.Join(t.TempDir(), "unreported.jsonl")
	t.Setenv("CODEAGENT_LEDGER", unreported)
	Record(testCall())

	var got2 map[string]json.RawMessage
	decodeRecord(t, unreported, &got2)
	if _, present := got2["cost_usd"]; present {
		t.Fatal("cost_usd present when the backend reported none")
	}
}

// Cache creation is billed as fresh input and dwarfs `in` on a cold call.
func TestRecordCarriesCacheWriteAndOmitsItWhenZero(t *testing.T) {
	withWrite := filepath.Join(t.TempDir(), "a.jsonl")
	t.Setenv("CODEAGENT_LEDGER", withWrite)
	call := testCall()
	call.Tokens = &Tokens{In: 2, CachedIn: 1200, CacheWrite: 60680, Out: 4}
	Record(call)

	var got struct {
		Tokens map[string]int `json:"tokens"`
	}
	decodeRecord(t, withWrite, &got)
	if got.Tokens["cached_write"] != 60680 {
		t.Fatalf("cached_write = %d, want 60680", got.Tokens["cached_write"])
	}

	withoutWrite := filepath.Join(t.TempDir(), "b.jsonl")
	t.Setenv("CODEAGENT_LEDGER", withoutWrite)
	call2 := testCall()
	call2.Tokens = &Tokens{In: 15451, CachedIn: 11008, Out: 5}
	Record(call2)

	var raw map[string]json.RawMessage
	decodeRecord(t, withoutWrite, &raw)
	var tok map[string]json.RawMessage
	if err := json.Unmarshal(raw["tokens"], &tok); err != nil {
		t.Fatalf("tokens is not an object: %v", err)
	}
	if _, present := tok["cached_write"]; present {
		t.Fatal("cached_write present for a backend that does not report it")
	}
}

// A row past 4096 B is no longer an atomic append, so writing it would let
// concurrent wrappers interleave and corrupt the rows around it.
func TestRecordDropsARowItCannotFitRatherThanCorruptTheFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", path)

	call := testCall()
	call.Backend = strings.Repeat("b", 8000)
	Record(call)

	data, err := os.ReadFile(path)
	if err == nil && len(data) > 0 {
		t.Fatalf("wrote %d bytes for a record that cannot fit", len(data))
	}
}

// The same field, long but a path: its base name fits, so the row survives in
// reduced form instead of being dropped.
func TestRecordTrimsALongBackendPathInsteadOfDroppingTheRow(t *testing.T) {
	path := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", path)

	call := testCall()
	call.Backend = "/" + strings.Repeat("d/", 3000) + "codex.sh"
	Record(call)

	var got map[string]json.RawMessage
	decodeRecord(t, path, &got)
	if string(got["backend"]) != `"codex.sh"` {
		t.Fatalf("backend = %s, want the trimmed base name", got["backend"])
	}
	data, _ := os.ReadFile(path)
	if len(data) >= maxLineBytes {
		t.Fatalf("row is %d bytes, want under %d", len(data), maxLineBytes)
	}
}

func TestRecordOmitsTokensWhenUnknown(t *testing.T) {
	path := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", path)

	Record(testCall())

	var got map[string]json.RawMessage
	decodeRecord(t, path, &got)
	if _, ok := got["tokens"]; ok {
		t.Fatal("tokens must be absent when the backend did not report usage")
	}
}

func TestRecordWriteFailureIsBestEffort(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "unwritable")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatalf("Mkdir() error = %v", err)
	}
	if err := os.Chmod(dir, 0o500); err != nil {
		t.Fatalf("Chmod() error = %v", err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o700) })
	t.Setenv("CODEAGENT_LEDGER", filepath.Join(dir, "calls.jsonl"))

	Record(testCall())
}

func TestRecordTruncatesLongLine(t *testing.T) {
	path := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", path)
	call := testCall()
	call.Role = strings.Repeat("role-", 2000)
	call.WorkDir = strings.Repeat("/very-long-workdir", 1000)

	Record(call)

	line, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	if len(line) >= maxLineBytes {
		t.Fatalf("record length = %d, want less than %d", len(line), maxLineBytes)
	}

	var got map[string]json.RawMessage
	if err := json.Unmarshal(line, &got); err != nil {
		t.Fatalf("record is not valid JSON: %v", err)
	}
	if string(got["truncated"]) != "true" {
		t.Fatalf("truncated = %s, want true", got["truncated"])
	}
}

func TestRecordDoesNotPersistTaskOrResponseText(t *testing.T) {
	path := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", path)
	task := "TASK_SECRET_MARKER_41b587da"
	response := "RESPONSE_SECRET_MARKER_8fca2e11"
	call := testCall()
	call.TaskChars = len(task)
	call.MsgChars = len(response)

	Record(call)

	line, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	if strings.Contains(string(line), task) || strings.Contains(string(line), response) {
		t.Fatalf("record contains task or response text: %s", line)
	}
}

func testCall() Call {
	return Call{
		Timestamp: time.Date(2026, time.August, 31, 0, 12, 3, 0, time.FixedZone("KST", 9*60*60)),
		Duration:  141230 * time.Millisecond,
		Backend:   "codex",
		Exit:      0,
		OK:        true,
		TaskChars: 3120,
		MsgChars:  13305,
		PID:       40246,
	}
}

func decodeRecord(t *testing.T, path string, target any) {
	t.Helper()
	line, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	if err := json.Unmarshal(line, target); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
}
