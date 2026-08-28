package backend

import (
	"reflect"
	"testing"

	config "codeagent-wrapper/internal/config"
)

func TestAgyEffortClamp(t *testing.T) {
	// agy rejects anything outside low|medium|high with a hard error that
	// fails the whole call, so the wrapper's higher tiers have to clamp here
	// rather than be passed through. Measured against agy 1.1.22:
	//   invalid --effort "xhigh" (valid: low, medium, high)
	cases := map[string]string{
		"low":    "low",
		"medium": "medium",
		"high":   "high",
		"HIGH":   "high",
		" high ": "high",
		"xhigh":  "high",
		"max":    "high",
		"":       "",
		"turbo":  "",
	}
	for in, want := range cases {
		if got := agyEffort(in); got != want {
			t.Errorf("agyEffort(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestAgyBuildArgs(t *testing.T) {
	b := AgyBackend{}

	t.Run("prompt is a flag value, never a stdin sentinel", func(t *testing.T) {
		t.Setenv("CODEAGENT_SKIP_PERMISSIONS", "false")
		cfg := &config.Config{Mode: "new", WorkDir: "/repo"}
		got := b.BuildArgs(cfg, "do the thing")
		want := []string{"--output-format", "json", "--print", "do the thing"}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %v, want %v", got, want)
		}
	})

	t.Run("skip-permissions by default", func(t *testing.T) {
		cfg := &config.Config{Mode: "new"}
		got := b.BuildArgs(cfg, "task")
		want := []string{"--dangerously-skip-permissions", "--output-format", "json", "--print", "task"}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %v, want %v", got, want)
		}
	})

	t.Run("model and clamped effort", func(t *testing.T) {
		t.Setenv("CODEAGENT_SKIP_PERMISSIONS", "false")
		cfg := &config.Config{Mode: "new", Model: "gemini-3.1-pro-high", ReasoningEffort: "xhigh"}
		got := b.BuildArgs(cfg, "task")
		want := []string{
			"--model", "gemini-3.1-pro-high",
			"--effort", "high",
			"--output-format", "json", "--print", "task",
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %v, want %v", got, want)
		}
	})

	t.Run("resume uses --conversation", func(t *testing.T) {
		t.Setenv("CODEAGENT_SKIP_PERMISSIONS", "false")
		cfg := &config.Config{Mode: "resume", SessionID: "conv-123"}
		got := b.BuildArgs(cfg, "task")
		want := []string{"--conversation", "conv-123", "--output-format", "json", "--print", "task"}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("got %v, want %v", got, want)
		}
	})

	t.Run("nil config", func(t *testing.T) {
		if got := b.BuildArgs(nil, "task"); got != nil {
			t.Fatalf("got %v, want nil", got)
		}
	})
}

func TestAgyBackendIdentity(t *testing.T) {
	b := AgyBackend{}
	if b.Name() != "agy" || b.Command() != "agy" {
		t.Fatalf("Name()=%q Command()=%q, want both %q", b.Name(), b.Command(), "agy")
	}
	// agy authenticates through its own CLI session; there is no base URL or
	// API key to inject.
	if env := b.Env("https://example.invalid", "key"); env != nil {
		t.Fatalf("Env() = %v, want nil", env)
	}
}

// The registry is the contract for --backend, so assert the D24 shape
// directly: three reachable names, and the two the decision removed erroring
// out rather than silently resolving.
func TestRegistryAfterD24(t *testing.T) {
	reg := Registry()
	if len(reg) != 3 {
		t.Fatalf("registry has %d backends, want 3: %v", len(reg), reg)
	}
	for _, name := range []string{"codex", "claude", "agy"} {
		if _, err := Select(name); err != nil {
			t.Errorf("Select(%q) error = %v, want reachable", name, err)
		}
	}
	for _, name := range []string{"gemini", "opencode"} {
		if _, err := Select(name); err == nil {
			t.Errorf("Select(%q) succeeded, want unsupported after D24", name)
		}
	}
}
