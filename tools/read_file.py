"""read_file: return one file of the private codebase, whole.

Its definition is read_file.json. It reads the same files search_repo searches:
everything under fixtures/repo except config/. A path is relative to
fixtures/repo, as search results print it.

It asks the file system whether the path exists. On a case-insensitive disk, which
is macOS's default, src/report.ts then opens src/Report.ts and reports success
(Assignment 3, Part B, task 3).

A path must match a file exactly, including case. It is compared with the list of
files as they are spelled on disk, never opened to see whether it exists: on a
case-insensitive disk, which is macOS's default, src/report.ts would silently open
src/Report.ts. A path that is not in the list fails and names the close matches.
"""

import difflib
from pathlib import Path

MAX_CHARS = 20_000      # detailed
CONCISE_CHARS = 4_000   # concise, the default
NEAR_MISS_CUTOFF = 0.9   # how alike two paths must be, ignoring case, to be offered
MAX_SUGGESTIONS = 3

def _readable_files(root: Path, excluded: set) -> list[str]:
    """Every file this tool may read, relative to the root, spelled as it is on disk."""
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not (set(rel.parts) & excluded):
            files.append(rel.as_posix())
    return files

def _near_misses(rel: str, files: list[str]) -> list[str]:
    """Up to MAX_SUGGESTIONS paths that look like `rel` when case is ignored, best first."""
    want = rel.lower()
    scored = [(difflib.SequenceMatcher(None, want, f.lower()).ratio(), f) for f in files]
    close = sorted(((s, f) for s, f in scored if s >= NEAR_MISS_CUTOFF), key=lambda pair: (-pair[0], pair[1]))
    return [f for _, f in close[:MAX_SUGGESTIONS]]

def run(ctx, path, response_format="concise"):
    from harness.formats import normalize_path
    from tools import ToolError
    from tools.search_repo import EXCLUDED_DIRS

    response_format = str(response_format).lower()
    if response_format not in ("concise", "detailed"):
        raise ToolError(f"response_format must be concise or detailed, not {response_format!r}.")
    rel = normalize_path(str(path))
    if rel in (None, "none"):
        raise ToolError("path is empty: give a path exactly as a search_code result prints it.")
    root = Path(ctx.repo_root).resolve()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise ToolError(f"{path} is outside the repository. Use a path relative to the repository root; "
                        f"retrying this path will not succeed.")
    if set(target.relative_to(root).parts) & EXCLUDED_DIRS:
        raise ToolError(f"{path} is not readable: config/ is never exposed. Retrying will not succeed.")
    files = _readable_files(root, EXCLUDED_DIRS)
    if rel not in files:
        close = _near_misses(rel, files)
        if close:
            raise ToolError(f"{rel} does not exist. Did you mean {', '.join(close)}? Paths are exact and "
                            f"case-sensitive; call again with one of these. Retrying {rel} will not succeed.")
        raise ToolError(f"{rel} does not exist and nothing close to it does. Use a path exactly as a "
                        f"search_code result prints it. Retrying {rel} will not succeed.")
    try:
        text = (root / rel).read_text()
    except UnicodeDecodeError:
        raise ToolError(f"{rel} is not a text file. Retrying will not succeed; read a different file.")
    if text == "":
        return "[empty file]"
    detailed = response_format == "detailed"
    cap = MAX_CHARS if detailed else CONCISE_CHARS
    if len(text) > cap:
        note = (f"\n[truncated: showed {cap:,} of {len(text):,} characters]" if detailed else
                f"\n[truncated: showed {cap:,} of {len(text):,} characters; "
                f"call again with response_format \"detailed\" to read up to {MAX_CHARS:,}]")
        return text[:cap] + note
    return text
