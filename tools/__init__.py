"""RepoMind's tools, and the registry that runs them.

Each tool is two files with one name: tools/<module>.json, its definition, the only
thing the model sees of it; and tools/<module>.py, the code that runs it. Rename a
tool inside its .json file and keep both file names. tools/roles.yaml says which
tool plays each of RepoMind's five roles (checks/FORMATS.md, section 11.2).

Assignment 3 starts with five definitions that are weak on purpose: generic names,
free-text filters, nothing said about an empty result, no cap on a response, no
examples. You rewrite them (Part A), and you make this registry check every call
at the boundary, return errors a model can repair from, key every write, verify a
write that failed, record every call and run a hook before each one (Parts A to C).

The registry's interface, which the runner, your ways and the checker use
(checks/FORMATS.md, section 11.3):

    registry = ToolRegistry(ctx)          # ctx is a RunContext, below
    registry.schemas                      # what the vendor gets: name, description, input_schema, strict
    registry.names()                      # the tools' names, in MODULES order
    registry.definition(name)             # the whole definition file, examples included
    registry.hooks.append(hook)           # hook(name, tool_input) runs before every call
    registry.call(name, tool_input, plan_step=None) -> ToolResult

A registry is bound to one run: every write is stamped with that run's ID. Build
one per run with `default_tools(ctx)`.
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import hashlib
import uuid

TOOLS_DIR = Path(__file__).resolve().parent

# The five modules, in the order the registry offers them. Keep these file names.
MODULES = ("read_issue", "search_repo", "read_file", "post_comment", "open_pr")

# The fields of a definition the vendor gets. Everything else in the file (the
# examples, notes of your own) stays here.
SENT = ("name", "description", "input_schema", "strict")

# Content rules the schema cannot carry under strict mode (Lecture 3, slide 22):
# {module: {argument: (low, high)}}. For a string argument, low 1 means it must not be
# empty or only whitespace, and high is its most characters (None for no maximum).
# For an integer argument, low is its smallest value and high its largest.
# The maximums repeat the constants in the tools' own files (MAX_QUERY_CHARS,
# MAX_BODY_CHARS, MAX_TITLE_CHARS); change them together.
CONTENT_RULES = {
    "read_issue": {"number": (1, None)},
    "search_repo": {"query": (1, 200)},
    "read_file": {"path": (1, None)},
    "post_comment": {"number": (1, None), "body": (1, 4000)},
    "open_pr": {"number": (1, None), "title": (1, 120), "body": (1, 4000)},
}

# What the model is told about a protocol error: fixed, under 200 characters, and
# naming neither the unknown tool nor any of ours. The detail goes to the harness log.
PROTOCOL_ERROR_TEXT = ("Error: that call could not be processed, and rewording it will not help. "
                       "Use only the tools you were offered, each with the arguments its definition lists.")

# Retry allocation (Lecture 3, slide 36). Only the read tools are retried here, and only
# for an OS fault that may pass. A write is never retried here: its timeout is ambiguous,
# and Part C verifies it by reading it back.
READ_MODULES = ("read_issue", "search_repo", "read_file")
TRANSIENT_RETRIES = 2          # so a read makes at most 3 attempts
TRANSIENT_BACKOFF_S = 0.2      # waits 0.2 s, then 0.4 s
PERMANENT_OS_ERRORS = (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError)

# The two tools that write to the tracker. Each call to one carries an idempotency key,
# which the harness derives; it is never in a definition and the model never sees it.
WRITE_MODULES = ("post_comment", "open_pr")

WRITE_ATTEMPTS = 3             # a write makes at most three attempts, in both of Part D's arms

class ToolError(Exception):
    """A tool failed in a way the model can be told about. Becomes an is_error result."""


@dataclass
class ToolResult:
    content: str
    is_error: bool
    latency_s: float

class WriteUnconfirmed(Exception):
    """A write may or may not have happened and the harness could not tell, or it was still
    unconfirmed after its last attempt. The run must stop and ask a person: the executor
    catches this and ends the run escalated. It is never shown to the model."""


@dataclass
class RunContext:
    run_id: str
    tracker: object                    # harness.tracker.Tracker
    repo_root: object                  # pathlib.Path to fixtures/repo
    calls: object = None               # harness.calls.CallRecord: runs/<run_id>.calls.jsonl
    harness_log: object = None         # pathlib.Path: runs/<run_id>.harness.log, for protocol errors
    switches: dict = field(default_factory=dict)   # harness.switches.current(), as the runner read them


def load_definition(module: str) -> dict:
    return json.loads((TOOLS_DIR / f"{module}.json").read_text())

def _render_description(definition: dict) -> str:
    """The description with the examples added at the end, which every vendor reads."""
    text = definition["description"]
    examples = definition.get("examples") or []
    if not examples:
        return text
    lines = [f"{i}. {json.dumps(e['input'], ensure_ascii=False)}  ({e['note']})"
             for i, e in enumerate(examples, 1)]
    return text + "\n\nExamples:\n" + "\n".join(lines)

def _kinds(spec: dict) -> list:
    kinds = (spec or {}).get("type")
    return kinds if isinstance(kinds, list) else [kinds]


def _check_content(props: dict, rules: dict, args: dict) -> list[str]:
    """Lengths and ranges, for the arguments that have the right type to measure."""
    problems = []
    for name, (low, high) in rules.items():
        value = args.get(name)
        kinds = _kinds(props.get(name))
        if isinstance(value, str) and "string" in kinds:
            if low and not value.strip():
                limit = f"1 to {high:,} characters" if high else "at least 1 character"
                problems.append(f"{name}: empty; give {limit}.")
            elif high is not None and len(value) > high:
                problems.append(f"{name}: {len(value):,} characters, over the maximum of {high:,}; shorten it.")
        elif isinstance(value, int) and not isinstance(value, bool) and "integer" in kinds:
            if low is not None and value < low:
                problems.append(f"{name}: {value}, below the minimum of {low}.")
            if high is not None and value > high:
                problems.append(f"{name}: {value}, above the maximum of {high}.")
    return problems


def _check_arguments(definition: dict, rules: dict, args: dict):
    """The arguments with enum values in their canonical case, and every problem found."""
    from harness.schema import errors      # imported here so tools never needs harness at import time

    schema = definition["input_schema"]
    props = schema.get("properties", {})
    fixed = dict(args)
    for name, value in args.items():
        allowed = (props.get(name) or {}).get("enum")
        if allowed and isinstance(value, str):
            fixed[name] = next((a for a in allowed if isinstance(a, str) and a.lower() == value.lower()), value)
    problems = [f"{line}." for line in errors(fixed, schema)]
    problems += _check_content(props, rules, fixed)
    return fixed, problems


def _result_schema(shape: dict) -> dict:
    """A JSON schema for a declared result_shape, so harness.schema.errors can check it."""
    props = {name: {"type": kind} for name, kind in shape.get("fields", {}).items()}
    for list_name, item_fields in shape.get("items", {}).items():
        props[list_name] = {"type": "array",
                            "items": {"type": "object", "required": list(item_fields),
                                      "properties": {k: {"type": v} for k, v in item_fields.items()}}}
    return {"type": "object", "required": list(props), "properties": props}

def _check_result(definition: dict, content: str) -> list[str]:
    """Why a result is not the shape its description promises. [] when it is."""
    shape = definition.get("result_shape")
    if not shape:
        return []
    problems = []
    limit = shape.get("max_chars")
    if limit is not None and len(content) > limit:
        problems.append(f"{len(content):,} characters, over the declared {limit:,}")
    if shape.get("format") == "json":
        try:
            data = json.loads(content)
        except ValueError:
            return problems + ["not valid JSON"]
        from harness.schema import errors
        problems += errors(data, _result_schema(shape))
    return problems

def derive_key(run_id: str, plan_step, args: dict) -> str:
    """The idempotency key of one write (Lecture 3, slide 38): a hash of the run, the plan
    step the call executes, and its arguments in canonical form (keys sorted, no
    whitespace). The same intended action gets the same key on every attempt."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    payload = f"{run_id}\n{plan_step}\n{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _without_key(args: dict) -> dict:
    """A write's arguments as its key hashes them: the call record shows no key inside them."""
    return {k: v for k, v in args.items() if k != "idempotency_key"}

def allow_every_call(name: str, tool_input: dict):
    """The default pre-call hook: None allows the call. It allows everything; what matters is
    that it runs before every call, and that a hook that raises denies the call."""
    return None

class ToolRegistry:
    def __init__(self, ctx: RunContext, modules=MODULES):
        self.ctx = ctx
        self.hooks: list = [allow_every_call]
        self._tools: dict[str, tuple[dict, object]] = {}
        self._rules: dict[str, dict] = {}
        self._reads: set[str] = set()
        self._writes: set[str] = set()
        self._module_names: dict[str, str] = {}
        for module in modules:
            definition = load_definition(module)
            self._tools[definition["name"]] = (definition, importlib.import_module(f"tools.{module}"))
            self._rules[definition["name"]] = CONTENT_RULES.get(module, {})
            self._module_names[definition["name"]] = module
            if module in READ_MODULES:
                self._reads.add(definition["name"])
            if module in WRITE_MODULES:
                self._writes.add(definition["name"])

    @property
    def schemas(self) -> list[dict]:
        """The definitions as the vendor gets them, in MODULES order, ready for
        ModelClient.create(tools=...). Only name, description, input_schema and strict
        are sent; the examples are rendered into the end of the description."""
        out = []
        for definition, _ in self._tools.values():
            sent = {k: definition[k] for k in SENT if k in definition}
            sent["description"] = _render_description(definition)
            out.append(sent)
        return out

    def names(self) -> list[str]:
        return list(self._tools)

    def definition(self, name: str) -> dict:
        return self._tools[name][0]

    def _log(self, line: str) -> None:
        """One line to runs/<run_id>.harness.log, for what the model must not see."""
        path = getattr(self.ctx, "harness_log", None)
        if path:
            try:
                with open(path, "a") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass

    def _record(self, name: str, args: dict, plan_step, key: str | None, attempt: int, outcome: str,
                content: str, started: float, is_error: bool = True) -> None:
        """One line of runs/<run_id>.calls.jsonl (Lecture 3, slide 42), written here at the
        boundary, independently of what the agent says it did. Without a call record on the
        context (a test, a script) there is nothing to write."""
        calls = getattr(self.ctx, "calls", None)
        if calls is None:
            return
        calls.write(tool=name, args=args, outcome=outcome, is_error=is_error, result=content,
                    latency_s=time.monotonic() - started, plan_step=plan_step, key=key, attempt=attempt)

    def _protocol_error(self, what: str, start: float, name, received: dict, plan_step) -> ToolResult:
        """A protocol error is for the harness: the full detail goes to the log and to the call
        record, and the model gets a short, generic result that names neither the tool nor any
        of ours."""
        self._log(f"{_now()} protocol error: {what}")
        self._record(name, received, plan_step, None, 1, "protocol", what, start)
        return ToolResult(PROTOCOL_ERROR_TEXT, True, time.monotonic() - start)

    def _denied(self, name, tool_input) -> str | None:
        """Run every hook before the call. None when each one allows it (returns None). A hook
        that returns anything else denies the call, and a hook that raises denies it too: it
        fails closed. Returns the reason the model is told."""
        for hook in list(self.hooks):
            try:
                verdict = hook(name, dict(tool_input) if isinstance(tool_input, dict) else tool_input)
            except Exception as exc:
                self._log(f"{_now()} a pre-call hook raised {type(exc).__name__}: {exc}; "
                          f"the call to {name!r} is denied")
                return "A check that runs before every call failed, so the call was not made."
            if verdict is not None:
                reason = verdict if isinstance(verdict, str) and verdict.strip() else "a pre-call check refused it"
                self._log(f"{_now()} a pre-call hook denied the call to {name!r}: {reason}")
                return reason
        return None

    def _already_written(self, name: str, args: dict, key: str) -> str | None:
        """Check before you execute (Lecture 3, slide 39): one read of this run's own writes.
        Returns the confirmation the write would have returned if its effect is already in
        the tracker, and None if it is not. A pull request is found by its branch, a comment
        by its key."""
        module = self._module_names[name]
        tracker, run_id, number = self.ctx.tracker, self.ctx.run_id, args.get("number")
        if module == "open_pr":
            found = tracker.prs(run_id, branch=f"repomind/issue-{number}")
            if found:
                return f"Opened draft pull request {found[0]['id']} from {found[0]['branch']} for issue-{number}."
        elif module == "post_comment":
            found = tracker.comment_by_key(run_id, key)
            if found:
                return f"Posted comment {found['id']} on issue-{number}."
        return None

    def _run_with_retries(self, name: str, module, args: dict, plan_step) -> str:
        """Run a read. A transient OS fault is retried here, below the model, a bounded
        number of times: a retry in this loop costs latency, not a turn. Every attempt
        leaves a line in the call record."""
        attempts = 1 + (TRANSIENT_RETRIES if name in self._reads else 0)
        for attempt in range(1, attempts + 1):
            began = time.monotonic()
            try:
                content = module.run(self.ctx, **args)
            except PERMANENT_OS_ERRORS as exc:
                self._record(name, args, plan_step, None, attempt, "error", f"{type(exc).__name__}: {exc}", began)
                raise
            except OSError as exc:
                self._record(name, args, plan_step, None, attempt, "error", f"{type(exc).__name__}: {exc}", began)
                if attempt == attempts:
                    raise
                self._log(f"{_now()} transient {type(exc).__name__} in {name}, "
                          f"attempt {attempt} of {attempts}: {exc}; retrying")
                time.sleep(TRANSIENT_BACKOFF_S * attempt)
                continue
            except (ToolError, TypeError, ValueError) as exc:
                self._record(name, args, plan_step, None, attempt, "error", str(exc), began)
                raise
            self._record(name, args, plan_step, None, attempt, "ok", content, began, is_error=False)
            return content

    def _run_write(self, name: str, module, args: dict, plan_step) -> str:
        """A write, with the three exits (Lecture 3, slides 39 and 40). Before every attempt,
        one read checks whether the effect is already there. After a timeout the write may or
        may not have happened, so read it back: found, and the existing result is the answer;
        not found, retry with the same key; unreadable, or still unconfirmed after the third
        attempt, raise WriteUnconfirmed. Every attempt leaves a line in the call record: a
        timeout that the read-back then resolves leaves a second line, outcome ok.

        The two control switches change this loop and nothing else (Part D): KEY_MODE=uuid
        sends a fresh random key on every attempt, and VERIFY=off skips the read-back and
        retries blind. The check before each attempt stays."""
        from harness.tracker import ReadbackUnavailable, TrackerTimeout

        switches = getattr(self.ctx, "switches", None) or {}
        random_keys = switches.get("key_mode") == "uuid"
        verify = switches.get("verify", "on") != "off"
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            began = time.monotonic()
            if random_keys:
                args = {**args, "idempotency_key": uuid.uuid4().hex}
            key = args["idempotency_key"]
            shown = _without_key(args)
            try:
                existing = self._already_written(name, args, key)
            except ReadbackUnavailable as exc:
                self._log(f"{_now()} {name}: the tracker could not be read before attempt {attempt}")
                self._record(name, shown, plan_step, key, attempt, "error",
                             "the tracker could not be read, so it cannot be known whether the write "
                             "already happened", began)
                raise WriteUnconfirmed(f"{name}: the tracker could not be read, so it cannot be known "
                                       f"whether the write already happened") from exc
            if existing is not None:
                self._log(f"{_now()} {name}: the effect was already in the tracker, so nothing was written")
                self._record(name, shown, plan_step, key, attempt, "ok", existing, began, is_error=False)
                return existing
            try:
                content = module.run(self.ctx, **args)
            except TrackerTimeout as exc:
                self._log(f"{_now()} {name}: attempt {attempt} of {WRITE_ATTEMPTS} timed out; "
                          f"it may or may not have happened")
                self._record(name, shown, plan_step, key, attempt, "timeout", str(exc), began)
                if verify:
                    try:
                        existing = self._already_written(name, args, key)
                    except ReadbackUnavailable as err:
                        raise WriteUnconfirmed(f"{name} timed out and the tracker could not be read back, "
                                               f"so it cannot be known whether it happened") from err
                    if existing is not None:
                        self._log(f"{_now()} {name}: read back after the timeout, and it had happened")
                        self._record(name, shown, plan_step, key, attempt, "ok", existing, began, is_error=False)
                        return existing
                if attempt == WRITE_ATTEMPTS:
                    raise WriteUnconfirmed(f"{name} was still unconfirmed after {WRITE_ATTEMPTS} attempts") from exc
                continue
            except (ToolError, TypeError, ValueError) as exc:
                self._record(name, shown, plan_step, key, attempt, "error", str(exc), began)
                raise
            self._record(name, shown, plan_step, key, attempt, "ok", content, began, is_error=False)
            return content

    def call(self, name: str, tool_input: dict, plan_step=None) -> ToolResult:
        """Run one tool: the pre-call hooks first, then the boundary check on its arguments,
        then the tool, then the check on its result before the model sees it. Expected
        failures come back as is_error results; anything else raises, and your loop decides
        what that means (terminal_reason tool_error). Every attempt leaves a line in the
        call record.

        `plan_step` is the id of the plan step the call runs for, from ctx.call_tool,
        or None when the model chose the call (the agent's loop)."""
        start = time.monotonic()
        if tool_input is None:
            received = {}
        elif isinstance(tool_input, dict):
            received = tool_input
        else:
            received = {"value": repr(tool_input)[:200]}

        reason = self._denied(name, tool_input)
        if reason is not None:
            self._record(name, received, plan_step, None, 1, "denied", reason, start)
            return ToolResult(f"Error: this call was denied and nothing ran. {reason}"[:600], True,
                              time.monotonic() - start)

        entry = self._tools.get(name)
        if entry is None:
            return self._protocol_error(
                f"no tool named {name!r}; the tools are {', '.join(self._tools)}", start, name, received, plan_step)
        definition, module = entry

        def failed(message: str) -> ToolResult:
            return ToolResult(f"Error: {message}"[:600], True, time.monotonic() - start)

        args = {} if tool_input is None else tool_input
        if not isinstance(args, dict):
            return self._protocol_error(
                f"{name} was called with {type(args).__name__} arguments, not an object: {str(args)[:200]!r}",
                start, name, received, plan_step)
        args, problems = _check_arguments(definition, self._rules[name], args)
        if problems:
            names = ", ".join(definition["input_schema"].get("properties", {}))
            result = failed(f"{' '.join(problems)} Nothing ran: fix these and call {name} again. "
                            f"Its arguments are {names}.")
            self._record(name, received, plan_step, None, 1, "rejected", result.content, start)
            return result
        run_args = args
        try:
            if name in self._writes:
                run_args = {**args, "idempotency_key": derive_key(self.ctx.run_id, plan_step, args)}
                content = self._run_write(name, module, run_args, plan_step)
            else:
                content = self._run_with_retries(name, module, run_args, plan_step)
        except (ToolError, TypeError, ValueError) as exc:
            return failed(str(exc))
        except OSError as exc:
            if name not in self._reads:
                raise          # a write's timeout is handled in _run_write; anything else is not ours to hide
            self._log(f"{_now()} {name}: {type(exc).__name__}: {exc}")
            if isinstance(exc, PERMANENT_OS_ERRORS):
                return failed(f"{name} cannot read what it needs, and this will not succeed with any "
                              f"arguments. Do not retry it; carry on without it.")
            return failed(f"{name} hit a temporary fault and still failed after {1 + TRANSIENT_RETRIES} "
                          f"attempts. This is not a problem with your call: the same call may work later, "
                          f"but changing its arguments will not help.")
        bad = _check_result(definition, content)
        if bad:
            self._log(f"{name}: result broke its declared shape: {'; '.join(bad)}")
            self._record(name, args, plan_step, run_args.get("idempotency_key"), 1, "error",
                         f"result broke its declared shape: {'; '.join(bad)}", start)
            return failed(f"{name} returned a result in an unexpected shape. This is a fault in the tool, "
                          f"not in your call: retrying with other arguments will not help.")
        return ToolResult(content, False, time.monotonic() - start)

def default_tools(ctx: RunContext) -> ToolRegistry:
    return ToolRegistry(ctx)
