package cli

import (
	"fmt"
	"strings"

	config "codeagent-wrapper/internal/config"

	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

const defaultWorkdir = "."

func ParseSingleConfig(rawArgv []string) (*config.Config, error) {
	opts := &Options{}
	cmd := &cobra.Command{SilenceErrors: true, SilenceUsage: true, Args: cobra.ArbitraryArgs}
	AddRootFlags(cmd.Flags(), opts)

	if err := cmd.ParseFlags(rawArgv); err != nil {
		return nil, err
	}
	args := cmd.Flags().Args()

	v, err := config.NewViper(opts.ConfigFile)
	if err != nil {
		return nil, err
	}

	return BuildSingleConfig(cmd, args, rawArgv, opts, v)
}

func BuildSingleConfig(cmd *cobra.Command, args []string, rawArgv []string, opts *Options, v *viper.Viper) (*config.Config, error) {
	backendName := "codex"
	model := ""
	reasoningEffort := ""
	agentName := ""
	promptFile := ""
	promptFileExplicit := false
	outputPath := ""
	yolo := false
	yoloSet := false

	if cmd.Flags().Changed("agent") {
		agentName = strings.TrimSpace(opts.Agent)
		if agentName == "" {
			return nil, fmt.Errorf("--agent flag requires a value")
		}
		if err := config.ValidateAgentName(agentName); err != nil {
			return nil, fmt.Errorf("--agent flag invalid value: %w", err)
		}
	} else {
		agentName = strings.TrimSpace(v.GetString("agent"))
		if agentName != "" {
			if err := config.ValidateAgentName(agentName); err != nil {
				return nil, fmt.Errorf("--agent flag invalid value: %w", err)
			}
		}
	}

	var resolvedBackend, resolvedModel, resolvedPromptFile, resolvedReasoning string
	var resolvedAllowedTools, resolvedDisallowedTools []string
	if agentName != "" {
		var resolvedYolo *bool
		var err error
		resolvedBackend, resolvedModel, resolvedPromptFile, resolvedReasoning, _, _, resolvedYolo, resolvedAllowedTools, resolvedDisallowedTools, err = config.ResolveAgentConfig(agentName)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve agent %q: %w", agentName, err)
		}
		if resolvedYolo != nil {
			yolo = *resolvedYolo
			yoloSet = true
		}
	}

	if cmd.Flags().Changed("prompt-file") {
		promptFile = strings.TrimSpace(opts.PromptFile)
		if promptFile == "" {
			return nil, fmt.Errorf("--prompt-file flag requires a value")
		}
		promptFileExplicit = true
	} else if val := strings.TrimSpace(v.GetString("prompt-file")); val != "" {
		promptFile = val
		promptFileExplicit = true
	} else {
		promptFile = resolvedPromptFile
	}

	if cmd.Flags().Changed("output") {
		outputPath = strings.TrimSpace(opts.Output)
		if outputPath == "" {
			return nil, fmt.Errorf("--output flag requires a value")
		}
	} else if val := strings.TrimSpace(v.GetString("output")); val != "" {
		outputPath = val
	}

	agentFlagChanged := cmd.Flags().Changed("agent")
	backendFlagChanged := cmd.Flags().Changed("backend")
	if backendFlagChanged {
		backendName = strings.TrimSpace(opts.Backend)
		if backendName == "" {
			return nil, fmt.Errorf("--backend flag requires a value")
		}
	}

	switch {
	case agentFlagChanged && backendFlagChanged && LastFlagIndex(rawArgv, "agent") > LastFlagIndex(rawArgv, "backend"):
		backendName = resolvedBackend
	case !backendFlagChanged && agentName != "":
		backendName = resolvedBackend
	case !backendFlagChanged:
		if val := strings.TrimSpace(v.GetString("backend")); val != "" {
			backendName = val
		}
	}

	modelFlagChanged := cmd.Flags().Changed("model")
	if modelFlagChanged {
		model = strings.TrimSpace(opts.Model)
		if model == "" {
			return nil, fmt.Errorf("--model flag requires a value")
		}
	}

	switch {
	case agentFlagChanged && modelFlagChanged && LastFlagIndex(rawArgv, "agent") > LastFlagIndex(rawArgv, "model"):
		model = strings.TrimSpace(resolvedModel)
	case !modelFlagChanged && agentName != "" && backendFlagChanged && backendName != resolvedBackend:
		// The caller moved this role to a different vendor. A role's model is a
		// name in ITS vendor's namespace, so inheriting it here ships e.g.
		// `codex e --model claude-opus-5` — an HTTP 400 on codex, and on agy a
		// silent wrong-model run with nothing to notice. Empty is the safe
		// value: every backend appends --model only when it is non-empty
		// (codex.go, gemini.go, agy.go, opencode.go), so the vendor CLI falls
		// back to its own default. That is exactly what omo's SKILL.md already
		// tells callers to expect from `--backend codex` with no `--model`;
		// until now the implementation did the opposite.
		//
		// backendName was already settled by the backend switch above, so when
		// `--agent` came LAST it equals resolvedBackend and the role keeps its
		// model — the role won the backend too, and inheriting is then correct.
		// Scoped to agentName != "": whether a model configured in settings
		// should survive a backend switch is a separate question, and this
		// branch deliberately does not answer it.
		model = ""
	case !modelFlagChanged && agentName != "":
		model = strings.TrimSpace(resolvedModel)
	case !modelFlagChanged:
		model = strings.TrimSpace(v.GetString("model"))
	}

	// A backend override that lands back on the home vendor's own model is not
	// a second opinion. The one reason to move a role off its vendor is to get
	// a model from a different family -- that is what omo's delegation ground 3
	// (adversarial verification) requires, and the role table binds `oracle` to
	// claude-opus-5, which is the model most sessions here are already running.
	// Nothing caught this: `--agent oracle --backend agy --model claude-opus-4-6-thinking`
	// is accepted by agy (it serves Gemini, Claude, and GPT-OSS from one CLI),
	// runs at exit 0, and returns a confident review written by the same family
	// that wrote the code. Measured 2026-08-29: agy with no `--model` resolves
	// to Gemini 3.7 Flash, so only an explicit same-family model reaches here.
	if agentFlagChanged && backendFlagChanged && backendName != resolvedBackend &&
		model != "" && modelFamily(model) != "" &&
		modelFamily(model) == modelFamily(resolvedModel) {
		return nil, fmt.Errorf(
			"--agent %s --backend %s --model %s: the override moves the role off %s "+
				"but %s is still a %s model, so this is the caller's own family "+
				"reviewing itself; pick a model from another family or drop --model",
			agentName, backendName, model, resolvedBackend, model, modelFamily(model))
	}

	if cmd.Flags().Changed("reasoning-effort") {
		reasoningEffort = strings.TrimSpace(opts.ReasoningEffort)
		if reasoningEffort == "" {
			return nil, fmt.Errorf("--reasoning-effort flag requires a value")
		}
	} else if val := strings.TrimSpace(v.GetString("reasoning-effort")); val != "" {
		reasoningEffort = val
	} else if agentName != "" {
		reasoningEffort = strings.TrimSpace(resolvedReasoning)
	}

	// Validated here rather than accepted as free text: an unchecked field is
	// a denominator nobody can trust, and parse time is before any vendor
	// process starts, so a typo costs nothing.
	ground := strings.TrimSpace(opts.Ground)
	if ground != "" {
		switch ground {
		case "1", "2", "3", "4":
		default:
			return nil, fmt.Errorf("--ground %s: must be 1 (settled plan), 2 (volume), "+
				"3 (three-strike) or 4 (adversarial verification)", ground)
		}
	}

	skipChanged := cmd.Flags().Changed("skip-permissions") || cmd.Flags().Changed("dangerously-skip-permissions")
	skipPermissions := false
	if skipChanged {
		skipPermissions = opts.SkipPermissions
	} else {
		skipPermissions = v.GetBool("skip-permissions")
	}

	if len(args) == 0 {
		return nil, fmt.Errorf("task required")
	}

	var skills []string
	if cmd.Flags().Changed("skills") {
		for _, s := range strings.Split(opts.Skills, ",") {
			s = strings.TrimSpace(s)
			if s != "" {
				skills = append(skills, s)
			}
		}
	}

	cfg := &config.Config{
		WorkDir:            defaultWorkdir,
		Backend:            backendName,
		Agent:              agentName,
		PromptFile:         promptFile,
		PromptFileExplicit: promptFileExplicit,
		OutputPath:         outputPath,
		SkipPermissions:    skipPermissions,
		Yolo:               yolo,
		YoloSet:            yoloSet,
		Model:              model,
		ReasoningEffort:    reasoningEffort,
		Ground:             ground,
		MaxParallelWorkers: config.ResolveMaxParallelWorkers(),
		AllowedTools:       resolvedAllowedTools,
		DisallowedTools:    resolvedDisallowedTools,
		Skills:             skills,
		Worktree:           opts.Worktree,
	}

	if args[0] == "resume" {
		if len(args) < 3 {
			return nil, fmt.Errorf("resume mode requires: resume <session_id> <task>")
		}
		cfg.Mode = "resume"
		cfg.SessionID = strings.TrimSpace(args[1])
		if cfg.SessionID == "" {
			return nil, fmt.Errorf("resume mode requires non-empty session_id")
		}
		cfg.Task = args[2]
		cfg.ExplicitStdin = args[2] == "-"
		if len(args) > 3 {
			if args[3] == "-" {
				return nil, fmt.Errorf("invalid workdir: '-' is not a valid directory path")
			}
			cfg.WorkDir = args[3]
		}
		return cfg, nil
	}

	cfg.Mode = "new"
	cfg.Task = args[0]
	cfg.ExplicitStdin = args[0] == "-"
	if len(args) > 1 {
		if args[1] == "-" {
			return nil, fmt.Errorf("invalid workdir: '-' is not a valid directory path")
		}
		cfg.WorkDir = args[1]
	}
	return cfg, nil
}

func LastFlagIndex(argv []string, name string) int {
	if len(argv) == 0 {
		return -1
	}
	name = strings.TrimSpace(name)
	if name == "" {
		return -1
	}

	needle := "--" + name
	prefix := needle + "="
	last := -1
	for i, arg := range argv {
		if arg == needle || strings.HasPrefix(arg, prefix) {
			last = i
		}
	}
	return last
}

// modelFamily names the vendor family a model id belongs to, or "" when the id
// is not recognised. Substring matching rather than a fixed list: a family adds
// model names continuously (claude-opus-5, claude-sonnet-4-6,
// claude-opus-4-6-thinking) and a list that has to be updated per release is a
// guard that silently stops guarding. Unknown ids return "" and are allowed --
// this refuses a *known* self-review, it does not police the model namespace.
func modelFamily(model string) string {
	m := strings.ToLower(strings.TrimSpace(model))
	switch {
	case strings.Contains(m, "claude"):
		return "claude"
	case strings.Contains(m, "gemini"):
		return "gemini"
	case strings.Contains(m, "gpt") || strings.Contains(m, "codex") || strings.Contains(m, "terra"):
		return "gpt"
	}
	return ""
}
