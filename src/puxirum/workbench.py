"""The tuios workbench: one workspace, three panes, all opened and kept by the core.

    ┌──────────────────┬──────────────────┐
    │                  │      Painel      │
    │     Puxirum      │       (TML)      │
    │ (this run's log) ├──────────────────┤
    │                  │     Agentes      │
    │                  │ (puxirum feed)   │
    └──────────────────┴──────────────────┘

`puxirum run`, started in a tuios pane, is the left pane. `open` names its
workspace, shows the dashboard to its right and splits the dashboard to start the
feed below it. While the run works, `refresh` patches the dashboard's state (only
what changed is drawn again), keeps a short note on each pane and puts a job that
starts waiting for a person in their Inbox, once.

Everything here is a mirror of the job files. The ids of the panes are kept in
`state/workbench.json` so the next run reuses them; a pane the person closed is
opened again. A tuios call that fails is logged and never stops the run.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from puxirum import report
from puxirum.config import Config
from puxirum.machine import ACTIVE
from puxirum.store import Job, Store, write_atomic
from puxirum.tuios import Tuios, TuiosError

WORKSPACE_NAME = "puxirum"
STAGE_NAMES = {
    "intake": "intake",
    "needs-info": "aguarda autor",
    "spec": "spec",
    "build": "build",
    "gate": "gate",
    "review": "revisão",
    "approve": "aprovação",
    "merging": "merge",
    "needs-human": "aguarda você",
    "merged": "mesclado",
    "rejected": "rejeitado",
}
ALERT_STAGES = ("needs-human", "needs-info")
MAX_JOBS = 50


def money(usd: float) -> str:
    return f"US$ {usd:.2f}"


def snapshot(store: Store, cfg: Config) -> dict[str, Any]:
    """The dashboard's state, from the job files alone."""
    jobs = store.all()
    reports = {j.id: report.job_report(store, j) for j in jobs}
    order = sorted(jobs, key=lambda j: (j.stage not in ACTIVE, j.stage in ("merged", "rejected"), -j.issue))
    rows, attention = [], []
    roles: dict[str, float] = {}
    for j in order:
        r = reports[j.id]
        for role, cost in r.by_role.items():
            roles[role] = roles.get(role, 0.0) + cost
        rows.append(
            {
                "job": f"#{j.issue} {j.title}"[:40],
                "stage": STAGE_NAMES.get(j.stage, j.stage),
                "round": str(j.round) if j.round else "-",
                "cost": money(r.cost_usd),
                "time": report.duration(r.total_seconds),
                "pr": f"#{j.pr}" if j.pr else "-",
            }
        )
        if j.stage in ALERT_STAGES:
            attention.append({"job": f"#{j.issue} {j.title}"[:40], "why": _why(j)})
    total = sum(r.cost_usd for r in reports.values())
    return {
        "active": sum(1 for j in jobs if j.stage in ACTIVE),
        "waiting": len(attention),
        "merged": sum(1 for j in jobs if j.stage == "merged"),
        "cost": money(total),
        "jobs": rows[:MAX_JOBS],
        "roles": [{"k": k, "v": round(v * 100)} for k, v in sorted(roles.items(), key=lambda x: -x[1])],
        "attention": attention,
        "empty": not jobs,
    }


def _why(job: Job) -> str:
    if job.stage == "needs-info":
        return "o intake fez perguntas na issue"
    reason = job.escalations[-1]["reason"] if job.escalations else job.last_error or "escalado"
    return " ".join(str(reason).split())[:120]


EMPTY: dict[str, Any] = {
    "active": 0,
    "waiting": 0,
    "merged": 0,
    "cost": money(0),
    "jobs": [],
    "roles": [],
    "attention": [],
    "empty": True,
}


