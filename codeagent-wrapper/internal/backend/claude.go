package backend

import (
	"os"
	"path/filepath"
	"strings"

	config "codeagent-wrapper/internal/config"

	"github.com/goccy/go-json"
)

type ClaudeBackend struct{}

func (ClaudeBackend) Name() string    { return "claude" }
func (ClaudeBackend) Command() string { return "claude" }
func (ClaudeBackend) Env(baseURL, apiKey string) map[string]string {
	baseURL = strings.TrimSpace(baseURL)
	apiKey = strings.TrimSpace(apiKey)
	if baseURL == "" && apiKey == "" {
		return nil
	}
	env := make(map[string]string, 2)
	if baseURL != "" {
		env["ANTHROPIC_BASE_URL"] = baseURL
	}
	if apiKey != "" {
		// Claude Code CLI uses ANTHROPIC_API_KEY for API-key based auth.
		env["ANTHROPIC_API_KEY"] = apiKey
	}
	return env
}
func (ClaudeBackend) BuildArgs(cfg *config.Config, targetArg string) []string {
	return buildClaudeArgs(cfg, targetArg)
}

const MaxClaudeSettingsBytes = 1 << 20 // 1MB

type MinimalClaudeSettings struct {
	Env   map[string]string
	Model string
}

// LoadMinimalClaudeSettings pulls only the safe minimum out of
// ~/.claude/settings.json:
//   - env: string values only
//   - model: string values only
//
// A missing file, a parse failure, or an over-size file all return empty.
func LoadMinimalClaudeSettings() MinimalClaudeSettings {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return MinimalClaudeSettings{}
	}

	claudeDir := filepath.Clean(filepath.Join(home, ".claude"))
	settingPath := filepath.Clean(filepath.Join(claudeDir, "settings.json"))
	rel, err := filepath.Rel(claudeDir, settingPath)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return MinimalClaudeSettings{}
	}

	info, err := os.Stat(settingPath)
	if err != nil || info.Size() > MaxClaudeSettingsBytes {
		return MinimalClaudeSettings{}
	}

	data, err := os.ReadFile(settingPath) // #nosec G304 -- path is fixed under user home and validated to stay within claudeDir
	if err != nil {
		return MinimalClaudeSettings{}
	}

	var cfg struct {
		Env   map[string]any `json:"env"`
		Model any            `json:"model"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return MinimalClaudeSettings{}
	}

	out := MinimalClaudeSettings{}

	if model, ok := cfg.Model.(string); ok {
		out.Model = strings.TrimSpace(model)
	}

	if len(cfg.Env) == 0 {
		return out
	}

	env := make(map[string]string, len(cfg.Env))
	for k, v := range cfg.Env {
		s, ok := v.(string)
		if !ok {
			continue
		}
		env[k] = s
	}
	if len(env) == 0 {
		return out
	}
	out.Env = env
	return out
}

func LoadMinimalEnvSettings() map[string]string {
	settings := LoadMinimalClaudeSettings()
	if len(settings.Env) == 0 {
		return nil
	}
	return settings.Env
}

func buildClaudeArgs(cfg *config.Config, targetArg string) []string {
	if cfg == nil {
		return nil
	}
	args := []string{"-p"}
	// Default to skip permissions unless CODEAGENT_SKIP_PERMISSIONS=false
	if cfg.SkipPermissions || config.YoloEnabled(cfg.Yolo, cfg.YoloSet, "CODEAGENT_SKIP_PERMISSIONS") {
		args = append(args, "--dangerously-skip-permissions")
	}

	// Prevent infinite recursion: disable all setting sources (user, project, local)
	// so the invoked Claude does not load ~/.claude/CLAUDE.md or skills and call
	// codeagent again. Added deliberately in a09c103 for that reason; f2e75c1
	// commented it out in May 2026 with an empty commit body and left the six
	// expectations in backend_test.go / main_test.go asserting it, so the Go suite
	// was red until 2026-08-27. Restored: the stated hazard still applies and the
	// CLI still accepts the flag.
	args = append(args, "--setting-sources", "")

	if model := strings.TrimSpace(cfg.Model); model != "" {
		args = append(args, "--model", model)
	}

	// Claude CLI spells the effort tier `--effort` and accepts exactly the tiers
	// the role config uses (low, medium, high, xhigh, max). Until 2026-08-27 this
	// was not emitted at all, so every claude-backed role silently ran at the
	// CLI's default no matter what `reasoning` said in models.json.
	if effort := strings.TrimSpace(cfg.ReasoningEffort); effort != "" {
		args = append(args, "--effort", effort)
	}

	if cfg.Mode == "resume" {
		if cfg.SessionID != "" {
			// Claude CLI uses -r <session_id> for resume.
			args = append(args, "-r", cfg.SessionID)
		}
	}

	if len(cfg.AllowedTools) > 0 {
		args = append(args, "--allowedTools")
		args = append(args, cfg.AllowedTools...)
	}
	if len(cfg.DisallowedTools) > 0 {
		args = append(args, "--disallowedTools")
		args = append(args, cfg.DisallowedTools...)
	}

	args = append(args, "--output-format", "stream-json", "--verbose", targetArg)

	return args
}
