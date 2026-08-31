package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config holds CLI configuration.
type Config struct {
	Mode            string // "new" or "resume"
	Task            string
	SessionID       string
	WorkDir         string
	OutputPath      string
	Model           string
	ReasoningEffort string
	// Ground is which of omo's four delegation grounds the caller named.
	// SKILL.md already forbids delegating without naming one, but that
	// obligation lived only in the prompt prose, so the ledger could count
	// what a call cost and never why it was made. One of "1".."4", or
	// empty when the caller did not say.
	Ground             string
	ExplicitStdin      bool
	Backend            string
	Agent              string
	PromptFile         string
	PromptFileExplicit bool
	SkipPermissions    bool
	Yolo               bool
	// YoloSet records that the role config named `yolo` explicitly. Without it,
	// an explicit false is indistinguishable from absent and loses to the env
	// default, which is how a security role configured NOT to bypass the sandbox
	// bypassed it anyway until 2026-08-27.
	YoloSet            bool
	MaxParallelWorkers int
	AllowedTools       []string
	DisallowedTools    []string
	Skills             []string
	Worktree           bool // Execute in a new git worktree
}

// EnvFlagEnabled returns true when the environment variable exists and is not
// explicitly set to a falsey value ("0/false/no/off").
func EnvFlagEnabled(key string) bool {
	val, ok := os.LookupEnv(key)
	if !ok {
		return false
	}
	val = strings.TrimSpace(strings.ToLower(val))
	switch val {
	case "", "0", "false", "no", "off":
		return false
	default:
		return true
	}
}

func ParseBoolFlag(val string, defaultValue bool) bool {
	val = strings.TrimSpace(strings.ToLower(val))
	switch val {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return defaultValue
	}
}

// EnvFlagDefaultTrue returns true unless the env var is explicitly set to
// false/0/no/off.
// YoloEnabled resolves the bypass decision. An explicit `yolo` on the role wins
// outright; only an unset one falls through to the env default. These used to be
// OR-ed, so `"yolo": false` could never suppress a default-true env flag.
func YoloEnabled(yolo, yoloSet bool, envKey string) bool {
	if yoloSet {
		return yolo
	}
	return EnvFlagDefaultTrue(envKey)
}

func EnvFlagDefaultTrue(key string) bool {
	val, ok := os.LookupEnv(key)
	if !ok {
		return true
	}
	return ParseBoolFlag(val, true)
}

func ValidateAgentName(name string) error {
	if strings.TrimSpace(name) == "" {
		return fmt.Errorf("agent name is empty")
	}
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= 'A' && r <= 'Z':
		case r >= '0' && r <= '9':
		case r == '-', r == '_':
		default:
			return fmt.Errorf("agent name %q contains invalid character %q", name, r)
		}
	}
	return nil
}

const (
	DefaultMaxParallelWorkers = 10
	maxParallelWorkersLimit   = 100
)

func NormalizeMaxParallelWorkers(value int) int {
	switch {
	case value < 0:
		return DefaultMaxParallelWorkers
	case value == 0:
		return 0
	case value > maxParallelWorkersLimit:
		return maxParallelWorkersLimit
	default:
		return value
	}
}

// ResolveMaxParallelWorkers reads CODEAGENT_MAX_PARALLEL_WORKERS. It returns 0
// for "unlimited".
func ResolveMaxParallelWorkers() int {
	raw := strings.TrimSpace(os.Getenv("CODEAGENT_MAX_PARALLEL_WORKERS"))
	if raw == "" {
		return DefaultMaxParallelWorkers
	}

	value, err := strconv.Atoi(raw)
	if err != nil {
		return DefaultMaxParallelWorkers
	}
	return NormalizeMaxParallelWorkers(value)
}
