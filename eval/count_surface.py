"""Part D, task 1: what the tool surface costs per request, counted by difference.

Each count sends the same one-message request twice, with and without the thing being
counted, and takes the difference in prompt_tokens (which includes cached tokens). The
starter's definitions are read from the repository's first commit and reduced to the
fields of tools.SENT each file has, with no examples; yours are sent as your registry
sends them (its schemas).

    python eval/count_surface.py            # writes eval/surface_counts.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.plan import _tool_list                      # noqa: E402
from harness import ROOT as HARNESS_ROOT               # noqa: E402
from harness.backends import make_backend               # noqa: E402
from harness.client import ModelClient                  # noqa: E402
from harness.pricing import PriceSheet                  # noqa: E402
from harness.settings import load_settings              # noqa: E402
from tools import MODULES, SENT, RunContext, default_tools   # noqa: E402

FIRST_COMMIT = "fd8fd12"
SYSTEM = "You are a connectivity test."
PROMPT = "Do not call any tool. Answer with the word ok."


def starter_schemas() -> list[dict]:
    """The starter's five definitions, from the first commit, as its registry sent them."""
    out = []
    for module in MODULES:
        raw = subprocess.run(["git", "show", f"{FIRST_COMMIT}:tools/{module}.json"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        definition = json.loads(raw)
        out.append({k: definition[k] for k in SENT if k in definition})
    return out


def my_schemas() -> list[dict]:
    return default_tools(RunContext(run_id="count", tracker=None, repo_root=ROOT / "fixtures" / "repo")).schemas


def prompt_tokens(client, *, tools=None, extra: str = "") -> int:
    """prompt_tokens of one request: the same one message, with or without tools or text."""
    message = PROMPT + (("\n\n" + extra) if extra else "")
    kwargs = {"tools": tools} if tools else {}
    reply = client.create(system=SYSTEM, messages=[{"role": "user", "content": message}], **kwargs)
    return int(reply.usage.prompt_tokens)


def count(client, schemas: list[dict]) -> dict:
    base = prompt_tokens(client)
    together = prompt_tokens(client, tools=schemas) - base
    alone = {s["name"]: prompt_tokens(client, tools=[s]) - base for s in schemas}
    listed = prompt_tokens(client, extra=_tool_list(schemas)) - base
    return {"together": together, "alone": alone, "list": listed}


def main() -> int:
    settings = load_settings(HARNESS_ROOT / "settings.yaml")
    client = ModelClient(make_backend(settings.provider, settings), PriceSheet(HARNESS_ROOT / "pricing.yaml"))
    result = {"model": settings.model, "first_commit": FIRST_COMMIT,
              "before": count(client, starter_schemas()), "after": count(client, my_schemas())}
    out = ROOT / "eval" / "surface_counts.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    for label in ("before", "after"):
        r = result[label]
        print(f"{label:6} five together {r['together']:>6}   planner's list {r['list']:>6}")
        for name, tokens in r["alone"].items():
            print(f"       {name:19} alone {tokens:>6}")
    t = client.totals()
    print(f"cost of counting: ${t['cost_usd']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())