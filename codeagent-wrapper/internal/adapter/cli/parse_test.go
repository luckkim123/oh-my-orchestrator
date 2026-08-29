package cli

import (
	"strings"
	"testing"

	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func TestBuildSingleConfigResumeMode(t *testing.T) {
	opts := &Options{}
	cmd := &cobra.Command{SilenceErrors: true, SilenceUsage: true, Args: cobra.ArbitraryArgs}
	AddRootFlags(cmd.Flags(), opts)
	args := []string{"resume", "sess-1", "do work", "/tmp/work"}

	cfg, err := BuildSingleConfig(cmd, args, args, opts, viper.New())
	if err != nil {
		t.Fatalf("BuildSingleConfig() error = %v", err)
	}
	if cfg.Mode != "resume" || cfg.SessionID != "sess-1" || cfg.Task != "do work" || cfg.WorkDir != "/tmp/work" {
		t.Fatalf("cfg = %+v", cfg)
	}
}

// TestBackendOverrideRejectsSameFamilyModel pins the hole left by the 0.12.0
// model-leak fix: clearing the model stopped the *accidental* leak, but an
// explicit same-family model still passed. `--agent oracle --backend agy
// --model claude-opus-4-6-thinking` ran at exit 0 and returned a review
// written by the family that wrote the code — omo's ground 3 defeated with
// nothing to notice.
func TestBackendOverrideRejectsSameFamilyModel(t *testing.T) {
	for _, tc := range []struct {
		name    string
		argv    []string
		wantErr bool
	}{
		{"claude role to agy on a claude model", []string{
			"--agent", "oracle", "--backend", "agy",
			"--model", "claude-opus-4-6-thinking", "-", "."}, true},
		{"claude role to agy on a gemini model", []string{
			"--agent", "oracle", "--backend", "agy",
			"--model", "gemini-3.1-pro-high", "-", "."}, false},
		{"claude role to codex with no model", []string{
			"--agent", "oracle", "--backend", "codex", "-", "."}, false},
		{"unrecognised model id is not policed", []string{
			"--agent", "oracle", "--backend", "agy",
			"--model", "some-local-llm", "-", "."}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			opts := &Options{}
			cmd := &cobra.Command{SilenceErrors: true, SilenceUsage: true,
				Args: cobra.ArbitraryArgs}
			AddRootFlags(cmd.Flags(), opts)
			if err := cmd.ParseFlags(tc.argv); err != nil {
				t.Fatalf("ParseFlags(%v) = %v", tc.argv, err)
			}
			args := cmd.Flags().Args()
			_, err := BuildSingleConfig(cmd, args, tc.argv, opts, viper.New())
			if tc.wantErr && err == nil {
				t.Fatalf("expected a refusal for %v", tc.argv)
			}
			if !tc.wantErr && err != nil && strings.Contains(err.Error(), "own family") {
				t.Fatalf("unexpected same-family refusal for %v: %v", tc.argv, err)
			}
		})
	}
}
