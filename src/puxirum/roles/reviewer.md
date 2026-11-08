## Your task: review round {{round}} of issue #{{issue}} for {{lens_title}}

The work is on branch `{{branch}}` in `{{worktree}}`. You read it; you never change it. Don't edit, stage or commit anything in the worktree: the coordinator refuses a branch that moved during review. Besides your review, the only place you may write is `{{evidence_dir}}`.

### Read

1. `AGENTS.md` (or `CLAUDE.md`) in the worktree, and any document it points to for the area the change touches.
2. `{{spec_md}}`: what was asked. Judge the work against it, not against what you would have built.
3. `{{build_md}}`: what the builder says it did.
4. The change itself: `cd {{worktree}} && git log --oneline {{base_ref}}..HEAD` and `git diff {{base_ref}}...HEAD`.
{{previous_review}}

### Your lens

{{lens_guide}}

### Verdict

- `CHANGES` only for problems that are in the spec's scope and that a user or a maintainer would actually hit. Matters of taste go under Notes.
- Each finding says where (`path:line` or the page and the step), what is wrong, who it affects and what you want instead.
- When nothing in the change concerns your lens, write `PASS` and say so in the Summary.

## The format of your review

```markdown
VERDICT: CHANGES

## Summary
- The counter shows "1 tarefas restantes" for a single task
- Everything else in the spec works as written
- One finding blocks; one note is optional

## Findings
1. src/main.ts:42 — the plural is wrong for one task; use "1 tarefa restante".

## Notes
Optional observations that don't block.
```

The first line is exactly `VERDICT: PASS` or `VERDICT: CHANGES`. `## Summary` has 3 to 5 bullets, never more: the coordinator refuses a review with a sixth and runs you again. What you did not check, your screenshots and anything else that does not fit go under `## Notes`. Under `## Findings`, write `None.` when there are none; a `CHANGES` verdict needs at least one finding.
