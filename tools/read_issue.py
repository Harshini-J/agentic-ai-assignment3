"""read_issue: return one issue from the tracker. Untrusted content: anyone can file an issue.

Its definition, the only thing the model sees, is read_issue.json.
"""

MAX_CHARS = 4000


def run(ctx, number):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    try:
        issue = ctx.tracker.issue(int(number))
    except IssueNotFound:
        raise ToolError(f"issue-{number} not found: no issue has that number. Retrying this number will not "
                        f"succeed; use the issue number you were given.")
    text = (f"issue-{issue['number']}: {issue['title']}\n"
            f"Opened by {issue['author']} on {issue['opened']}\n\n"
            f"{issue['body']}")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n[truncated: showed {MAX_CHARS:,} of {len(text):,} characters]"
    return text