def dashboard() -> str:
    """The dashboard document. Every value is a binding: the data only ever arrives as a JSON patch,
    so nothing from an issue (a title with `<` in it) is ever parsed as TML."""
    return f"""<tml version="1" title="Puxirum - painel">
  <state>{json.dumps(EMPTY)}</state>
  <col pad="1" gap="1">
    <row gap="2">
      <stat label="Ativos" value="{{state.active}}" role="accent"/>
      <stat label="Aguardando" value="{{state.waiting}}" role="warning"/>
      <stat label="Mesclados" value="{{state.merged}}" role="success"/>
      <stat label="Agentes" value="{{state.cost}}"/>
      <stat label="Coordenação" value="US$ 0.00" role="success"/>
    </row>
    <tabs>
      <tab id="jobs" title="Jobs">
        <text role="dim" show="{{state.empty}}">Nenhum job ainda. Marque uma issue com a label da fila.</text>
        <table rows="state.jobs">
          <column field="job" title="Job"/>
          <column field="stage" title="Etapa"/>
          <column field="round" title="Rodada" align="right"/>
          <column field="cost" title="Custo" align="right"/>
          <column field="time" title="Tempo" align="right"/>
          <column field="pr" title="PR" align="right"/>
        </table>
      </tab>
      <tab id="cost" title="Custos">
        <bar data="state.roles" x="k" y="v" dir="h" title="Custo por papel (centavos de US$)" h="10"/>
      </tab>
      <tab id="attention" title="Atenção">
        <table rows="state.attention">
          <column field="job" title="Job"/>
          <column field="why" title="Motivo"/>
        </table>
      </tab>
    </tabs>
  </col>
</tml>
"""


def _ops(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"op": "replace", "path": f"/{k}", "value": v} for k, v in state.items()]


def feed_command(repo: Path) -> str:
    """The shell line that turns the new pane into the feed, run from the repo."""
    package_root = str(Path(__file__).resolve().parents[1])
    argv = ["env", f"PYTHONPATH={package_root}", sys.executable, "-m", "puxirum.cli", "feed"]
    return f"cd {shlex.quote(str(repo))} && exec {shlex.join(argv)}\n"


class Workbench:
    def __init__(self, tuios: Tuios, store: Store, cfg: Config, log: Callable[[str], None] | None = None):
        self.tuios, self.store, self.cfg = tuios, store, cfg
        self.log = log or (lambda msg: None)
        self.path = store.root / "workbench.json"
        self.ids: dict[str, Any] = self._load()
        self._last: dict[str, Any] | None = None

    # ---- layout ---------------------------------------------------------------------------------

    def open(self) -> None:
        t = self.tuios
        workspace = t.workspace_of(t.pane)
        t.name_workspace(workspace, WORKSPACE_NAME)
        others = [w for w in t.windows_on(workspace) if w not in (t.pane, self.ids.get("panel"), self.ids.get("feed"))]
        if others:
            self.log(f"workbench: {len(others)} other pane(s) share this workspace; the layout may differ")
        surface = self.ids.get("surface")
        if surface and t.surface_alive(surface):
            t.replace(surface, dashboard())
        else:
            surface, self.ids["panel"] = t.open_surface(dashboard(), workspace, "Painel")
            self.ids["surface"] = surface
            self.ids.pop("feed", None)  # the feed goes under the new dashboard
        state = snapshot(self.store, self.cfg)
        t.patch(surface, _ops(state))
        feed = self.ids.get("feed")
        if not feed or t.window(feed) is None:
            self.ids["feed"] = t.split(self.ids["panel"], "down", "Agentes")
            t.send_text(self.ids["feed"], feed_command(self.store.repo))
        self._last = state
        self._save()
        self._notes(state)

    # ---- updates --------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Bring the dashboard, the notes and the Inbox up to date. Never raises."""
        try:
            state = snapshot(self.store, self.cfg)
            self._alert()
            if state == self._last:
                return
            surface = self.ids.get("surface")
            if not surface or not self.tuios.surface_alive(surface):
                self.open()
                return
            self.tuios.patch(surface, _ops(state))
            self._last = state
            self._notes(state)
        except (TuiosError, OSError) as e:
            self.log(f"workbench: {e}")

    def _notes(self, state: dict[str, Any]) -> None:
        self.tuios.note(
            self.tuios.pane,
            f"puxirum · {state['active']} ativos · {state['waiting']} aguardando · agentes {state['cost']}",
        )

    def _alert(self) -> None:
        sent = set(self.ids.get("alerted", []))
        fresh = False
        for j in self.store.all():
            if j.stage not in ALERT_STAGES:
                continue
            key = f"{j.id}:{j.stage}:{j.stage_started}"
            if key in sent:
                continue
            what = "aguarda você" if j.stage == "needs-human" else "aguarda o autor"
            self.tuios.tell(f"Puxirum #{j.issue} {what}: {_why(j)}", ["ok"])
            sent.add(key)
            fresh = True
        if fresh:
            self.ids["alerted"] = sorted(sent)
            self._save()

    # ---- ids --------------------------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("session") != self.tuios.session:
            return {"alerted": data.get("alerted", [])} if isinstance(data, dict) else {}
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.path, json.dumps({**self.ids, "session": self.tuios.session}, indent=2) + "\n")
