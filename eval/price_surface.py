"""Part D, task 1, second half: what the tool surface costs in a mean harness-arm run.

Each model call in the harness arm's 12 runs is charged for the definitions it carried (its
`tools` field), at the model's input rate in pricing.yaml, uncached; a plan or revise call is
charged for the tool list as well, and submit_plan is left out because it is the same before and
after. Priced three ways: with the starter's counts, with mine, and as if every call had carried
all five of mine and nothing else. Counts come from eval/surface_counts.json.

    python eval/price_surface.py            # prints the arithmetic, writes eval/surface_price.json
    python eval/price_surface.py --fill     # also fills the surface object of reports/LAB_03.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.count_writes import read_runs   # noqa: E402

# The tool a name stood for before and after the rewrite, in the order of tools.MODULES.
RENAMED = {"read_issue": "read_issue", "search_code": "search_repo", "read_file_code": "read_file",
           "post_comment_issue": "post_comment", "open_pr": "open_pr"}


def harness_calls() -> list[list[dict]]:
    """The model_call lines of each harness-arm run, in order."""
    per_run = []
    for run in read_runs():
        if run["arm"] != "harness":
            continue
        lines = [json.loads(l) for l in (ROOT / "runs" / f"{run['run_id']}.jsonl").read_text().splitlines() if l.strip()]
        per_run.append([l for l in lines if l["type"] == "model_call"])
    return per_run


def price_run(calls: list[dict], counts: dict, rate: float, *, all_five: bool) -> float:
    """Tokens charged for definitions in one run, as dollars: one call's tools, or all five."""
    tokens = 0
    for call in calls:
        carried = [t for t in call.get("tools") or [] if t != "submit_plan"]
        if all_five:
            tokens += counts["together"]
            continue
        tokens += sum(counts["alone"][t] for t in carried)
        if call.get("purpose") in ("plan", "revise"):
            tokens += counts["list"]
    return tokens * rate / 1_000_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fill", action="store_true", help="write the surface object of reports/LAB_03.json")
    a = ap.parse_args()
    surface = json.loads((ROOT / "eval" / "surface_counts.json").read_text())
    prices = yaml.safe_load((ROOT / "pricing.yaml").read_text())["models"]
    rate = next(p["input"] for name, p in prices.items() if surface["model"].startswith(name))

    before = {"together": surface["before"]["together"], "list": surface["before"]["list"],
              "alone": {new: surface["before"]["alone"][old] for new, old in RENAMED.items()}}
    after = surface["after"]
    runs = harness_calls()
    n = len(runs)
    calls_per_run = sum(len(r) for r in runs) / n
    plan_calls = sum(1 for r in runs for c in r if c.get("purpose") in ("plan", "revise"))
    result = {
        "model": surface["model"], "input_rate_per_million": rate, "runs": n,
        "calls_per_run": round(calls_per_run, 2),
        "plan_or_revise_calls_per_run": round(plan_calls / n, 2),
        "cost_per_run_before": round(sum(price_run(r, before, rate, all_five=False) for r in runs) / n, 6),
        "cost_per_run_after": round(sum(price_run(r, after, rate, all_five=False) for r in runs) / n, 6),
        "cost_per_run_all_five": round(sum(price_run(r, after, rate, all_five=True) for r in runs) / n, 6),
    }
    (ROOT / "eval" / "surface_price.json").write_text(json.dumps(result, indent=2) + "\n")

    tokens = lambda cost: cost * 1_000_000 / rate
    print(f"{n} harness-arm runs, {calls_per_run:.2f} model calls per run "
          f"({plan_calls / n:.2f} plan or revise), input rate ${rate}/million, uncached")
    for label, key in (("starter's counts", "cost_per_run_before"), ("my counts", "cost_per_run_after"),
                       ("all five on every call", "cost_per_run_all_five")):
        print(f"  {label:24} {tokens(result[key]):>9,.0f} definition tokens  ${result[key]:.6f} per run")
    if a.fill:
        path = ROOT / "reports" / "LAB_03.json"
        report = json.loads(path.read_text())
        report["surface"].update({"calls_per_run": result["calls_per_run"],
                                  "cost_per_run_before": result["cost_per_run_before"],
                                  "cost_per_run_after": result["cost_per_run_after"],
                                  "cost_per_run_all_five": result["cost_per_run_all_five"]})
        path.write_text(json.dumps(report, indent=2) + "\n")
        print("filled reports/LAB_03.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())