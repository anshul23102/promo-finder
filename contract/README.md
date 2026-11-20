# Run contract, version 1

One JSON document another system can read without our UI. `promo/contract.py` writes it (`python3 -m promo.contract RUN_FOLDER INPUT`; the browser runner includes it in **Download all run files**) and validates it. Golden examples: [`examples/run.v1.json`](examples/run.v1.json) (a run on one made-up episode) and [`examples/handoff.v1.json`](examples/handoff.v1.json) (that run after one editor trimmed a cut). `tests/test_contract.py` regenerates the first and fails if the code drifts from it.

| Surface | What it holds |
|---|---|
| `schema`, `run_id` | `promo-finder.run/1`. A reader must refuse any other value (`validate()` does). `run_id` = `run-` plus the idempotency key. |
| `engine` | Name, version, and a hash of the finder's own source files, so a result says which code made it. `rules_version` for rules runs. |
| `input` | `show_id`, title, `mode` (`rules` or `ai`), `locale` and `target_audience` (null until given), the source file (name, SHA-256, `revision` if the storage adapter supplies one) and every episode (stable `E001` IDs, cue count, duration). The parser's TXT and ZIP path is the first adapter; a storage adapter can hand over a stream or a permitted URI instead. |
| `timeline` | Integer centiseconds, **start inclusive, end exclusive**, relative to each episode, in the user's source timebase. `media_timebase` is null until footage conforms; `cutlist.edl` is a 30 fps non-drop reference only. |
| `suggestions` | Stable id, rank, post slot, ordered segments (episode ID, start, end, duration), `opening` and `closing` evidence with cue IDs, a one-line rationale and its source (`model` or `template`), spoiler level, provenance (`found_by`, `scored_by`, `judged_by`). `status` is `timing_checked` (rules found it) or `judge_shortlisted` (a cold-viewer model passed it). It is never `human_approved` in this document. |
| `status` | `state` (`queued`, `running`, `partial`, `succeeded`, `failed`, `cancelled`), episodes requested and parsed, candidates, shortlisted, fallbacks, non-sensitive warnings (no script text), model IDs and usage. A run whose model stopped early is `partial`, not `succeeded`. |
| `review` | Empty by design, with `ready_requires_human_decision: true`. |
| `invariants` | Input hash, config hash and the config itself, the idempotency key (`sha256(input | config | engine)`, so the same input run the same way is the same job), and a checksum of each output file. |

## Editor handoff (`promo-finder.handoff/1`)

`apply_review(run_document, decisions)` turns a person's decisions into the approved list. A decision names a suggestion, `keep`, `trim` or `pass`, and a **named reviewer**. Rules, matching the review page: Pass cuts are left out and listed; a trim that makes the cut shorter than 20 s or longer than 60 s is not accepted and the cut is listed for re-review; any accepted trim sets `needs_rereview` because the hook, closing and rationale were written for the original boundaries. The document carries the source hash and revision so a later change to the script can be reconciled.

## Adapters, in the order they were proved

1. **Portable worker.** `promo.browser.run_upload` reads an upload from memory, writes a run to a temporary folder and returns the page payload plus this contract; the CLI is unchanged. The same function runs in Pyodide.
2. **OpenAI-compatible model route.** `--model openai-compatible:<name>` with `PROMO_BASE_URL` and `PROMO_API_KEY` set outside the repo; `--judge` can route a different model. `tools/swap_smoke_test.py` checks structured answers, provenance, cache replay, a wrong key and an HTTP 500 against a local stand-in.
3. **Editor handoff.** The golden `handoff.v1.json` is the thing to show an editor to learn which fields are useful, which frame-rate or reel naming their tool accepts, and where the human decision belongs, before any editing-tool plugin is built.

## Not decided here (ask Kuku)

Their model gateway and approved providers, the job runtime, identity, retention, and the editing-tool format. The contract is shaped so those plug in without changing the finder.
