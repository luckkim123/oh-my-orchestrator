package parser

import (
	"strings"
	"testing"
)

func TestParseJSONStreamInternalCarriesCodexUsage(t *testing.T) {
	input := `{"type":"turn.completed","usage":{"input_tokens":0,"cached_input_tokens":38000,"output_tokens":2210}}`

	_, _, usage := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)
	if usage == nil {
		t.Fatal("usage = nil, want usage from turn.completed")
	}
	if usage.InputTokens != 0 || usage.CachedInputTokens != 38000 || usage.OutputTokens != 2210 {
		t.Fatalf("usage = %+v, want input=0 cached_input=38000 output=2210", usage)
	}
}
