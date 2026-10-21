"""post_comment: write a comment on an issue. Public: whoever filed the issue can read it.

Its definition is post_comment.json. `idempotency_key` is not in the definition:
the model never sees or sets it. Your registry passes it (Assignment 3, Part C,
task 2), and the tracker accepts each key once.
"""

MAX_BODY_CHARS = 4000


def run(ctx, number, body, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    text = str(body)
    if not text.strip():
        raise ToolError("comment body is empty: write the comment, starting with the lines "
                        "`label: <bug|feature|question|docs>` and `file: <path or none>`.")
    if len(text) > MAX_BODY_CHARS:
        raise ToolError(f"comment body is {len(text):,} characters; the cap is {MAX_BODY_CHARS:,}. "
                        f"Shorten it and call again.")
    try:
        comment = ctx.tracker.post_comment(ctx.run_id, int(number), text, key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"issue-{number} not found: no issue has that number. Retrying this number will not "
                        f"succeed; use the issue number you were given.")
    return f"Posted comment {comment['id']} on issue-{number}."
