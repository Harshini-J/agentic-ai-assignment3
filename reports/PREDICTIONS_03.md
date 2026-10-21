# Predictions for Part D

Written before any evaluation run under FLAKY_WRITES. The measurement is 12 runs per arm: the six evaluation issues, twice each.

## Duplicates left in the tracker

| | Duplicate comments | Duplicate PRs |
|---|---|---|
| My harness | 0 | 0 |
| Control | about 10, across about 8 runs | 0 |

- **My harness:** 0 duplicate comments and 0 duplicate PRs. The harness generates a key for each write and checks the tracker before every attempt. If a write times out, it reads the tracker to see whether it succeeded before retrying, preventing duplicate writes.

- **The control:** 0 duplicate PRs and about 10 duplicate comments across 12 runs, occurring in about 8 runs. The harness checks for an existing PR by branch before each attempt, preventing duplicates. However, the comment key changes with every attempt, so the check misses comments that have already been posted. Since about half of the write attempts time out after committing, retries create duplicate comments.

## The tool I expect the model to misuse most
- `search_code`. It has four required arguments and the longest description. In my development runs, the model made two to four searches per run and once used an unsupported exclusion glob that the tool rejected.
