# Assignment 3 · A tool surface that tells the truth, and writes that happen once

Fill in each section. Every number here must match `reports/LAB_03.json`, and
every count of writes must come from the tracker's database, not from your traces.

## Part A · The five definitions

- Strict tools, optional parameters, nullable or union-typed parameters (from
  `python tools/audit_schemas.py`):
  strict tools 5, optional parameters 0, nullable or union-typed parameters 1; names namespaced by suffix

- Does your vendor have a strict mode? What did `make ping` show?
 Yes. Anthropic compiles a tool's schema when it is marked `"strict": true`, and
  limits a request to 20 strict tools (`tools/audit_limits.yaml`). `make ping` with
  claude-sonnet-5 showed all 5 definitions accepted in one request, with 5 marked
  strict (4,755 prompt tokens, 55 output tokens, $0.010060 for the final definitions; an earlier ping, before later edits to the descriptions, was 3,850). It made three calls: a tool call, a final answer, and the five definitions.

- Consolidation, in one line:
None; no task always follows the same sequence of calls (the search and read steps depend on what the issue says, and the PR and comment are separate writes: a PR can be closed later, but a posted comment cannot be taken back), so I kept five tools.

`search_repo`, before and after:

| Before | After |
|---|---|
| **name:** `search_repo` | **name:** `search_code` (suffix names the service) |
| **strict:** not set | **strict:** `true` |
| **description:** "Search the code." | **description:** says what the JSON holds, that zero matches is a success (`count: 0`), that a malformed search is an error, and the caps. Full text in `tools/search_repo.json` |
| **query** (string): "Text to look for" | **query** (string): literal, case-insensitive, not a regex; 1 to 200 characters |
| **max_results** (integer): "How many results. Default 10." | removed; `response_format` sets the cap |
| **filter** (string): "Optional filter expression" | **path_glob** (string or null): a documented glob such as `src/**/*.ts`; null searches everything; includes only, cannot exclude with `!` or `\|` |
| **deep** (boolean): "Whether to do a deep search. Default false." | **source** (enum `index`, `disk`): the prebuilt index (fast, with `index_age`) or the files themselves (current) |
| no such parameter | **response_format** (enum `concise`, `detailed`): concise (5 results, the cheap choice, used first) or detailed (20) |
| **required:** `["query"]` | **required:** all four properties |
| **additionalProperties:** not set | **additionalProperties:** `false` |
| **examples:** none | **examples:** two, a typical search then a hard one |
| **result:** text lines; a malformed query and no match both return "No matches." | **result:** JSON with `count`, `query_valid`, `truncated`, `index_age`; no match is a success, a malformed query is an error |


## Part B · Errors

| Tool | Transient | Permanent | Ambiguous |
|---|---|---|---|
| `read_issue` | None: the tracker reads a local file. If a read ever failed before returning, it would be safe to retry; the model would never see it | Issue number does not exist; number below 1 | None: a read has no effect |
| `search_code` | The index file cannot be read before any search runs; safe to retry | Empty or whitespace-only query; query over 200 characters; invalid `path_glob`; `source` or `response_format` outside its enum | None: a read has no effect |
| `read_file_code` | The file cannot be read from disk before any content is returned; safe to retry | Path does not exist (the error names near misses such as `src/Report.ts` for `src/report.ts`); path outside the repository or in `config/`; not a text file; `response_format` outside its enum | None: a read has no effect |
| `post_comment_issue` | None: the tracker is local, and a failure before the request is sent would be safe to retry | Empty body; body over 4,000 characters; issue does not exist | Write timeout: the comment may or may not have been saved. Read comments back by key to confirm |
| `open_pr` | None: a failure before sending is safe to retry | Branch is not `repomind/issue-<n>`; empty or over-long title or body; issue does not exist | Write timeout: the PR may or may not exist. Read back by branch or key to confirm |

- Protocol errors: `generic_result`. Unknown tool names or non-object arguments are logged in full to `runs/<run_id>.harness.log`, while the model receives a fixed message under 200 characters that names no tool and explains rewording will not help. I chose this over `end_run` because one invalid call should not discard paid work or interrupt a partially completed task, such as opening a PR without posting its comment. Since the model cannot fix the error by rewording, the message makes that clear, and the run's step and token limits prevent endless retries.

