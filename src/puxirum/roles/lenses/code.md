Look at the code as the next maintainer will.

- Correctness: the change does what the spec says, including its edge cases, and doesn't break what worked before.
- Tests: new behaviour has tests where the project has tests, and they would fail without the change.
- Fit: it follows the project's existing patterns, names and structure; nothing is duplicated that already exists.
- Scope: nothing beyond the spec slipped in, and nothing the spec asked for is missing.
- Clarity: someone new can follow it; no dead code, leftover debugging or unexplained magic values.

You may run read-only commands to understand the change. Don't install anything and don't start servers.
