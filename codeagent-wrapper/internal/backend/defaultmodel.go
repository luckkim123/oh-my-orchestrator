package backend

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
)

// homeDir is a var so tests can point the lookups at a fixture tree.
var homeDir = os.UserHomeDir

// DefaultModel reports the model a vendor CLI falls back to when the wrapper
// passes none. That is not an edge case: every `--backend` override without an
// explicit `--model` lands here on purpose (internal/adapter/cli/parse.go -- a
// role's model name lives in ITS vendor's namespace, so carrying it across
// vendors is an HTTP 400 on codex and a silent wrong-model run on agy). The
// ledger then recorded `backend=codex` and nothing else, which is how the two
// most expensive calls of 2026-08-31 (4.8M and 8.9M input tokens) ended up
// unattributable to any model.
//
// What comes back is what the vendor's own config *declares*, never evidence of
// what served the turn -- that is `model_resolved`, which only claude reports.
// It gets its own ledger field so the two can never be confused.
//
// Every failure path returns "": this is metadata about a call that already
// happened and must never affect one.
func DefaultModel(name string) string {
	home, err := homeDir()
	if err != nil {
		return ""
	}
	switch name {
	case "codex":
		return codexDefaultModel(filepath.Join(home, ".codex", "config.toml"))
	case "agy":
		return agyDefaultModel(filepath.Join(home, ".gemini", "antigravity-cli", "settings.json"))
	}
	// claude reports the model that actually served the turn, so a declared
	// default would be the weaker of two facts already available.
	return ""
}

// codexDefaultModel reads the top-level `model` key out of codex's TOML without
// pulling in a TOML parser. Two things make the naive scan wrong: only the keys
// above the first `[table]` header are top level, and `model_reasoning_effort`
// shares the prefix -- so the `=` is what has to be matched, not the name.
func codexDefaultModel(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()

	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if strings.HasPrefix(line, "[") {
			break // a table header: everything below is scoped, not the default
		}
		key, val, ok := strings.Cut(line, "=")
		if !ok || strings.TrimSpace(key) != "model" {
			continue
		}
		return unquoteTOML(val)
	}
	return ""
}

// unquoteTOML takes the quoted string out of a value, leaving any trailing
// inline comment behind. A bare `strings.Trim(val, "\"")` would keep it.
func unquoteTOML(val string) string {
	val = strings.TrimSpace(val)
	if len(val) > 1 && (val[0] == '"' || val[0] == '\'') {
		if end := strings.IndexByte(val[1:], val[0]); end >= 0 {
			return val[1 : 1+end]
		}
	}
	return strings.Trim(val, `"'`)
}

func agyDefaultModel(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	var settings struct {
		Model string `json:"model"`
	}
	if json.Unmarshal(data, &settings) != nil {
		return ""
	}
	return strings.TrimSpace(settings.Model)
}
