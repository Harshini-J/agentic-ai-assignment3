# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan written as data before the issue is read; a validator with four checks; an executor that runs only the plan's steps; one checkpoint that may revise the plan; a second pass before the comment; detectors and a diff over traces; a progress file and a compaction
- **Removed:** the model's choice of the next tool, in the planned way
- **Constrained:** every tool call to a step of a validated plan; revisions to steps not yet done; the comment to drafts that pass the second pass

## Assignment 3
- **Added:** five tool definitions rewritten against the six rules (suffix names, enums, capped responses, two examples each, strict mode); a boundary validator on every call's arguments and every result; errors that say how to repair a call, and bounded read retries below the model; idempotency keys derived by the harness; a check before every write attempt, a read-back after a failure, and three exits; a call record and a pre-call hook; a pull request step before the comment
- **Removed:** the free-text tool descriptions; the free-form `filter`, `deep` and `max_results` arguments of the search; the model's own account of whether a write happened
- **Constrained:** every call to arguments that pass the schema and content rules before the tool runs; every write to one attempt in the tracker per key, with at most three attempts and a person asked when it cannot be confirmed