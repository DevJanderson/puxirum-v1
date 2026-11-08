"""Project configuration: `.puxirum/config.toml`.

Every key has a default, so an empty file is a valid configuration. Unknown keys
and wrong types are refused with the dotted path of the offending key, so a
typo never silently falls back to a default.
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(".puxirum") / "config.toml"

RISKS = ("low", "medium", "high")
REVIEWERS = ("code", "ux", "ui", "security")
ROLES = ("intake", "spec", "builder", "approver")
MERGE_METHODS = ("merge", "squash", "rebase")
PRICE_FIELDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


class ConfigError(Exception):
    """The configuration file is missing a required value or has a bad one."""


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


@dataclass(frozen=True)
class Config:
    queue_label: str = "puxirum"
    needs_info_label: str = "puxirum:needs-info"
    needs_human_label: str = "puxirum:needs-human"
    concurrency: int = 1
    max_rounds: int = 3
    agent_attempts: int = 2
    effect_attempts: int = 3
    base_branch: str = "main"
    merge_method: str = "squash"
    branch_prefix: str = "puxirum/"
    worktrees_dir: str = ".worktrees"
    checks: str = ".puxirum/checks.sh"
    gate_timeout_s: int = 1800
    protected: tuple[str, ...] = (".puxirum/checks.sh", ".puxirum/config.toml", ".puxirum/roles/*")
    ports_base: int = 5200
    ports_step: int = 10
    models: dict[str, str] = field(
        default_factory=lambda: {"intake": "sonnet", "spec": "sonnet", "builder": "sonnet", "approver": "sonnet"}
    )
    risk_reviewers: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "low": {"code": "haiku"},
            "medium": {"code": "sonnet"},
            "high": {"code": "sonnet"},
        }
    )
    surface_reviewers: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "ui": {"ux": "sonnet", "ui": "haiku"},
            "security": {"security": "opus"},
        }
    )
    prices: dict[str, Price] = field(default_factory=dict)

    def is_protected(self, path: str) -> bool:
        """True when a repo-relative path matches one of the protected patterns."""
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in self.protected)


# ---- Loading ----------------------------------------------------------------


def load(repo: Path) -> Config:
    """Read `<repo>/.puxirum/config.toml`. A missing file is an error: run `puxirum init`."""
    path = repo / CONFIG_PATH
    if not path.is_file():
        raise ConfigError(f"{CONFIG_PATH} not found in {repo}; run `puxirum init`")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{CONFIG_PATH}: {e}") from None
    return parse(data)


def parse(data: dict[str, Any]) -> Config:
    """Build a Config from parsed TOML, validating every key."""
    r = _Reader(data, "")
    queue = r.table("queue")
    git = r.table("git")
    gate = r.table("gate")
    ports = r.table("ports")
    routing = r.table("routing")
    d = Config()

    values: dict[str, Any] = {
        "queue_label": queue.string("label", d.queue_label),
        "needs_info_label": queue.string("needs_info_label", d.needs_info_label),
        "needs_human_label": queue.string("needs_human_label", d.needs_human_label),
        "concurrency": queue.integer("concurrency", d.concurrency, minimum=1),
        "max_rounds": queue.integer("max_rounds", d.max_rounds, minimum=1),
        "agent_attempts": queue.integer("agent_attempts", d.agent_attempts, minimum=1, maximum=10),
        "effect_attempts": queue.integer("effect_attempts", d.effect_attempts, minimum=1, maximum=20),
        "base_branch": git.string("base", d.base_branch),
        "merge_method": git.choice("merge_method", d.merge_method, MERGE_METHODS),
        "branch_prefix": git.string("branch_prefix", d.branch_prefix),
        "worktrees_dir": git.relpath("worktrees_dir", d.worktrees_dir),
        "checks": gate.relpath("checks", d.checks),
        "gate_timeout_s": gate.integer("timeout_s", d.gate_timeout_s, minimum=1),
        "protected": tuple(gate.strings("protected", list(d.protected))),
        "ports_base": ports.integer("base", d.ports_base, minimum=1024, maximum=65000),
        "ports_step": ports.integer("step", d.ports_step, minimum=1, maximum=1000),
        "models": r.table("models").string_map(d.models, allowed=ROLES, merge=True),
        "risk_reviewers": _reviewer_tables(routing.table("risk"), d.risk_reviewers, required=RISKS),
        "surface_reviewers": _reviewer_tables(routing.table("surfaces"), d.surface_reviewers, required=()),
        "prices": _prices(r.table("prices")),
    }
    for reader in (r, queue, git, gate, ports, routing):
        reader.refuse_unknown()

    labels = [values["queue_label"], values["needs_info_label"], values["needs_human_label"]]
    if len(set(labels)) != len(labels):
        raise ConfigError("queue: label, needs_info_label and needs_human_label must all differ")
    if not values["branch_prefix"].endswith("/"):
        raise ConfigError("git.branch_prefix: must end with '/'")
    return Config(**values)


def _reviewer_tables(r: _Reader, default: dict[str, dict[str, str]], required: tuple[str, ...]):
    if not r.data:
        return {k: dict(v) for k, v in default.items()}
    out = {}
    for name in r.data:
        out[name] = r.table(name).string_map({}, allowed=REVIEWERS, merge=False)
    missing = [k for k in required if k not in out]
    if missing:
        raise ConfigError(f"{r.path}: missing {', '.join(missing)}")
    return out


def _prices(r: _Reader) -> dict[str, Price]:
    out = {}
    for model in r.data:
        t = r.table(model)
        out[model] = Price(**{f: t.number(f) for f in PRICE_FIELDS})
        t.refuse_unknown()
    return out


class _Reader:
    """Typed access to one TOML table that remembers which keys were read."""

    def __init__(self, data: Any, path: str):
        if not isinstance(data, dict):
            raise ConfigError(f"{path}: must be a table")
        self.data = data
        self.path = path
        self.seen: set[str] = set()

    def _key(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def _get(self, key: str) -> Any:
        self.seen.add(key)
        return self.data.get(key)

    def table(self, key: str) -> _Reader:
        value = self._get(key)
        return _Reader({} if value is None else value, self._key(key))

    def string(self, key: str, default: str) -> str:
        value = self._get(key)
        if value is None:
            return default
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{self._key(key)}: must be a non-empty string")
        return value

    def relpath(self, key: str, default: str) -> str:
        value = self.string(key, default)
        p = Path(value)
        if p.is_absolute() or ".." in p.parts:
            raise ConfigError(f"{self._key(key)}: must be a path inside the repository")
        return value

    def choice(self, key: str, default: str, options: tuple[str, ...]) -> str:
        value = self.string(key, default)
        if value not in options:
            raise ConfigError(f"{self._key(key)}: must be one of {', '.join(options)}")
        return value

    def integer(self, key: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
        value = self._get(key)
        if value is None:
            return default
        # bool is a subclass of int; `concurrency = true` is a mistake, not 1.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{self._key(key)}: must be an integer")
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            raise ConfigError(f"{self._key(key)}: must be between {minimum} and {maximum}")
        return value

    def number(self, key: str) -> float:
        value = self._get(key)
        if value is None:
            raise ConfigError(f"{self._key(key)}: required")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ConfigError(f"{self._key(key)}: must be a non-negative number")
        return float(value)

    def strings(self, key: str, default: list[str]) -> list[str]:
        value = self._get(key)
        if value is None:
            return default
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise ConfigError(f"{self._key(key)}: must be a list of non-empty strings")
        return value

    def string_map(self, default: dict[str, str], allowed: tuple[str, ...], merge: bool) -> dict[str, str]:
        """This whole table as {name: non-empty string}, with names from `allowed`."""
        out = dict(default) if merge else {}
        for k, v in self.data.items():
            self.seen.add(k)
            if k not in allowed:
                raise ConfigError(f"{self._key(k)}: unknown name; expected one of {', '.join(allowed)}")
            if not isinstance(v, str) or not v.strip():
                raise ConfigError(f"{self._key(k)}: must be a non-empty string (a model)")
            out[k] = v
        return out

    def refuse_unknown(self) -> None:
        unknown = sorted(set(self.data) - self.seen)
        if unknown:
            raise ConfigError(f"unknown key {self._key(unknown[0])}")
