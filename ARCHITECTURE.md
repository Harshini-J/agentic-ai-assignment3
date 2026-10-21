# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 42 to 44):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below is RepoMind as Assignment 3 leaves it: the Tools row now cites the boundary check, the key and the verified write, and Control & Policy, Observability and Evaluation each gain what Part C and Part D added.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:120` | present |
| Harness | The loop, with three bounds checked in code; a plan validated before it runs, and an executor that runs only the plan's steps, drafts the comment first and opens the PR before posting it | `agent/loop.py:38`, `ways/planned.py:98`, `ways/planned.py:136`, `ways/planned.py:300` | present |
| Tools | Five tools behind one registry; every call is checked at the boundary before it runs (types, enums, lengths), errors say what to fix, a protocol error gets a generic result, reads are retried below the model, and every write carries a key the harness derives, is read back after a failure, and is retried with the same key or stops | `tools/__init__.py:208`, `tools/__init__.py:54`, `tools/__init__.py:145`, `tools/__init__.py:266`, `tools/__init__.py:308`, `tools/__init__.py:188`, `tools/__init__.py:334`, `harness/tracker.py:208` | present |
| Memory & State | A run's progress file, outside the model's context | `ways/notes.py:67` | partial: nothing survives a run |
| Control & Policy | A pre-call hook that denies when it raises; a write makes at most three attempts, and one still unconfirmed ends the run escalated; the second pass holds a draft that still fails | `tools/__init__.py:274`, `tools/__init__.py:334`, `ways/planned.py:343`, `ways/planned.py:354` | partial: the only hook allows every call, and no one is told of an escalation |
| Observability | One trace line per model call and per tool call, the plan as data before it runs, and one call-record line per attempt, written by the registry | `agent/loop.py:50`, `ways/planned.py:77`, `harness/calls.py:47`, `tools/__init__.py:255` | partial: traces and a call record, no alerts |
| Evaluation | The grounded check reads the tracker, never the agent; Part D counts what a tool surface costs per call and per run, and each arm's writes from the tracker's database | `eval/check_triage.py:7`, `eval/count_surface.py:58`, `eval/price_surface.py:43`, `eval/count_writes.py:56` | partial: offline only |

**Empty layers:** 0 of 7, and four are partial. Assignment 3 makes Tools present in code: the registry checks every call at the boundary, and every write is keyed by the harness, read back after a failure, retried with the same key and recorded. The four others stay partial because nothing carries into a later run, no person is told of an escalation, the traces are read only after the run, and the measurements are offline.