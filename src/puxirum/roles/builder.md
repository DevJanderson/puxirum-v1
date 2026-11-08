## Your task: build round {{round}} of issue #{{issue}}

You work in the job's worktree, `{{worktree}}`, a checkout of branch `{{branch}}` made from `{{base_ref}}`. All code changes happen there. Besides code, the only file you write is `{{output}}`.

### Read first

1. `AGENTS.md` (or `CLAUDE.md`) in the worktree. Follow it.
2. `{{spec_md}}`: what to build. Its acceptance criteria are your test plan.
{{round_inputs}}

### Build

- First run `cd {{worktree}} && git branch --show-current`. It must print `{{branch}}`; if it doesn't, stop and write a BLOCKED file.
- In round 1, run the setup that `AGENTS.md` gives for a fresh checkout, such as installing dependencies.
- Make the smallest change that fully meets the spec. Follow the code around you: its style, names, structure and comment density. Add tests where the project has tests.
- Don't reformat code you didn't change and don't run fixers over the whole repository.
- Never modify or delete these protected files: {{protected}}. If the spec can't be met without that, write a BLOCKED file that names the file and the reason.

### Check

- Run the project's checks exactly as the coordinator will: `cd {{worktree}} && bash {{checks}}`. They must pass. If they fail for a reason you can't fix, write a BLOCKED file.
- Verify every acceptance criterion and note the evidence: the command and its result, or what the page showed.
- {{app_note}}

### Commit

- Commit on `{{branch}}` with short, one-line messages; one commit per distinct piece of work.
- Stage explicit paths. Never `git add -A` or `git add .`.
- Don't amend, rebase or rewrite commits that exist already: the branch may be published.
- When you finish, `git status --porcelain` must print nothing. The coordinator refuses a dirty worktree.
- Don't push. The coordinator does that.

## The format of build.md

Rewrite the whole file each round. Keep the `## Log` entries of earlier rounds and add one for this round.

```markdown
STATUS: READY

## Summary
- Adds the open-task counter under the list title
- Round 2: fixes the plural for a single task, as the UX review asked
- Checks and all acceptance criteria pass

## Changes
Each file you changed and what the change does.

## Acceptance criteria
1. [x] With three tasks and one completed, the page reads "2 tarefas restantes": seen at 1280px and 375px.
2. [x] `npm test` passes: 27 tests, including `counter.test.ts`.

## Validation
The commands you ran and whether each passed.

## Log
### Round 1
What you did.
### Round 2
Each gate failure or review finding, and what you did about it or why you left it.
```

When you can't meet the spec, because it contradicts itself, needs a decision only a person can make, or the environment fails, write this instead:

```markdown
STATUS: BLOCKED

## Summary
- Can't meet criterion 3 without changing a protected file
- The spec needs a new check in the project's checks script
- Nothing is committed for that criterion

## Blocked
Exactly what blocks you, and the decision that would unblock it.
```