- The exact text of your `read_file` near-miss error for `src/report.ts`:
Error: src/report.ts does not exist. Did you mean src/Report.ts, src/report.tsx, src/reports.ts? Paths are exact and case-sensitive; call again with one of these. Retrying src/report.ts will not succeed.

- **Retry policy:** The registry retries read tools up to twice, with a short wait, when a temporary OS error occurs. These retries add latency but do not use extra model turns. Permanent errors are not retried because retrying cannot succeed, and writes are not retried because a write timeout may leave the result uncertain; Part C handles this by reading the result back. Error messages explain what to do next: missing issues or files will not be fixed by retrying, invalid arguments need correction, and a read that still fails may work if tried again later.

## Part C · Writes that may already have happened

- The key formula:
The idempotency key is the first 32 hexadecimal characters of the SHA-256 hash of run_id, the plan step's id, and the write arguments in canonical JSON format, each on a separate line. The registry generates the key once per call and reuses it for every attempt. If the body or plan step changes, a different key is generated.

- How a run whose file is `none` skips the PR:
The executor handles this with a check. Since the planner creates the plan before reading the issue, it cannot know whether a file is needed and always includes the PR step. The executor drafts the comment and runs the second pass before any writes. If the draft's file line is `none`, it skips the PR step and records a `skipped` event in the trace. Otherwise, it opens the PR and posts the same draft as the comment. If the second pass holds the draft, the run stops before either write; if opening the PR fails, the comment is not posted.

- One call-record line for a write:

```json
{"run_id": "planned-4192-s01-6dc664", "t": 0.092, "tool": "post_comment_issue", "role": "comment", "args": {"number": 4192, "body": "label: bug\nfile: src/ingest/dedupe.ts"}, "plan_step": 5, "key": "f77f9b5b34fea00e86991340592b654c", "attempt": 1, "outcome": "ok", "is_error": false, "result": "Posted comment 26 on issue-4192.", "latency_s": 0.001, "cost_usd": 0.0}
```

## Part D · Measure

1. The surface price, with its arithmetic: the five definitions together, each alone, and the
   planner's tool list, the starter's and yours; then a mean harness-arm run, each call
   charged for what it carried, and the same calls with all five on every one:

Counted by difference on claude-sonnet-5 (the same one-message request with and without what is counted, difference in `prompt_tokens`, `eval/count_surface.py`):

| | Starter | Mine |
|---|---|---|
| The five definitions together | 929 | 3,735 |
| `read_issue` alone | 437 | 733 |
| `search_repo` / `search_code` alone | 519 | 1,400 |
| `read_file` / `read_file_code` alone | 427 | 938 |
| `post_comment` / `post_comment_issue` alone | 460 | 964 |
| `open_pr` alone | 502 | 1,116 |
| The planner's tool list (`_tool_list`) | 156 | 1,972 |

The definition counts include the vendor's tool-use preamble, which is charged once per call that uses a tool. The five individual counts total 2,345 tokens for the starter and 5,151 for mine, compared with 929 and 3,735 when counted together. The difference is 1,416 tokens in both cases, which accounts for four preambles at 354 tokens each. Excluding the preambles, the actual tool definitions use 575 tokens for the starter and 3,381 for mine.

Using the input rate of `claude-sonnet-5` from `pricing.yaml` ($2.00 per million uncached tokens), I calculated the cost with `eval/price_surface.py`. Each model call is charged for the tool definitions it receives, and plan and revise calls also include the tool list. I excluded submit_plan because it is unchanged. Each run averages 6.92 model calls, including 2.17 planning or revision calls.

|Average per harness run | Definition tokens | Cost |
|---|---|---|
| Starter definitions | 2,642 | $0.005285 |
| My definitions | 9,859 | $0.019718 |
| All five tools on every call (3,735 each) | 25,834 | $0.051668 |

My rewrite costs about 3.7 times as much as the starter, adding around $0.0144 per run. However, the planned approach still costs much less than including all five tools on every call: about $0.0197 compared with $0.0517. Calls that need only one tool carry just that definition (938–1,400 tokens), rather than all five (3,735 tokens).

Planning and revision calls are the most expensive because each includes my 1,972-token tool list. With 2.17 such calls per run, they account for 43% of definition-token costs.

The extra tokens improved validation and error handling. An empty search now returns count: 0 instead of being confused with a malformed query, invalid source values are rejected with the allowed options identified, and src/report.ts no longer silently opens src/Report.ts on a case-insensitive disk. However, misuse has not been eliminated: the harness arm still recorded 10 failed tool calls across 12 runs. Caching could reduce the cost of repeated definitions, but it would not reduce the space they occupy in the model's context.

