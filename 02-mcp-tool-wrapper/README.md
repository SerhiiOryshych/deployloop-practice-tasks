# Task 2: wrap an internal API as an MCP-style tool

Time box: **90-120 minutes**. Python 3.11+, plus `jsonschema` (pinned in
`../requirements.txt`). No MCP SDK is used or needed.

## The brief

An internal ticket-search HTTP API must be exposed to an LLM agent as a tool.
`ticket_tool.py` has a first version that works when everything goes right. It
leaks credentials into logs, accepts bad input, crashes on upstream errors, has
no timeout, returns unbounded output, and hands ticket text to the model
verbatim. Fix and finish it so that all tests in `tests/` pass.

The protocol is plain dicts, shaped like MCP `tools/list` and `tools/call`
(see the docstring in `ticket_tool.py`). The upstream is `fake_ticket_api.py`
(in-process fake; read it first).

Requirements:

1. **Schemas.** `inputSchema` and `outputSchema` are JSON Schema (2020-12).
   Input: `query` (1-200 chars, not blank, no control characters), `status`
   (`open|pending|closed`, optional), `limit` (integer 1-50, default 10), no
   other keys. Output: `total_matches`, `returned`, `truncated`, `tickets[]`
   (`id`, `title`, `status`, `priority`, `updated_at`, `snippet`, `flags[]`).
2. **Strict validation** before any upstream call. `True` is not an integer;
   `"5"` is not an integer. Error details name the field, but never echo
   the offending value.
3. **Auth passthrough.** Forward `Authorization` (and a well-formed
   `X-Request-Id`) to the upstream. Drop all other caller headers. Never write
   credentials to logs, error messages, or results, also not through exception
   text.
4. **Timeout.** `timeout_s` bounds the upstream call.
5. **Error mapping.** Never raise to the caller; return
   `isError: true` with `structuredContent.error = {code, message, retryable}`.
   Codes: `invalid_input`, `unknown_tool`, `unauthorized`, `forbidden`,
   `rate_limited` (with `retry_after_s` when the upstream sends a valid number),
   `upstream_unavailable`, `upstream_unreachable`, `timeout`,
   `bad_upstream_response`, `upstream_error`. Messages are fixed text; do not
   copy upstream bodies into them.
6. **Output limits.** Both the text content and `json.dumps(structuredContent)`
   stay within `max_output_chars`. Cut long fields, then drop tickets from the
   end. Set `truncated` honestly and report the real `total_matches`.
7. **Prompt-injection-safe output (stretch).** Ticket text is data written by strangers.
   Strip invisible and control characters, neutralize markup so text cannot close
   the data envelope you wrap it in, start the text output with a notice that the
   content is untrusted data, and label tickets that look like instructions
   (`flags: ["possible_prompt_injection"]`). Validate the upstream payload too.

Run: `pytest -q`. Optional: if you keep your own solution in a `solution/`
folder, `DEPLOYLOOP_SOLUTION=1 pytest` tests it.

**Stretch.** Requirement 7 is a stretch goal. Its tests are marked `stretch`
and run by default. To skip them and focus on requirements 1-6, run
`pytest -q -m "not stretch"`. To run only them, use `-m stretch`. A good
attempt can stop after requirements 1-6 and explain how it would do 7.

## Contract (what the tests check)

You can pass without reading `tests/` if you follow this section.

Input and validation (requirements 1 and 2)
- `inputSchema.properties.query.maxLength` is exactly `200`. Longer queries
  are `invalid_input`. `inputSchema.required` is `["query"]`.
- `limit` has `minimum` 1 and `maximum` 50. `status` has an `enum` with
  `open`, `pending`, `closed`. `additionalProperties` is `false`.
- Default `limit` 10 is sent upstream, so params are `{"q", "limit"}` and
  `status` only when the caller gave it. `arguments` of `None` is
  `invalid_input`, not a crash.
