package parser

import (
	"strings"
	"testing"
)

// agy runs under --output-format json, which emits exactly one object. The
// shapes below are the measured ones (agy 1.1.22, 2026-08-28) with synthetic
// ids and text.
func TestParseAgyResult(t *testing.T) {
	input := `{"conversation_id":"11111111-2222-3333-4444-555555555555","status":"SUCCESS","response":"the answer\n","duration_seconds":1.9,"num_turns":1}` + "\n"

	message, threadID := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)

	if message != "the answer\n" {
		t.Errorf("message = %q, want %q", message, "the answer\n")
	}
	if threadID != "11111111-2222-3333-4444-555555555555" {
		t.Errorf("threadID = %q, want the conversation_id", threadID)
	}
}

// A rejected --model/--effort pair comes back as a well-formed object with an
// empty conversation_id. Dropping it would leave an empty message, which reads
// as "the vendor had nothing to say" rather than "the call was refused".
func TestParseAgyErrorSurfacesAsMessage(t *testing.T) {
	input := `{"conversation_id":"","status":"ERROR","response":"","error":"invalid --effort \"xhigh\" (valid: low, medium, high)"}` + "\n"

	var warnings []string
	message, threadID := ParseJSONStreamInternal(
		strings.NewReader(input),
		func(s string) { warnings = append(warnings, s) },
		nil, nil, nil,
	)

	if !strings.Contains(message, "invalid --effort") {
		t.Errorf("message = %q, want the agy error text", message)
	}
	if threadID != "" {
		t.Errorf("threadID = %q, want empty", threadID)
	}
	if len(warnings) == 0 {
		t.Error("expected a warning for the agy error, got none")
	}
}

// The agy branch has to win over the gemini one, which triggers on any
// non-empty `status`. If the ordering ever flips, this returns "" and the
// consultation silently produces nothing.
func TestParseAgyNotSwallowedByGeminiBranch(t *testing.T) {
	input := `{"conversation_id":"abc","status":"SUCCESS","response":"agy spoke"}` + "\n"

	message, _ := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)

	if message != "agy spoke" {
		t.Fatalf("message = %q, want %q — the gemini branch has taken the agy event", message, "agy spoke")
	}
}

// Guard the other direction: a genuine gemini event must not be captured by
// the agy detection.
func TestParseGeminiStillRoutesToGeminiBranch(t *testing.T) {
	input := strings.Join([]string{
		`{"type":"init","session_id":"sess-1"}`,
		`{"type":"content","role":"assistant","content":"gemini spoke"}`,
		`{"type":"result","status":"success"}`,
	}, "\n") + "\n"

	message, threadID := ParseJSONStreamInternal(strings.NewReader(input), nil, nil, nil, nil)

	if message != "gemini spoke" {
		t.Errorf("message = %q, want %q", message, "gemini spoke")
	}
	if threadID != "sess-1" {
		t.Errorf("threadID = %q, want %q", threadID, "sess-1")
	}
}
