package parser

import (
	"strings"
	"testing"

	"github.com/goccy/go-json"
)

// claude reports the same idea under different names than codex, and splits it
// in two. If CachedIn ever starts summing them this fails: cache *creation* is
// billed as fresh input, so counting it as cached understates what was spent.
func TestUsageCachedInReadsWhicheverNameTheBackendUsed(t *testing.T) {
	codex := Usage{CachedInputTokens: 38000}
	if got := codex.CachedIn(); got != 38000 {
		t.Fatalf("codex CachedIn() = %d, want 38000", got)
	}

	claude := Usage{CacheReadInputTokens: 1200, CacheCreationInputTokens: 60680}
	if got := claude.CachedIn(); got != 1200 {
		t.Fatalf("claude CachedIn() = %d, want 1200 (creation is not cached)", got)
	}

	if got := (Usage{InputTokens: 5}).CachedIn(); got != 0 {
		t.Fatalf("CachedIn() = %d with neither field set, want 0", got)
	}
}

func TestParseJSONStreamInternalCarriesClaudeUsageCostAndModel(t *testing.T) {
	input := `{"type":"result","subtype":"success","session_id":"s1","result":"ok",` +
		`"total_cost_usd":0.4223195,` +
		`"usage":{"input_tokens":2,"cache_creation_input_tokens":60680,"cache_read_input_tokens":1200,"output_tokens":4},` +
		`"modelUsage":{"claude-opus-5[1m]":{"costUSD":0.4223195}}}`

	msg, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if msg != "ok" {
		t.Fatalf("message = %q, want %q", msg, "ok")
	}
	if usage == nil {
		t.Fatal("usage = nil, want usage from the claude result event")
	}
	if !usage.TokensReported {
		t.Fatal("TokensReported = false though the event carried a usage object")
	}
	if usage.InputTokens != 2 || usage.OutputTokens != 4 {
		t.Fatalf("usage = %+v, want input=2 output=4", usage)
	}
	if got := usage.CachedIn(); got != 1200 {
		t.Fatalf("CachedIn() = %d, want 1200", got)
	}
	// The number the call was actually billed for. Measured on a live call it
	// was 60,680 against an input_tokens of 2; dropping it understated claude
	// by four orders of magnitude.
	if usage.CacheCreationInputTokens != 60680 {
		t.Fatalf("CacheCreationInputTokens = %d, want 60680", usage.CacheCreationInputTokens)
	}
	if usage.TotalCostUSD != 0.4223195 || !usage.CostReported {
		t.Fatalf("cost = %v reported=%v, want 0.4223195 true", usage.TotalCostUSD, usage.CostReported)
	}
	if usage.ResolvedModel != "claude-opus-5[1m]" {
		t.Fatalf("ResolvedModel = %q, want the resolved name", usage.ResolvedModel)
	}
}

// A result with no usage object at all leaves usage nil so the ledger omits
// every count. A zero-valued struct would read as "this call consumed
// nothing", which is a different claim from "the backend did not say".
func TestParseJSONStreamInternalLeavesUsageNilWhenClaudeSaysNothing(t *testing.T) {
	input := `{"type":"result","subtype":"success","session_id":"s1","result":"ok"}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage != nil {
		t.Fatalf("usage = %+v, want nil", usage)
	}
}

// `total_cost_usd` and `modelUsage` sit beside `usage`, not inside it. Gating
// them on it recorded a priced call as one that cost nothing.
func TestParseJSONStreamInternalKeepsCostWhenUsageIsAbsent(t *testing.T) {
	input := `{"type":"result","subtype":"success","session_id":"s1","result":"ok",` +
		`"total_cost_usd":0.42,"modelUsage":{"claude-opus-5[1m]":{"costUSD":0.42}}}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage == nil {
		t.Fatal("usage = nil though the event priced the turn")
	}
	if !usage.CostReported || usage.TotalCostUSD != 0.42 {
		t.Fatalf("cost = %v reported=%v, want 0.42 true", usage.TotalCostUSD, usage.CostReported)
	}
	if usage.ResolvedModel != "claude-opus-5[1m]" {
		t.Fatalf("ResolvedModel = %q, want the resolved name", usage.ResolvedModel)
	}
	// No usage object arrived, so nothing may claim token counts.
	if usage.TokensReported {
		t.Fatal("TokensReported = true though the event carried no usage object")
	}
}

