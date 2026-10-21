"""search_repo: literal, case-insensitive text search over the private codebase.

Its definition is search_repo.json. It reads a prebuilt index,
fixtures/search_index/index.json, of every text file under fixtures/repo except
config/, and the index records when it was built. With deep set, it reads the files
themselves instead. Results come back in path order, one line each, as
path:line: excerpt, then one line saying when the index was built, how many lines
matched and how many are shown: the truncation and the index's age.

**Malformed**, for Assignment 3 (Part A, task 1), is any of three things:
  1. a query that is empty or only whitespace;
  2. a query longer than MAX_QUERY_CHARS;
  3. a filter that is not a valid glob (glob_problem, below).
This stub answers a malformed query exactly as it answers one that matched nothing,
"No matches.": the defect Part A removes. The two must differ in the raw response.
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {"config", "node_modules", ".git"}
HARD_CAP = 20
MAX_QUERY_CHARS = 200
INDEX = "fixtures/search_index/index.json"
GLOB_CHARS = re.compile(r"^[A-Za-z0-9_.\-/*?\[\]{},]+$")

CONCISE = {"max_results": 5, "excerpt_chars": 80}
DETAILED = {"max_results": HARD_CAP, "excerpt_chars": 160}

def glob_problem(pattern: str) -> str | None:
    """Why `pattern` is not a valid path glob, or None when it is one."""
    if pattern.startswith("/"):
        return "a glob is relative to the repository root; it cannot start with /"
    if ".." in pattern.split("/"):
        return "a glob cannot leave the repository (..)"
    if not GLOB_CHARS.match(pattern):
        return "a glob uses letters, digits, / . _ - and the wildcards * ? [ ] { }; no spaces, colons or quotes"
    depth = 0
    for ch in pattern:
        depth += {"[": 1, "]": -1}.get(ch, 0)
        if depth not in (0, 1):
            return "a glob's [ and ] must pair up"
    if depth:
        return "a glob's [ and ] must pair up"
    if pattern.count("{") != pattern.count("}"):
        return "a glob's { and } must pair up"
    return None


def problem(query, path_glob=None) -> str | None:
    """Why this search is malformed, or None when it is well-formed."""
    text = str(query or "")
    if not text.strip():
        return "the query is empty"
    if len(text) > MAX_QUERY_CHARS:
        return f"the query is {len(text)} characters long; the cap is {MAX_QUERY_CHARS}"
    if path_glob not in (None, ""):
        return glob_problem(str(path_glob))
    return None


def _expand(pattern: str) -> list[str]:
    """{a,b} alternatives, which fnmatch does not know."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    return [p for option in match.group(1).split(",")
            for p in _expand(pattern[:match.start()] + option + pattern[match.end():])]


def _matches(path: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path, p.replace("**/", ""))
               for p in _expand(pattern))


def load_index(root: Path) -> dict:
    return json.loads((Path(root) / INDEX).read_text())


def _disk(repo_root: Path) -> dict[str, list[str]]:
    files = {}
    for path in sorted(Path(repo_root).rglob("*")):
        rel = path.relative_to(repo_root)
        if path.is_file() and not (set(rel.parts) & EXCLUDED_DIRS):
            try:
                files[rel.as_posix()] = path.read_text().splitlines()
            except UnicodeDecodeError:
                continue
    return files


def age(built_at: str, now: float | None = None) -> str:
    built = datetime.strptime(built_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    days = int(((now or time.time()) - built.timestamp()) // 86400)
    return "today" if days < 1 else f"{days} day{'s' if days != 1 else ''} ago"

def run(ctx, query, path_glob=None, response_format="concise", source="index"):
    from tools import ToolError

    why = problem(query, path_glob)
    if why is not None:
        raise ToolError(f"malformed search, nothing was searched: {why}. "
                        f"Fix the query or path_glob and call again; this is not the same as no matches. "
                        f"The same query or path_glob will fail again.")
    source = str(source).lower()
    if source not in ("index", "disk"):
        raise ToolError(f"source must be index or disk, not {source!r}.")
    response_format = str(response_format).lower()
    if response_format not in ("concise", "detailed"):
        raise ToolError(f"response_format must be concise or detailed, not {response_format!r}.")
    mode = DETAILED if response_format == "detailed" else CONCISE
    repo_root = Path(ctx.repo_root)
    if source == "disk":
        files, index_age = _disk(repo_root), "not used (read from disk)"
    else:
        index = load_index(repo_root.parent.parent)
        files, index_age = index["files"], age(index["built_at"])
    needle = str(query).strip().lower()
    hits = [{"path": rel, "line": number, "excerpt": line.strip()[:mode["excerpt_chars"]]}
            for rel, lines in sorted(files.items()) if _matches(rel, path_glob)
            for number, line in enumerate(lines, 1) if needle in line.lower()]
    shown = hits[:mode["max_results"]]
    return json.dumps({"query": str(query).strip(), "query_valid": True, "path_glob": path_glob,
                       "source": source, "index_age": index_age, "count": len(hits),
                       "shown": len(shown), "truncated": len(hits) > len(shown), "results": shown})