2. The table, from the tracker:

| Measure | Your harness | Control |
|---|---|---|
| Triage comments per run (should be 1) | 1 in every run (max 1) | max 3; 9 of 12 runs had more than one (14 extra comments) |
| Open PRs from `repomind/issue-<n>` per run (1 when the file is not `none`, else 0) | correct in 12 of 12 | correct in 12 of 12 |
| Writes that timed out and had in fact committed | 14 | 20 |
| Runs that ended `escalated` | 0 | 1 |
| Triage success (your grounded check from Assignment 1) | 8 of 12 | 2 of 12 |

The tracker's `attempts` table and the call record agree: every one of the 14 (harness) and 20 (control) writes that timed out after committing has a timeout line with its key in the call record, which also holds the timeouts that happened before the commit (15 and 23 in all).

3. The four shapes of tool misuse: which your surface narrowed, with evidence for
   each; which is still standing; did you see it in your runs, and how would you
   know if you had not?

- **Right tool, wrong arguments: narrowed, not removed.** The 12 harness runs had 10 failed calls, all using the correct tool with wrong arguments: 5 searches (the exclusion glob `!(*.md|src/i18n/*)` twice in 4203-s01, `source: 'grep'` in 4204-s01, and `source: 'repo'` twice in 4205-s01) and 5 reads (four nonexistent paths, including `src/parsers/csvParser.js`, and the directory `src/export/`). The boundary refused the three invalid `source` values before the tool ran, while the tool rejected the two exclusion globs as malformed searches. Every run finished. In development, an invented exclusion glob failed twice in a 4192 run. After I clarified `path_glob`, it did not recur in the next two runs, but it appeared again in 4203-s01. The change helped but did not eliminate the problem. I did not test the starter's surface on the evaluation issues, so I cannot compare rates.

- **Wrong tool, valid call: not seen, closed by the plan.** Each fill call offers one tool, and no `off_plan` events occurred across the 12 runs. The plan prevents this misuse, not the tool names.

- **Correct call, misread result: seen, not narrowed, no visible cost.** The search description says to use `source: disk` when `index_age` exceeds one day, but none of the 26 searches did. Rerunning zero-count searches on disk gave the same counts, so the answers were unchanged.

- **No call at all: still standing, not narrowed by the surface. Did I see it? Yes, indirectly.** No direct cases appeared across 57 `execute` calls, but four wrong answers followed failed reads. Five runs had failed reads; four failed the check, while none of the other seven did. The fifth, 4205-s01, correctly answered `file: none` to a question. With no second read step, the model continued without verifying the file: three answers said `none` for a bug, and one named a directory. Slide 53 reports a 36% failure share in the MCP-Atlas 2026 preprint by Scale AI authors, but my 12 runs are too few for comparison. To detect missing calls directly, I would need known-answer labels showing whether a tool was required and whether it was called; without them, a run that made no call looks the same as a run that did not need one.

4. Every prediction in `reports/PREDICTIONS_03.md` that missed, and why:

- **Control duplicates:** I predicted about 10 duplicate comments in 8 runs, but the tracker recorded 14 extra comments in 9 runs. The run count was close, but I underestimated the comment count by 4. The actual rates were close to my estimate that about half of attempts time out after committing: 54% of comment attempts timed out after committing and 39% succeeded. However, more runs made extra comment attempts, and five needed all three attempts. Of the 20 writes that timed out after committing, 15 were comments and 5 were PRs protected by the branch check. One run (4205-s03) timed out after committing on all three attempts and never succeeded, so the extra comments were 15 − 1 = 14.

- **Most misused tool:** I predicted `search_code`, but `read_file_code` had the higher failure rate. Both had 5 failed calls, but `search_code` failed 19% of the time compared with 42% for `read_file_code`. I expected search to fail more because it has four required arguments and a longer description. The search failures were the kind I described, an unsupported glob, plus invented `source` values; the read failures came from nonexistent paths, which clearer tool definitions would not prevent.

- **Hits:** My harness had 0 duplicate comments and 0 duplicate PRs. The control also had 0 duplicate PRs because the branch check protects them.

## AI assistance

Which tool, what it wrote, and what you checked:

