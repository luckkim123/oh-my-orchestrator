package ledger

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Every test that drives the executor reaches Record, and before this guard one
// `go test ./...` left 65 rows in the real ledger against 5 genuine vendor
// calls -- backends named `cat`, `sleep`, and temp-directory shell scripts. A
// denominator a test suite can inflate thirteenfold is not a denominator.
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
