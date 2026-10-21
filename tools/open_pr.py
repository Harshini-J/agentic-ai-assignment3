"""open_pr: open a draft pull request on the mock remote. New in Assignment 3.

Its definition is open_pr.json. The mock remote needs no commits: a PR is a branch,
a title and a body, stored in the tracker's database. `idempotency_key` is not in
the definition: your registry passes it, as for post_comment.
"""

MAX_TITLE_CHARS = 120
MAX_BODY_CHARS = 4000


def run(ctx, number, branch, title, body, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    expected = f"repomind/issue-{int(number)}"
    if str(branch) != expected:
        raise ToolError(f"branch must be exactly {expected} for issue-{number}, not {branch!r}. "
                        f"Call again with branch {expected!r}.")
    if not str(title).strip() or len(str(title)) > MAX_TITLE_CHARS:
        raise ToolError(f"title must be 1 to {MAX_TITLE_CHARS} characters; it is {len(str(title))}.")
    if not str(body).strip() or len(str(body)) > MAX_BODY_CHARS:
        raise ToolError(f"body must be 1 to {MAX_BODY_CHARS:,} characters; it is {len(str(body)):,}.")
    try:
        pr = ctx.tracker.open_pr(ctx.run_id, int(number), str(branch), str(title), str(body), key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"issue-{number} not found: no issue has that number. Retrying this number will not "
                        f"succeed; use the issue number you were given.")
    return f"Opened draft pull request {pr['id']} from {branch} for issue-{number}."