AI tools: Anthropic Claude Code; GitHub Copilot (inline autocomplete in VS Code)

Date: 19 - 21 October 2026

Understanding the existing codebase: Claude Code helped me understand the starter code before I changed it: what the registry in `tools/__init__.py` provides (schemas, call, hooks, plan_step), what ctx provides (ctx.tracker, ctx.calls, ctx.harness_log, ctx.switches, ctx.call_tool), how `harness/tracker.py` simulates a lying tracker (FLAKY_WRITES, READBACK_FAIL, the attempts table), how harness/calls.py defines the call record, and where each format is defined in checks/FORMATS.md (section 11 and `reports/LAB_03.json`).

I used it to explain parts of the assignment I didn't understand.

- **Part A:** how the six rules apply to a tool definition, how the strict-mode limits are counted (optional parameters, union types, nesting), and why lengths and ranges move out of the schema into the boundary check.
- **Part B:** the difference between a protocol error and a tool execution error, why the model should not see the first, and what makes an error repairable.
- **Part C:** why a timed-out write is ambiguous, how an idempotency key and a check before every attempt make a retry safe, and what the three exits are.
- **Part D:** how counting by difference prices a tool surface, and how to count each arm's writes from the tracker and not from traces.

**What it wrote:**

- GitHub Copilot: inline autocomplete suggestions while I was coding
- Claude Code: edits to the prompts in `prompts/` (planner.md, executor.md, reviser.md, rewrite.md) for the new tool names and the PR step, which I edited.
- Claude Code: one-off read-only commands and scratch scripts, kept outside the repository, to read traces and call records, count failed calls and recount tracker rows.
- Claude Code: `ARCHITECTURE.md`, searched the repo and identified where the model call and tools are invoked.
- Claude Code: drafts of the five tool definitions (`tools/*.json`), `tools/roles.yaml`, and the changes to `tools/*.py`, which I edited
- Claude Code: drafts of the registry in `tools/__init__.py` (boundary check, protocol errors, read retries, keys, the verified write with its three exits, call record, pre-call hook), which I edited and tested
- Claude Code: drafts of the near-miss path check in `tools/read_file.py`
- Claude Code: drafts of the changes to `ways/planned.py` (the plan rule, the PR step, the draft before either write).
- Claude Code: `eval/count_surface.py`, `eval/price_surface.py` and `eval/count_writes.py`, which I fixed and ran

**What I checked:**

- **`ARCHITECTURE.md`:** printed the line each `file:line` reference lands on and checked it against its row.
- **Autocomplete suggestions:** checked every suggestion by hand before keeping it.
- **Prompts in `prompts/`:** searched `executor.md`, `reviser.md`, `rewrite.md` and `planner.md` for the old tool names (nothing left), then read the traces of the real-model development runs: the planner wrote `open_pr` before `post_comment_issue` in every run I read, and every run finished.
- **Scratch scripts and one-off commands:** they only read. I cross-checked their numbers against `make check-03` and against each other.
- **`tools/*.json`, `roles.yaml` and `tools/*.py`:** ran `make audit` (5 strict tools, 0 optional parameters, 1 nullable parameter) and `make ping`; checked the example facts for issues 4191 and 4192 against `fixtures/answers.yaml` and the issue files; ran the search with no match (`count: 0`, `query_valid: true`) and four malformed queries (all errors); checked the caps (5 results of 2,627, the file read cut at 4,000 characters with a note) and the `issue-<n>` form in the outputs.
- **Registry in `tools/__init__.py`:** ran a script for every case the checker uses: 15 malformed calls refused before the tool ran, the enum case, the length rules, the result shape, protocol errors and what reached the harness log, read retries, the key formula, the check before each attempt, the call record and the hook, and the three write scenarios with scripted faults.
- **`tools/read_file.py`:** ran `src/report.ts` (it fails and names `src/Report.ts`, `src/report.tsx` and `src/reports.ts`) and an exact path (it still reads).
- **`ways/planned.py`:** ran scripted models for a draft naming no file (the PR is skipped) and a draft naming one, then real-model development runs under `FLAKY_WRITES` (every run one PR and one comment) and under `READBACK_FAIL` (the third exit, no duplicates).
- **`eval/` scripts:** checked the surface counts against the two pings (the gap of 2,806 tokens matches), recomputed the pricing arithmetic by hand, fixed the `usage` bug in the counting script, and matched the writes table against `make check-03`.