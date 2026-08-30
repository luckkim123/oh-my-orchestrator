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

// The ledger exists to answer "which vendor ran, and what did it cost", and
// the backend field is the one it is useless without. `cfg.Backend` starts as
// the package constant "codex" and is resolved to the real vendor further down
// (backend.Name, else taskSpec.Backend, else commandName); reading it before
// that resolution -- or dropping back to `defaultBackendName` -- would stamp
// every agy and claude call "codex". A ledger of one value with no error to
// notice is the exact failure this whole record was built to prevent, so it is
// worth a test that fails the moment the field stops varying.
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
		t.Fatalf("backend = %v, want \"agy\" -- the ledger recorded a constant, not the vendor that ran", got)
	}
	if got := row["role"]; got != "explore" {
		t.Fatalf("role = %v, want \"explore\"", got)
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
	// The task text must never reach a durable file.
	if strings.Contains(raw, "sweep the tree") {
		t.Fatalf("task text leaked into the ledger row: %s", raw)
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