// codex reports no cost at all; claude can report a real zero.
func TestParseJSONStreamInternalMarksAZeroCostAsReported(t *testing.T) {
	input := `{"type":"result","subtype":"success","session_id":"s1","result":"ok",` +
		`"total_cost_usd":0,"usage":{"input_tokens":1,"output_tokens":1}}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage == nil || !usage.CostReported || usage.TotalCostUSD != 0 {
		t.Fatalf("usage = %+v, want an explicitly reported zero cost", usage)
	}
}

func TestParseJSONStreamInternalLeavesCostUnreportedForCodex(t *testing.T) {
	input := `{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1}}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage == nil {
		t.Fatal("usage = nil, want usage from turn.completed")
	}
	if usage.CostReported {
		t.Fatal("CostReported = true for codex, which never reports cost")
	}
	if !usage.TokensReported {
		t.Fatal("TokensReported = false though turn.completed carried usage")
	}
}

// codex emits one turn.completed per turn, but a second one without usage
// would erase the numbers the first reported.
func TestParseJSONStreamInternalDoesNotLetALaterEventEraseUsage(t *testing.T) {
	input := `{"type":"turn.completed","usage":{"input_tokens":15451,"cached_input_tokens":11008,"output_tokens":5}}` + "\n" +
		`{"type":"turn.completed"}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage == nil {
		t.Fatal("usage = nil: a usage-less second event erased the first")
	}
	if usage.InputTokens != 15451 || usage.OutputTokens != 5 {
		t.Fatalf("usage = %+v, want the numbers from the first event", usage)
	}
}

func TestDominantModelKeyPicksTheModelThatWasBilled(t *testing.T) {
	one := map[string]json.RawMessage{"claude-opus-5[1m]": json.RawMessage(`{"costUSD":0.41}`)}
	if got := dominantModelKey(one); got != "claude-opus-5[1m]" {
		t.Fatalf("dominantModelKey(one) = %q, want the single key", got)
	}

	// The shape actually observed on a wrapper call: a cheap helper model
	// rides along with the one that answered.
	withHelper := map[string]json.RawMessage{
		"claude-opus-5[1m]":         json.RawMessage(`{"costUSD":0.0461}`),
		"claude-haiku-4-5-20251001": json.RawMessage(`{"costUSD":0.000946}`),
	}
	if got := dominantModelKey(withHelper); got != "claude-opus-5[1m]" {
		t.Fatalf("dominantModelKey(withHelper) = %q, want the billed model", got)
	}

	if got := dominantModelKey(nil); got != "" {
		t.Fatalf("dominantModelKey(nil) = %q, want empty", got)
	}

	tied := map[string]json.RawMessage{
		"claude-opus-5[1m]": json.RawMessage(`{"costUSD":0.5,"inputTokens":10,"outputTokens":1}`),
		"claude-sonnet-5":   json.RawMessage(`{"costUSD":0.5,"inputTokens":10,"outputTokens":1}`),
	}
	if got := dominantModelKey(tied); got != "" {
		t.Fatalf("dominantModelKey(tied) = %q, want empty", got)
	}
}

// A fully cached or promotional turn prices every model at zero. Treating that
// as a tie dropped the model name exactly when the call was cheap.
func TestDominantModelKeyBreaksZeroCostTiesOnVolume(t *testing.T) {
	free := map[string]json.RawMessage{
		"claude-opus-5[1m]":         json.RawMessage(`{"costUSD":0,"inputTokens":9000,"outputTokens":400}`),
		"claude-haiku-4-5-20251001": json.RawMessage(`{"costUSD":0,"inputTokens":90,"outputTokens":4}`),
	}
	if got := dominantModelKey(free); got != "claude-opus-5[1m]" {
		t.Fatalf("dominantModelKey(free) = %q, want the model that did the volume", got)
	}
}

// `best == ""` cannot mean both "nothing chosen yet" and "the chosen key is
// blank", or a cheaper model overwrites a dearer one.
func TestDominantModelKeyDoesNotTreatAnEmptyKeyAsUnset(t *testing.T) {
	withBlank := map[string]json.RawMessage{
		"":                json.RawMessage(`{"costUSD":1.0,"inputTokens":100,"outputTokens":10}`),
		"claude-sonnet-5": json.RawMessage(`{"costUSD":0.1,"inputTokens":10,"outputTokens":1}`),
	}
	if got := dominantModelKey(withBlank); got != "" {
		t.Fatalf("dominantModelKey(withBlank) = %q, want the dearer blank-keyed entry to win", got)
	}
}

// Skipping an entry that will not decode hands the win to whatever else is in
// the map -- typically the cheap helper. Unknown is the honest answer.
func TestDominantModelKeyRefusesWhenAnEntryWillNotDecode(t *testing.T) {
	broken := map[string]json.RawMessage{
		"claude-opus-5[1m]":         json.RawMessage(`{"costUSD":"broken"}`),
		"claude-haiku-4-5-20251001": json.RawMessage(`{"costUSD":0.001}`),
	}
	if got := dominantModelKey(broken); got != "" {
		t.Fatalf("dominantModelKey(broken) = %q, want empty rather than the helper", got)
	}
}
