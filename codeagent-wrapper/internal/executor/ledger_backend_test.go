package executor

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/goccy/go-json"

	config "codeagent-wrapper/internal/config"
)

// The ledger exists to answer "which vendor ran, and what did it cost", and the
// backend field is the one it is useless without. `cfg.Backend` starts as the
// package constant "codex" and is resolved to the real vendor further down;
// reading it before that resolution, or dropping back to defaultBackendName,
// would stamp every agy and claude call "codex" -- a ledger of one value with
// no error to notice.
func TestLedgerRecordsTheBackendThatActuallyRan(t *testing.T) {
	ledgerPath := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", ledgerPath)

	restore := newCommandRunner
	newCommandRunner = func(context.Context, string, ...string) commandRunner { return &fakeCmd{} }
	t.Cleanup(func() { newCommandRunner = restore })

	noArgs := func(*config.Config, string) []string { return nil }
	RunCodexTaskWithContext(
		context.Background(),
		TaskSpec{ID: "t1", Agent: "explore", Task: "sweep the tree", Mode: "new"},
		nil, "agy", noArgs, nil, false, true, 0,
	)

	raw := rawLedgerLine(t, ledgerPath)
	row := readSoleLedgerRow(t, raw)

	if got := row["backend"]; got != "agy" {
		t.Fatalf("backend = %v, want agy -- the ledger recorded a constant, not the vendor that ran", got)
	}
	if got := row["role"]; got != "explore" {
		t.Fatalf("role = %v, want explore", got)
	}
	// This run fails at the stderr pipe, so it must be written down as a
	// failure. A defer that records only the happy path biases the whole
	// measurement toward calls that worked.
	if got := row["ok"]; got != false {
		t.Fatalf("ok = %v, want false for a failed call", got)
	}
	if _, present := row["tokens"]; present {
		t.Fatalf("tokens present in %v, want the key omitted when no backend reported usage", row)
	}
	if strings.Contains(raw, "sweep the tree") {
		t.Fatalf("task text leaked into the ledger row: %s", raw)
	}
}

// The wrapper counts a task as failed on `ExitCode != 0 || Error != ""`
// everywhere it reports. A ledger using a looser test would claim a success
// rate the run itself denies.
func TestLedgerOKMatchesTheWrappersOwnFailureTest(t *testing.T) {
	ledgerPath := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", ledgerPath)

	restore := newCommandRunner
	newCommandRunner = func(context.Context, string, ...string) commandRunner { return &fakeCmd{} }
	t.Cleanup(func() { newCommandRunner = restore })

	noArgs := func(*config.Config, string) []string { return nil }
	res := RunCodexTaskWithContext(
		context.Background(),
		TaskSpec{ID: "t1", Agent: "explore", Task: "x", Mode: "new"},
		nil, "agy", noArgs, nil, false, true, 0,
	)
	if res.Error == "" {
		t.Fatal("expected the fake stderr pipe to set an error")
	}

	row := readSoleLedgerRow(t, rawLedgerLine(t, ledgerPath))
	if got := row["ok"]; got != false {
		t.Fatalf("ok = %v with Error=%q, want false", got, res.Error)
	}
}

// The fields are named for characters. `len` reported a 1,000-character Korean
// task as 3,000 and silently inflated every per-language comparison.
func TestLedgerCountsCharactersNotBytes(t *testing.T) {
	ledgerPath := filepath.Join(t.TempDir(), "calls.jsonl")
	t.Setenv("CODEAGENT_LEDGER", ledgerPath)

	restore := newCommandRunner
	newCommandRunner = func(context.Context, string, ...string) commandRunner { return &fakeCmd{} }
	t.Cleanup(func() { newCommandRunner = restore })

	task := strings.Repeat("\uac00", 100) // 100 characters, 300 bytes
	noArgs := func(*config.Config, string) []string { return nil }
	RunCodexTaskWithContext(
		context.Background(),
		TaskSpec{ID: "t1", Agent: "explore", Task: task, Mode: "new"},
		nil, "agy", noArgs, nil, false, true, 0,
	)

	row := readSoleLedgerRow(t, rawLedgerLine(t, ledgerPath))
	if got := row["task_chars"]; got != float64(100) {
		t.Fatalf("task_chars = %v, want 100 characters (not 300 bytes)", got)
	}
}

// `attachStderr` appends up to 4 KB of captured vendor stderr to every error it
// builds, and vendor stderr quotes prompts and file content. Truncating that to
// 200 runes and writing it to a durable file is still a leak.
func TestWrapperErrorOnlyDropsTheVendorStderrHalf(t *testing.T) {
	const secret = "PRIVATE-REPO-CONTENT-9f2a"
	got := wrapperErrorOnly("codex exited with status 3; stderr: " + secret)

	if strings.Contains(got, secret) {
		t.Fatalf("vendor stderr survived into %q", got)
	}
	if got != "codex exited with status 3" {
		t.Fatalf("wrapperErrorOnly = %q, want the wrapper's own sentence intact", got)
	}
	if got := wrapperErrorOnly("failed to create stdin pipe"); got != "failed to create stdin pipe" {
		t.Fatalf("wrapperErrorOnly = %q, want the message unchanged", got)
	}
}

// defaultCommandName is the seam tests inject a fake vendor binary through.
// Correcting the command from taskSpec.Backend must not clobber it, or nine
// app tests go at the real codex.
func TestSeedBackendPrefersTheSpec(t *testing.T) {
	if got := seedBackend("claude"); got != "claude" {
		t.Fatalf("seedBackend(claude) = %q", got)
	}
	if got := seedBackend("  "); got != defaultBackendName {
		t.Fatalf("seedBackend(blank) = %q, want %q", got, defaultBackendName)
	}
}

func readSoleLedgerRow(t *testing.T, raw string) map[string]any {
	t.Helper()
	lines := strings.Split(strings.TrimSpace(raw), "\n")
	if len(lines) != 1 {
		t.Fatalf("ledger has %d rows, want exactly 1", len(lines))
	}
	var row map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &row); err != nil {
		t.Fatalf("ledger row is not JSON: %v (%s)", err, lines[0])
	}
	return row
}

func rawLedgerLine(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read ledger: %v", err)
	}
	return string(data)
}
