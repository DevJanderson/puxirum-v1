#!/usr/bin/env python3
"""Stands in for `claude -p` in tests: records what it got and answers per FAKE_CLAUDE_MODE."""

import json
import os
import subprocess
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_RECORD"], "w") as f:
    json.dump({"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd(), "prompt": prompt}, f)

if mode == "sleep":
    time.sleep(60)
if mode == "garbage":
    print("not json")
    sys.exit(0)
if mode == "fail":
    print(json.dumps({"type": "result", "is_error": True, "total_cost_usd": 0.2}))
    sys.exit(1)
if mode == "is_error":
    print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 0.1}))
    sys.exit(0)
if mode == "child":
    child = subprocess.Popen(["sleep", "60"])
    with open(os.environ["FAKE_CLAUDE_PID"], "w") as f:
        f.write(str(child.pid))
print(json.dumps({"type": "system", "subtype": "init", "cwd": os.getcwd()}))
tool_use = {"type": "tool_use", "name": "Read", "input": {"file_path": "spec.md"}}
print(json.dumps({"type": "assistant", "message": {"content": [tool_use]}}))
print(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "total_cost_usd": 0.123,
            "num_turns": 3,
            "result": "done",
        }
    )
)
