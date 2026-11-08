"""A fake tuios daemon: just enough of the verbs the workbench uses, with their error codes."""

import copy
import itertools
import json

from puxirum.tuios import TuiosError


class FakeDaemon:
    def __init__(self, protocol=1, min_protocol=1):
        self.protocol, self.min_protocol = protocol, min_protocol
        self.windows = {}  # id -> {"workspace", "name", "typed": [...]}
        self.surfaces = {}  # id -> {"window", "doc", "state"}
        self.notes = {}
        self.workspace_names = {}
        self.asks = []
        self.calls = []
        self.fail = {}  # verb -> error code, raised on every call to that verb
        self._ids = itertools.count(1)

    def add_window(self, name, workspace=1):
        wid = f"w{next(self._ids):04d}-0000-0000-0000-000000000000"
        self.windows[wid] = {"workspace": workspace, "name": name, "typed": []}
        return wid

    def _window(self, verb, target):
        for wid, w in self.windows.items():
            if target == wid or wid.startswith(target) or target == w["name"]:
                return wid
        raise TuiosError(verb, "window_not_found", f"no window found matching {target!r}")

    def _surface(self, verb, sid):
        if sid not in self.surfaces or self.surfaces[sid]["window"] not in self.windows:
            raise TuiosError(verb, "surface_not_found", sid)
        return self.surfaces[sid]

    def __call__(self, verb, params):
        self.calls.append((verb, copy.deepcopy(params)))
        if verb in self.fail:
            raise TuiosError(verb, self.fail[verb])
        handler = getattr(self, "v_" + verb.replace("-", "_"), None)
        if handler is None:
            raise TuiosError(verb, "unknown_verb")
        return handler(verb, params)

    def v_hello(self, verb, p):
        return {"type": "hello", "protocol": self.protocol, "min_protocol": self.min_protocol}

    def v_get_window(self, verb, p):
        wid = self._window(verb, p["window"])
        return {"id": wid, "workspace": self.windows[wid]["workspace"], "title": self.windows[wid]["name"]}

    def v_list_windows(self, verb, p):
        # The real reply names the id `window_id` here, but `id` in get-window.
        return {"windows": [{"window_id": wid, "workspace": w["workspace"]} for wid, w in self.windows.items()]}

    def v_set_workspace_name(self, verb, p):
        self.workspace_names[p["workspace"]] = p["name"]
        return {}

    def v_split_window(self, verb, p):
        parent = self._window(verb, p["window"])
        wid = self.add_window(p["name"], self.windows[parent]["workspace"])
        self.windows[wid]["beside"] = (parent, p["side"])
        return {"window_id": wid}

    def v_send_text(self, verb, p):
        self.windows[self._window(verb, p["window"])]["typed"].append(p["text"])
        return {}

    def v_close_window(self, verb, p):
        del self.windows[self._window(verb, p["window"])]
        return {}

    def v_set_note(self, verb, p):
        self.notes[self._window(verb, p["window"])] = p["note"]
        return {}

    def v_tml_open(self, verb, p):
        wid = self.add_window(p["name"], p["workspace"])
        sid = f"tml-{next(self._ids):08x}"
        self.surfaces[sid] = {"window": wid, "doc": p["doc"], "state": _state_of(p["doc"])}
        return {"surface": sid, "window_id": wid, "workspace": p["workspace"]}

    def v_tml_get(self, verb, p):
        s = self._surface(verb, p["surface"])
        return {"state": s["state"], "window_id": s["window"]}

    def v_tml_patch(self, verb, p):
        s = self._surface(verb, p["surface"])
        for op in p["ops"]:
            assert op["op"] == "replace", op
            keys = op["path"].strip("/").split("/")
            node = s["state"]
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = op["value"]
        return {}

    def v_tml_replace(self, verb, p):
        s = self._surface(verb, p["surface"])
        s["doc"], s["state"] = p["doc"], _state_of(p["doc"])
        return {}

    def v_ask_human(self, verb, p):
        self.asks.append((p["question"], p["options"]))
        return {"status": "pending", "request_id": f"r{len(self.asks)}"}


def _state_of(doc):
    start = doc.find("<state>")
    if start < 0:
        return {}
    return json.loads(doc[start + len("<state>") : doc.index("</state>")])
