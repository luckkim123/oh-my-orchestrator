package parser

import (
	"strings"
	"testing"

	"github.com/goccy/go-json"
)

// claude reports the same idea under different names than codex, and splits it
// in two. If CachedIn ever starts summing them, this fails: cache *creation* is
// billed as fresh input and counting it as cached understates the call.
func TestUsageCachedInReadsWhicheverNameTheBackendUsed(t *testing.T) {
	codex := Usage{CachedInputTokens: 38000}
	if got := codex.CachedIn(); got != 38000 {
		t.Fatalf("codex CachedIn() = %d, want 38000", got)
	}

	claude := Usage{CacheReadInputTokens: 1200, CacheCreationInputTokens: 60680}
	if got := claude.CachedIn(); got != 1200 {
		t.Fatalf("claude CachedIn() = %d, want 1200 (creation is not cached)", got)
	}

	none := Usage{InputTokens: 5}
	if got := none.CachedIn(); got != 0 {
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
	if usage.InputTokens != 2 || usage.OutputTokens != 4 {
		t.Fatalf("usage = %+v, want input=2 output=4", usage)
	}
	if got := usage.CachedIn(); got != 1200 {
		t.Fatalf("CachedIn() = %d, want 1200", got)
	}
	if usage.TotalCostUSD != 0.4223195 {
		t.Fatalf("TotalCostUSD = %v, want 0.4223195", usage.TotalCostUSD)
	}
	// The resolved name, not the one the role was configured with. That
	// difference is the reason the field exists.
	if usage.ResolvedModel != "claude-opus-5[1m]" {
		t.Fatalf("ResolvedModel = %q, want %q", usage.ResolvedModel, "claude-opus-5[1m]")
	}
}

// A claude result with no usage object must leave usage nil so the ledger omits
// the key. A zero-valued struct here would be recorded as "this call cost
// nothing", which is a different claim from "the backend did not say".
func TestParseJSONStreamInternalLeavesUsageNilWhenClaudeOmitsIt(t *testing.T) {
	input := `{"type":"result","subtype":"success","session_id":"s1","result":"ok"}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage != nil {
		t.Fatalf("usage = %+v, want nil when the event carries no usage object", usage)
	}
}

func TestDominantModelKeyPicksTheModelThatWasBilled(t *testing.T) {
	one := map[string]json.RawMessage{"claude-opus-5[1m]": json.RawMessage(`{"costUSD":0.41}`)}
	if got := dominantModelKey(one); got != "claude-opus-5[1m]" {
		t.Fatalf("dominantModelKey(one) = %q, want the single key", got)
	}

	// The shape actually observed on a wrapper call: a cheap helper model
	// rides along with the one that answered. Returning "" here would leave
	// the field empty on ordinary calls, which is the same as not recording it.
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

	// A genuine tie has no answer, and map iteration order is randomized --
	// returning either key would make the ledger differ run to run.
	tied := map[string]json.RawMessage{
		"claude-opus-5[1m]": json.RawMessage(`{"costUSD":0.5}`),
		"claude-sonnet-5":   json.RawMessage(`{"costUSD":0.5}`),
	}
	if got := dominantModelKey(tied); got != "" {
		t.Fatalf("dominantModelKey(tied) = %q, want empty", got)
	}
}
