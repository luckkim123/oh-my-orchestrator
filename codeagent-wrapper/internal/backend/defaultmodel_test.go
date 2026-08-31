package backend

import (
	"os"
	"path/filepath"
	"testing"
)

func fakeHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	prev := homeDir
	homeDir = func() (string, error) { return home, nil }
	t.Cleanup(func() { homeDir = prev })
	return home
}

func writeFile(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
}

func TestDefaultModel_Codex(t *testing.T) {
	tests := []struct {
		name string
		toml string
		want string
	}{
		{
			name: "top-level model",
			// model_reasoning_effort shares the prefix: matching the name alone
			// would return "high" for a config whose model is gpt-5.6-sol.
			toml: "model = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"high\"\n",
			want: "gpt-5.6-sol",
		},
		{
			name: "effort first still finds the model",
			toml: "model_reasoning_effort = \"high\"\nmodel = \"gpt-5.6-sol\"\n",
			want: "gpt-5.6-sol",
		},
		{
			name: "a model inside a table is not the default",
			toml: "model_reasoning_effort = \"high\"\n[profiles.review]\nmodel = \"gpt-5.6-terra\"\n",
			want: "",
		},
		{
			name: "trailing inline comment is dropped",
			toml: "model = \"gpt-5.6-sol\"  # pinned 2026-08\n",
			want: "gpt-5.6-sol",
		},
		{
			name: "commented-out key is not a value",
			toml: "# model = \"gpt-5.6-terra\"\n",
			want: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			home := fakeHome(t)
			writeFile(t, filepath.Join(home, ".codex", "config.toml"), tt.toml)
			if got := DefaultModel("codex"); got != tt.want {
				t.Fatalf("DefaultModel(codex) = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestDefaultModel_Agy(t *testing.T) {
	home := fakeHome(t)
	writeFile(t, filepath.Join(home, ".gemini", "antigravity-cli", "settings.json"),
		"{\n  \"model\": \"Gemini 3.7 Flash (High)\"\n}\n")
	if got, want := DefaultModel("agy"), "Gemini 3.7 Flash (High)"; got != want {
		t.Fatalf("DefaultModel(agy) = %q, want %q", got, want)
	}
}

// A missing or unreadable config is the normal case on a machine that never ran
// the vendor, and this runs inside a deferred ledger write: it reports nothing
// rather than failing anything.
func TestDefaultModel_AbsentConfigIsEmpty(t *testing.T) {
	fakeHome(t)
	for _, name := range []string{"codex", "agy", "claude", "nosuchbackend"} {
		if got := DefaultModel(name); got != "" {
			t.Fatalf("DefaultModel(%s) = %q, want empty", name, got)
		}
	}
}

// claude reports model_resolved, the stronger fact, so it never gets a declared
// default even when a config is sitting right there.
func TestDefaultModel_ClaudeAlwaysEmpty(t *testing.T) {
	home := fakeHome(t)
	writeFile(t, filepath.Join(home, ".codex", "config.toml"), "model = \"gpt-5.6-sol\"\n")
	if got := DefaultModel("claude"); got != "" {
		t.Fatalf("DefaultModel(claude) = %q, want empty", got)
	}
}
