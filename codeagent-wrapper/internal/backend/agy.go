package backend

import (
	"strings"

	config "codeagent-wrapper/internal/config"
)

// AgyBackend drives the Antigravity CLI (`agy`), which replaced `gemini` as
// the reachable Google-family vendor here (omo D24, 2026-08-28). Its flag
// surface reads like Claude Code's, but three measured differences (agy
// 1.1.22, 2026-08-28) make it its own backend rather than a rename of
// GeminiBackend:
//
//  1. `--print` takes the prompt as a flag VALUE. It never reads stdin:
//     `--print` with no value errors "flag needs an argument", and
//     `--print -` sends the literal "-", which the model answers with a
//     generic greeting — a wrong answer with a zero exit code. The executor
//     therefore materialises the prompt into argv for this backend instead of
//     piping it (see executor.go's `cfg.Backend == "agy"` guard).
//  2. `--effort` accepts exactly low|medium|high. Anything else is a hard
//     error, so the role config's `xhigh`/`max` tiers must be clamped here
//     rather than passed through — see agyEffort.
//  3. Its `--output-format json` result object is a schema no other backend
//     emits (`conversation_id` / `status` / `response`), which is why the
//     parser carries an agy branch.
//
// Auth is the CLI's own subscription session; no base URL or API key env is
// involved, so Env is nil like OpencodeBackend's.
type AgyBackend struct{}

func (AgyBackend) Name() string                                 { return "agy" }
func (AgyBackend) Command() string                              { return "agy" }
func (AgyBackend) Env(baseURL, apiKey string) map[string]string { return nil }
func (AgyBackend) BuildArgs(cfg *config.Config, targetArg string) []string {
	return buildAgyArgs(cfg, targetArg)
}

// agyEffort maps a role's reasoning tier onto the three agy accepts. The
// wrapper's own tiers go up to `xhigh`/`max`; passing either through fails the
// whole call with
//
//	invalid --effort "xhigh" (valid: low, medium, high)
//
// so they clamp to `high`. An unrecognised tier returns "" and the flag is
// omitted, which leaves agy on its own default — degrading to the default is
// the right failure here, since the alternative is erroring out on a value
// the caller may have meant loosely.
func agyEffort(tier string) string {
	normalized := strings.ToLower(strings.TrimSpace(tier))
	switch normalized {
	case "low", "medium", "high":
		return normalized
	case "xhigh", "max":
		return "high"
	default:
		return ""
	}
}

func buildAgyArgs(cfg *config.Config, targetArg string) []string {
	if cfg == nil {
		return nil
	}

	var args []string

	if cfg.SkipPermissions || config.YoloEnabled(cfg.Yolo, cfg.YoloSet, "CODEAGENT_SKIP_PERMISSIONS") {
		args = append(args, "--dangerously-skip-permissions")
	}

	if model := strings.TrimSpace(cfg.Model); model != "" {
		args = append(args, "--model", model)
	}

	if effort := agyEffort(cfg.ReasoningEffort); effort != "" {
		args = append(args, "--effort", effort)
	}

	if cfg.Mode == "resume" {
		if sessionID := strings.TrimSpace(cfg.SessionID); sessionID != "" {
			// agy calls a session a conversation and resumes by id.
			args = append(args, "--conversation", sessionID)
		}
	}

	// Single-shot json, not stream-json: agy's stream schema nests every
	// payload under an `event` discriminator that shares no field with the
	// other backends, so consuming it would mean a second parser rather than
	// a branch. The result object carries the full response, and a
	// consultation's output is read whole anyway.
	// ponytail: no incremental progress from an agy worker; switch to
	// stream-json if a long consultation ever needs to show its work.
	args = append(args, "--output-format", "json", "--print", targetArg)

	return args
}
