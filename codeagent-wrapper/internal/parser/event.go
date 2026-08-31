package parser

import "github.com/goccy/go-json"

// JSONEvent represents a Codex JSON output event.
type JSONEvent struct {
	Type     string     `json:"type"`
	ThreadID string     `json:"thread_id,omitempty"`
	Item     *EventItem `json:"item,omitempty"`
	Usage    *Usage     `json:"usage,omitempty"`
}

// Usage is the token usage a backend reported for the turn.
// The containing pointer distinguishes an absent usage object from zero usage.
//
// Two backends fill it and they do not agree on the field names. Codex emits
// `cached_input_tokens` on `turn.completed`; claude emits the same idea split in
// two on its `type:"result"` event -- `cache_read_input_tokens` for what a cache
// served and `cache_creation_input_tokens` for what was written into one and
// billed as fresh input. Decoding both names into one struct is why `CachedIn()`
// exists: the caller wants "how much came from cache" without caring who said it.
type Usage struct {
	InputTokens              int `json:"input_tokens"`
	CachedInputTokens        int `json:"cached_input_tokens"`         // codex
	CacheReadInputTokens     int `json:"cache_read_input_tokens"`     // claude
	CacheCreationInputTokens int `json:"cache_creation_input_tokens"` // claude
	OutputTokens             int `json:"output_tokens"`

	// Filled by the parser from the enclosing event, not from the `usage`
	// object, so they are never decoded from it. CostReported carries the
	// distinction a bare float cannot: a fully cached turn can genuinely cost
	// zero, and that is a different fact from a backend that never reports
	// cost at all -- which is every codex and agy call.
	TotalCostUSD  float64 `json:"-"`
	CostReported  bool    `json:"-"`
	ResolvedModel string  `json:"-"`

	// TokensReported separates "the backend sent a usage object" from "the
	// parser had to synthesise one to carry cost". Without it a claude result
	// that reports cost but no usage would be written down as a call that
	// consumed zero tokens.
	TokensReported bool `json:"-"`
}

// CachedIn is the input tokens a cache served, under whichever name the backend
// used. Cache *creation* is deliberately excluded: those tokens were charged as
// fresh input, so counting them as cached would understate what the call cost.
func (u Usage) CachedIn() int {
	if u.CachedInputTokens != 0 {
		return u.CachedInputTokens
	}
	return u.CacheReadInputTokens
}

// EventItem represents the item field in a JSON event.
type EventItem struct {
	Type string      `json:"type"`
	Text interface{} `json:"text"`
}

// ClaudeEvent for Claude stream-json format.
type ClaudeEvent struct {
	Type      string `json:"type"`
	Subtype   string `json:"subtype,omitempty"`
	SessionID string `json:"session_id,omitempty"`
	Result    string `json:"result,omitempty"`
}

// UnifiedEvent combines all backend event formats into a single structure
// to avoid multiple JSON unmarshal operations per event.
type UnifiedEvent struct {
	// Common fields
	Type string `json:"type"`

	// Codex-specific fields
	ThreadID string          `json:"thread_id,omitempty"`
	Item     json.RawMessage `json:"item,omitempty"` // Lazy parse

	// Shared: codex puts `usage` on `turn.completed`, claude on `type:"result"`.
	Usage *Usage `json:"usage,omitempty"`

	// Claude-specific fields
	Subtype   string `json:"subtype,omitempty"`
	SessionID string `json:"session_id,omitempty"`
	Result    string `json:"result,omitempty"`
	// Only claude reports what the turn cost and which model actually served
	// it. `modelUsage` is keyed by the resolved name (`claude-opus-5[1m]`),
	// which can differ from the model string the role was configured with --
	// and that difference is the whole reason to record it.
	TotalCostUSD *float64                   `json:"total_cost_usd,omitempty"`
	ModelUsage   map[string]json.RawMessage `json:"modelUsage,omitempty"`

	// Agy-specific fields. agy runs under `--output-format json`, which emits
	// exactly one object rather than a stream, so these carry the whole
	// result. `Status` doubles as a guard in the claude detection
	// (`event.Status == ""`); it came from the retired gemini stream shape.
	Status         string `json:"status,omitempty"`
	ConversationID string `json:"conversation_id,omitempty"`
	Response       string `json:"response,omitempty"`
	Error          string `json:"error,omitempty"`
}

// ItemContent represents the parsed item.text field for Codex events.
type ItemContent struct {
	Type string      `json:"type"`
	Text interface{} `json:"text"`
}
