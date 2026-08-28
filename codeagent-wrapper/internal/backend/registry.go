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
// because the gemini CLI can no longer authenticate here. GeminiBackend and
// OpencodeBackend still compile — the parser, the stderr filter, and ~80 test
// lines reference them — but nothing can select them any more, so deleting
// that code is a separate sweep from this decision.
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
