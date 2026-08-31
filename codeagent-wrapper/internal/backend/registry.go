package backend

import (
	"fmt"
	"strings"
)

// The registry is the contract for `--backend`: a name absent here is
// unreachable no matter what code still exists for it.
//
// omo D24 (2026-08-28) cut it to three. `opencode` went because the operator
// does not use it; `gemini` was REPLACED by `agy`, not retained alongside it,
// because the gemini CLI can no longer authenticate here. The deferred sweep
// D24 named happened in 0.20.0: GeminiBackend, OpencodeBackend, their parser
// branches, stderr patterns, and tests are deleted, not just unreachable.
var registry = map[string]Backend{
	"codex":  CodexBackend{},
	"claude": ClaudeBackend{},
	"agy":    AgyBackend{},
}

// Registry exposes the available backends. Intended for internal inspection/tests.
func Registry() map[string]Backend {
	return registry
}

func Select(name string) (Backend, error) {
	key := strings.ToLower(strings.TrimSpace(name))
	if key == "" {
		key = "codex"
	}
	if backend, ok := registry[key]; ok {
		return backend, nil
	}
	return nil, fmt.Errorf("unsupported backend %q", name)
}
