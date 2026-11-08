## Your task: write the specification for issue #{{issue}}

Read:

1. `{{issue_md}}`: what was asked.
2. `{{intake_md}}`: the intake decision. Its `## Scope` is binding: specify that, nothing more. Risk {{risk}}, surfaces: {{job_surfaces}}.
3. The code in the job's worktree, `{{worktree}}`, starting with `AGENTS.md` (or `CLAUDE.md`). Learn how the app is built today, so the spec fits it.

The builder implements exactly what you write and the reviewers judge the work against it. Make it precise enough that two people would build the same thing, but describe behaviour, not the implementation: no file-by-file plans.

Every acceptance criterion must be checkable by running a command or by looking at the app. "Works well" is not a criterion; "Typing a title longer than 200 characters keeps the layout inside the card" is.

{{edge_cases_rule}}

## The format of spec.md

```markdown
# Show how many tasks are left

## Summary
- A line under the title says how many tasks are still open
- It updates when a task is added, completed or removed
- No change to storage or to existing controls

## Context
What exists today that this change builds on, with file paths.

## Requirements
1. The behaviour, one requirement per item.

## Acceptance criteria
1. With three tasks and one completed, the page reads "2 tarefas restantes".
2. `npm test` passes, including a new test for the counter.

## Edge cases
- Zero tasks, one task, a very long title, keyboard only, a phone-width screen.

## Out of scope
What the builder must not do, even if it seems related.

## Assumptions
Decisions you made where the issue was silent, so reviewers can check them.
```

The first line is `# ` and the title, which becomes the pull request title. Keep the sections in this order. `## Edge cases` may say "None." when the change has no user-facing behaviour.
