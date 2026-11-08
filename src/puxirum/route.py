"""Which reviewers look at a job, and with which model.

The risk table gives the base set; each surface adds its reviewers on top. A
later entry for the same reviewer wins, so a surface can raise a model.
"""

from __future__ import annotations

from puxirum.config import Config


class RouteError(Exception):
    pass


def reviewers(cfg: Config, risk: str, surfaces: list[str]) -> dict[str, str]:
    if risk not in cfg.risk_reviewers:
        raise RouteError(f"risk {risk!r} isn't routed; known: {', '.join(cfg.risk_reviewers)}")
    out = dict(cfg.risk_reviewers[risk])
    for surface in surfaces:
        extra = cfg.surface_reviewers.get(surface)
        if extra is None:
            known = ", ".join(cfg.surface_reviewers) or "none"
            raise RouteError(f"surface {surface!r} isn't routed; known: {known}")
        out.update(extra)
    if not out:
        raise RouteError(f"risk {risk!r} with surfaces {surfaces} routes to no reviewer")
    return out
