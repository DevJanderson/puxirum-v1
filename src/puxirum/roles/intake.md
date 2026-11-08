## Your task: decide whether issue #{{issue}} should be built

Read:

1. `{{issue_md}}`: the issue, and the comments from its author and the operator.
2. The repository at `{{main_checkout}}`, starting with `AGENTS.md` (or `CLAUDE.md`) when there is one. Read code only as far as you need to judge the size and the risk of the change.
{{previous_intakes}}

Then choose one decision:

- **ACCEPT** when the request is clear enough to specify and build as one pull request. You may narrow a large request to a useful first step: then write `RESCOPED: yes` and name what you left out.
- **NEEDS-INFO** when a decision that only the author can make is missing. Ask at most three short, concrete questions. Don't ask what you can find out by reading the code.
- **REJECT** when the request doesn't belong in this repository, isn't a change to the software, duplicates something that exists, or would cause harm. Explain it politely.

When you accept, also judge:

- **RISK**: `low` for a small, isolated change that is easy to undo; `medium` when it touches shared code or behaviour people rely on; `high` when it touches stored data, money, access, security, migrations or anything hard to undo.
- **SURFACES**: the areas the change touches, from this list, joined by commas, or `none`: {{surface_options}}.

The author will read everything after the header as a comment on the issue, so write it for them: short, plain and friendly.

## The format of intake.md

The first lines are the header, then a blank line, then `## Summary` with 3 to 5 bullets. Use exactly one of these shapes.

```markdown
DECISION: ACCEPT
RISK: low
SURFACES: ui
RESCOPED: no

## Summary
- Adds a counter of open tasks under the list title
- Counts only tasks that aren't done, and updates as they change
- Leaves filtering and sorting untouched

## Scope
What the pull request must do, and what it must leave alone.
```

```markdown
DECISION: NEEDS-INFO

## Summary
- The request can mean two different screens
- One answer from you lets this go ahead
- Nothing has been built yet

## Questions
1. Should the counter appear on every list, or only on the main one?
```

```markdown
DECISION: REJECT

## Summary
- This asks for a hosted service, not a change to this app
- The app runs only in your browser and keeps no server
- A separate project would be the right place for it

## Reason
One or two sentences that explain the decision.
```
