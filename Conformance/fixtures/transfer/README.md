# Transfer-text fixture

The cross-SDK parity fixture for the **memory-transfer text adapter** — the pasted text
that ChatGPT, Claude, and Gemini exchange today when a user runs the standard memory-export
prompt ("Format each entry as: `[date saved, if available] - memory content`", in a single
code block).

| File | Purpose |
|---|---|
| `sample-export.txt` | A realistic assistant reply: prose around a fenced block; entries with `-`, `–`, `—` separators; `[Jan 2026]` and `[date unknown]` brackets; a bare ISO date; a `-` bullet and a `1.` numbered line; a `##` header and an ALL-CAPS header; an indented continuation line; non-ASCII text; and an exact duplicate entry. |
| `expected-episode.jsonl` | The `items/episode.jsonl` stream both SDKs MUST produce from it when parsed with `source = "chatgpt"` and `now = 2023-11-14T22:13:20Z` (epoch `1700000000`) and exported through a store that returns episodes sorted by id. |
| `generate.py` | Regenerates the expected file with the Python SDK. |

What the expected output pins down: fence handling (surrounding prose ignored), separator
tolerance, bullet/number stripping, header → `categories`, continuation joining, verbatim
`transfer_date_raw` / `transfer_section` / `transfer_line` metadata, date parsing (ISO,
`Month YYYY`, unknown → undated), deterministic `tx_<sha256[:24]>` ids, and duplicate
collapse (the repeated last line produces no second episode).

The Python test `tests/test_adapter_transfer.py::test_fixture_parity_with_swift` and the
Swift test `TransferTextAdapterTests.testFixtureParityWithPython` both compare against the
same bytes. This directory is byte-identical in both repositories.
