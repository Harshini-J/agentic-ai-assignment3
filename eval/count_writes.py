"""Part D, task 4: what the tracker holds, counted from its database and not from traces.

For each arm's finished runs on the six evaluation issues, it reads the tracker's tables by
run_id and counts the writes. A run belongs to an arm by the switches recorded in its
run_start line: key_mode derived (my harness) or uuid with verify off (the control). It also
checks the tracker's committed timeouts against each run's call record.

    python eval/count_writes.py             # prints the table, writes eval/writes_counts.json
    python eval/count_writes.py --fill      # also fills the writes object of reports/LAB_03.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.check_triage import check                      # noqa: E402
from harness.formats import parse_triage_comment          # noqa: E402
from harness.tracker import Tracker                       # noqa: E402

EVAL_ISSUES = range(4201, 4207)
FIELDS = ("runs", "comments_per_run_max", "duplicate_comment_runs", "prs_correct_runs",
          "committed_timeouts", "escalated", "triage_passes")


def read_runs() -> list[dict]:
    """Every finished evaluation run on the real backend, with its arm, end and issue."""
    runs = []
    for path in sorted((ROOT / "runs").glob("planned-*.jsonl")):
        if path.name.endswith(".calls.jsonl") or path.name.startswith("_"):
            continue
        lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        start = next((l for l in lines if l["type"] == "run_start"), None)
        if start is None or start.get("lab") != "03" or start["issue"] not in EVAL_ISSUES:
            continue
        if start.get("backend") not in ("anthropic", "openai-compatible") or not any(l["type"] == "run_end" for l in lines):
            continue
        sw = start.get("switches") or {}
        arm = ("control" if sw.get("key_mode") == "uuid" and sw.get("verify") == "off" else
               "harness" if sw.get("key_mode", "derived") == "derived" and sw.get("verify", "on") == "on" else None)
        if arm is None or not sw.get("flaky_writes"):
            continue
        end = next((l for l in lines if l["type"] == "end"), {})
        runs.append({"run_id": start["run_id"], "arm": arm, "issue": start["issue"],
                     "ended": end.get("terminal_reason", "completed"), "detail": end.get("detail", "")})
    return runs


def count_arm(tracker: Tracker, runs: list[dict], answers: dict) -> dict:
    attempts = tracker.table("attempts")
    comments_all = tracker.table("comments")
    prs_all = tracker.table("prs")
    out = {"runs": len(runs), "comments_per_run_max": 0, "duplicate_comment_runs": 0, "prs_correct_runs": 0,
           "committed_timeouts": 0, "escalated": 0, "triage_passes": 0}
    extra_comments, failed = 0, []
    for r in runs:
        rid, issue = r["run_id"], r["issue"]
        comments = [c for c in comments_all if c["run_id"] == rid and c["issue"] == issue]
        prs = [p for p in prs_all if p["run_id"] == rid]
        out["comments_per_run_max"] = max(out["comments_per_run_max"], len(comments))
        if len(comments) > 1:
            out["duplicate_comment_runs"] += 1
            extra_comments += len(comments) - 1
        wants_pr = bool(comments) and (parse_triage_comment(comments[0]["body"])[1] or "none").strip().lower() != "none"
        right = [p for p in prs if p["state"] == "open" and p["branch"] == f"repomind/issue-{issue}"]
        if (wants_pr and len(prs) == 1 and len(right) == 1) or (not wants_pr and not prs):
            out["prs_correct_runs"] += 1
        out["committed_timeouts"] += sum(1 for a in attempts if a["run_id"] == rid and a["outcome"] == "timeout_after_commit")
        out["escalated"] += r["ended"] == "escalated"
        passed = check(tracker, rid, issue, answers[issue])
        out["triage_passes"] += passed
        if not passed:
            label, file = parse_triage_comment(comments[0]["body"]) if comments else (None, None)
            failed.append({"run": rid, "issue": issue, "comments": len(comments), "got": [label, file],
                           "want": [answers[issue]["label"], answers[issue]["file"]]})
    out["extra_comments"] = extra_comments
    out["failed_checks"] = failed
    return out


def reconcile(tracker: Tracker, runs: list[dict]) -> dict:
    """Check the tracker's committed timeouts against each run's call record: every attempt the
    tracker logged as timeout_after_commit must have a timeout line with the same key."""
    attempts = tracker.table("attempts")
    out = {"committed_in_tracker": 0, "timeouts_in_call_record": 0, "committed_with_a_line": 0}
    for r in runs:
        lines = []
        path = ROOT / "runs" / f"{r['run_id']}.calls.jsonl"
        if path.exists():
            lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        timeout_keys = [l["key"] for l in lines if l["outcome"] == "timeout"]
        committed = [a for a in attempts if a["run_id"] == r["run_id"] and a["outcome"] == "timeout_after_commit"]
        out["committed_in_tracker"] += len(committed)
        out["timeouts_in_call_record"] += len(timeout_keys)
        out["committed_with_a_line"] += sum(1 for a in committed if a["key"] in timeout_keys)
    return out


def load_answers() -> dict:
    """{issue number: {label, file}} for the evaluation issues, from fixtures/answers.yaml."""
    raw = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())
    found = {}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if str(k).isdigit() and isinstance(v, dict) and "label" in v:
                    found[int(k)] = v
                else:
                    walk(v)
    walk(raw)
    return {n: found[n] for n in EVAL_ISSUES}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fill", action="store_true", help="write the counts into reports/LAB_03.json")
    a = ap.parse_args()
    answers = load_answers()
    tracker = Tracker()
    runs = read_runs()
    result = {arm: count_arm(tracker, [r for r in runs if r["arm"] == arm], answers) for arm in ("harness", "control")}
    (ROOT / "eval" / "writes_counts.json").write_text(json.dumps(result, indent=2) + "\n")

    print(f"{'':28} {'harness':>8} {'control':>8}")
    for f in FIELDS + ("extra_comments",):
        print(f"{f:28} {result['harness'][f]:>8} {result['control'][f]:>8}")
    for arm in ("harness", "control"):
        rec = reconcile(tracker, [r for r in runs if r["arm"] == arm])
        print(f"  {arm:8} tracker: {rec['committed_in_tracker']} timed out after committing; call record: "
              f"{rec['timeouts_in_call_record']} timeouts, {rec['committed_with_a_line']} of the committed ones have a line")
    for arm in ("harness", "control"):
        for bad in result[arm]["failed_checks"]:
            print(f"  {arm:8} failed {bad['run']}: {bad['comments']} comment(s), got {bad['got']}, want {bad['want']}")
    if a.fill:
        path = ROOT / "reports" / "LAB_03.json"
        report = json.loads(path.read_text())
        for arm in ("harness", "control"):
            report["writes"][arm] = {f: result[arm][f] for f in FIELDS}
        path.write_text(json.dumps(report, indent=2) + "\n")
        print("filled reports/LAB_03.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())