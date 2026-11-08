"""The file contract between the core and the agents.

Each agent writes one Markdown file. Most start with a header of `KEY: value`
lines that ends at the first blank line, followed by a `## Summary` of 3 to 5
bullets. `read()` parses and validates a file for its kind. A file that breaks
the contract raises MalformedFile; the core treats it as an invalid result,
never as a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from puxirum.config import RISKS

KEY_RE = re.compile(r"[A-Z][A-Z0-9-]*")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SUMMARY_MIN, SUMMARY_MAX = 3, 5


class MalformedFile(Exception):
    """An agent's file breaks the contract for its kind."""

    def __init__(self, path: Path | str, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path = Path(path)
        self.reason = reason


@dataclass(frozen=True)
class AgentFile:
    path: Path
    header: dict[str, str]
    text: str
    summary: tuple[str, ...]

    def section(self, heading: str) -> str | None:
        return section(self.text, heading)


# ---- Generic parsing ----------------------------------------------------------


def parse_header(text: str) -> dict[str, str]:
    """The `KEY: value` lines at the top of `text`, up to the first blank line.

    Raises ValueError on a line that isn't `KEY: value`, an empty value, or a
    repeated key.
    """
    fields: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            break
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not KEY_RE.fullmatch(key):
            raise ValueError(f"line {n} isn't a `KEY: value` header line: {line[:80]!r}")
        if not value:
            raise ValueError(f"header {key} is empty")
        if key in fields:
            raise ValueError(f"header {key} appears twice")
        fields[key] = value
    return fields


def section(text: str, heading: str) -> str | None:
    """Body of the `## heading` section, stripped, or None when it is absent."""
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def bullets(body: str) -> list[str]:
    """Top-level `- ` bullets of a section body. Raises ValueError on any other line."""
    items = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if not line.startswith("- ") or not line[2:].strip():
            raise ValueError(f"expected only `- ` bullets, found {line[:80]!r}")
        items.append(line[2:].strip())
    return items


def quote(text: str) -> str:
    """Text as a Markdown blockquote, so agents read it as data, never as instructions."""
    lines = (text.strip() or "(empty)").splitlines()
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines)


# ---- Per-kind validation ------------------------------------------------------

SPEC_SECTIONS = ("Summary", "Context", "Requirements", "Acceptance criteria", "Out of scope", "Assumptions")


def read(path: Path, kind: str, *, require_edge_cases: bool = False) -> AgentFile:
    """Parse and validate the file at `path` as `kind`.

    Kinds: intake, spec, build, review, decision, checks.
    Raises FileNotFoundError when the file is missing and MalformedFile when it
    breaks the contract.
    """
    if kind not in _RULES:
        raise ValueError(f"unknown file kind {kind!r}")
    text = path.read_text(encoding="utf-8")
    try:
        header = {} if kind == "spec" else parse_header(text)
        _RULES[kind](header, text)
        if kind == "spec" and require_edge_cases:
            edge = section(text, "Edge cases")
            if edge is None or edge.lower().rstrip(".") in ("", "none"):
                raise ValueError("a change with a user interface needs a non-empty `## Edge cases`")
        summary = _summary(text)
    except ValueError as e:
        raise MalformedFile(path, str(e)) from None
    return AgentFile(path=path, header=header, text=text, summary=tuple(summary))


def _summary(text: str) -> list[str]:
    body = section(text, "Summary")
    if body is None:
        raise ValueError("missing `## Summary`")
    items = bullets(body)
    if not SUMMARY_MIN <= len(items) <= SUMMARY_MAX:
        raise ValueError(f"`## Summary` has {len(items)} bullets; it needs {SUMMARY_MIN} to {SUMMARY_MAX}")
    return items


def _keys(header: dict[str, str], required: dict[str, tuple[str, ...] | None], optional: tuple[str, ...] = ()):
    """Check header keys: each required key present (and in its allowed values), nothing unexpected."""
    for key, allowed in required.items():
        if key not in header:
            raise ValueError(f"missing header {key}")
        if allowed is not None and header[key] not in allowed:
            raise ValueError(f"{key}: {header[key]!r} isn't one of {', '.join(allowed)}")
    extra = sorted(set(header) - set(required) - set(optional))
    if extra:
        raise ValueError(f"unexpected header {extra[0]}")


def _intake(header: dict[str, str], text: str) -> None:
    decision = header.get("DECISION")
    if decision == "ACCEPT":
        _keys(header, {"DECISION": None, "RISK": RISKS, "SURFACES": None, "RESCOPED": ("yes", "no")})
        surfaces = header["SURFACES"]
        if surfaces != "none":
            names = [s.strip() for s in surfaces.split(",")]
            if not all(re.fullmatch(r"[a-z][a-z0-9-]*", s) for s in names) or len(set(names)) != len(names):
                raise ValueError(f"SURFACES: {surfaces!r} must be `none` or distinct lowercase names joined by commas")
    else:
        _keys(header, {"DECISION": ("ACCEPT", "NEEDS-INFO", "REJECT")})
        heading = "Questions" if decision == "NEEDS-INFO" else "Reason"
        if not section(text, heading):
            raise ValueError(f"DECISION: {decision} needs a non-empty `## {heading}`")


def _spec(_: dict[str, str], text: str) -> None:
    first = text.split("\n", 1)[0]
    if not first.startswith("# ") or not first[2:].strip():
        raise ValueError("the first line must be `# <title>`")
    for heading in SPEC_SECTIONS:
        if section(text, heading) is None:
            raise ValueError(f"missing `## {heading}`")
    criteria = section(text, "Acceptance criteria") or ""
    if not re.search(r"^\d+\. \S", criteria, re.M):
        raise ValueError("`## Acceptance criteria` needs at least one numbered criterion")


def _build(header: dict[str, str], text: str) -> None:
    _keys(header, {"STATUS": ("READY", "BLOCKED")})
    if header["STATUS"] == "BLOCKED" and not section(text, "Blocked"):
        raise ValueError("STATUS: BLOCKED needs a non-empty `## Blocked`")


def _review(header: dict[str, str], text: str) -> None:
    _keys(header, {"VERDICT": ("PASS", "CHANGES")})
    findings = section(text, "Findings")
    if findings is None:
        raise ValueError("missing `## Findings`")
    if header["VERDICT"] == "CHANGES" and findings.lower().rstrip(".") in ("", "none"):
        raise ValueError("VERDICT: CHANGES needs at least one finding")


def _decision(header: dict[str, str], text: str) -> None:
    _keys(header, {"DECISION": ("APPROVE", "ESCALATE")})
    if not section(text, "Why"):
        raise ValueError("missing a non-empty `## Why`")


def _checks(header: dict[str, str], _: str) -> None:
    _keys(header, {"GATE": ("PASS", "FAIL"), "COMMIT": None})
    if not SHA_RE.fullmatch(header["COMMIT"]):
        raise ValueError(f"COMMIT: {header['COMMIT']!r} isn't a full commit sha")


_RULES = {
    "intake": _intake,
    "spec": _spec,
    "build": _build,
    "review": _review,
    "decision": _decision,
    "checks": _checks,
}