- `invalid_input` has `structuredContent.error.details`: a list of objects.
  Each has a `path` string that is the field name (for example `"limit"`).
  Never put the offending value in `message` or `details`. A result for a
  100,000-char query must stay under 1,500 serialized chars.

Errors (requirement 5)
- Every error has `code`, `message`, `retryable` (bool), and
  `content[0].text` equals `message`.
- Retryable: `rate_limited`, `upstream_unavailable`, `upstream_unreachable`,
  `timeout`. Not retryable: the others.
- `Retry-After` is used only when it is a plain non-negative integer string;
  otherwise leave `retry_after_s` out.

Logging (requirement 3)
- The tool must emit at least one log record per call through the `logging`
  module (`logger` argument, or the `ticket_tool` logger). Log names of
  headers, never values. Never log the token, also not through `str(exc)`.

Output (requirements 6 and 7)
- Snippet is capped at 400 characters. Title and other long fields are cut too.
- `len(json.dumps(structuredContent))` and `len(content[0].text)` are both at
  most `max_output_chars`.
- Each ticket in `structuredContent.tickets[]` has `flags`, a list (empty when
  the ticket looks normal).

Stretch contract (requirement 7)
- Remove zero-width, bidi, BOM and control characters from ticket text. Remove
  them, do not replace them with a space (`"Printer\u200b broken"` becomes
  `"Printer broken"`).
- In `content[0].text`, wrap each ticket in exactly one tag pair named
  `untrusted_ticket_data`: `<untrusted_ticket_data ...>` and
  `</untrusted_ticket_data>`. N tickets give N opening and N closing tags.
  Ticket text must not be able to add or close a tag, so no `<` appears in
  `snippet` (replace or escape it).
- Line 1 of `content[0].text` is a notice that contains the words "untrusted"
  and "instructions", and it ends with a newline (`\n`) before the tickets.
- A ticket whose title or body looks like an instruction to the model gets
  `flags == ["possible_prompt_injection"]` and its opening tag carries the
  attribute `flags="possible_prompt_injection"`. Check after stripping hidden
  characters. Cover: "ignore/disregard previous instructions", role prefixes
  such as `SYSTEM:` and `Assistant:`, "you are now ...", requests to run a tool,
  and links used to send data out. Plain tickets must stay unflagged.

## What "good" looks like

- All tests pass and you can say which requirement each failing test came from.
- One validation path (the schema), not a second hand-written one.
- Error mapping is a small table, not nested `if`s; exceptions are caught at one
  place with a deliberate type list.
- Logging policy: names of headers, never values; exception type, not
  `str(exc)`. You can say why `str(exc)` is dangerous.
- You are honest about the limits of labeling: a regex flag does not make
  injection impossible. It is one layer. You can name the others.

## Interviewer follow-up questions

Security
1. Why is labeling and escaping not enough? What does a real injection that
   passes your filter look like? Which layers remain (least-privilege tool
   scopes, no write tools in the same session, human approval, output
   classifiers, separate quarantined model)?
2. The agent runs for many users. How do you make sure user A's credentials never
   reach user B's call? Where does the token live between calls?
3. The ticket body contains a URL and the model renders markdown. What is the
   data-exfiltration risk and how do you close it?
4. How would you red-team this tool? Write three attack tickets.

Reliability and design
5. When should the tool retry by itself and when should it hand
   `retryable: true` to the agent? What is the risk of agent-driven retries?
6. Add `get_ticket(id)` and `add_comment(id, text)`. What changes in the schema,
   the auth model and the approval policy for the write tool? How do you make
   `add_comment` idempotent?
7. Pagination: should the tool return a cursor? How does the model know that
   there is more data, and how do you stop it from looping?
8. Why a size limit in characters? What would you use if the budget is in tokens?

Observability
9. What do you log and measure per call (latency, error code, truncation rate,
   flagged-ticket rate) without logging user content or secrets?
10. How do you detect that the model keeps calling with invalid input, and
    what do you change (schema descriptions, examples, error messages)?
