---
name: puxirum
description: Talk to this repository's Puxirum software factory - see the queue and costs, read what its agents decided, file an issue for it, start a run, send an escalated job back with feedback, or reject one. Use when the person types /puxirum or asks about the factory, its jobs, the issues in its queue, a run, or the workbench.
---

# Puxirum

Puxirum turns GitHub issues that carry its queue label into merged pull requests.
A deterministic core, the `puxirum` command, does all of the work: it starts the
agents (intake, spec, builder, reviewers, approver), runs the gate, pushes,
opens the pull request and merges it. You are the person's window into it: you
look things up, explain them, and pass on what the person decides.

Answer in the person's language.

## What you never do

The core owns every job. Doing a part of its work by hand leaves the job's
records saying one thing and the repository another. So:

- Don't edit, create or delete files under `.worktrees/` or `.puxirum/state/`.
- Don't commit to a job's branch, push, open, comment on, approve or merge a
  pull request, and don't add or remove a label on a queued issue.
- Don't run an agent yourself or start `claude -p`.

When something about a job should change, it goes through `puxirum feedback`,
`puxirum reject`, or a new issue. Changing `.puxirum/config.toml` or
`.puxirum/checks.sh` changes how every job is judged: do it only when the person
asks, and show them the diff first.

## Commands

| To | Run |
|---|---|
| See every issue in the queue and what its job is doing | `puxirum status` |
| Costs and times by job, role, model and run | `puxirum report` (`--json` for numbers) |
| Work the queue until every job waits or finishes | `puxirum run`, in the background (below) |
| Work one issue only | `puxirum run <issue>`, in the background |
| Open the workbench without running | `puxirum workbench` |
| Send a job that waits for you back to work | `puxirum feedback <job or issue> -m "<what to change>"` |
| Reject a job | `puxirum reject <job or issue> -m "<why>"` |
| Check that a run has what it needs | `puxirum doctor` |

The queue label is `[queue] label` in `.puxirum/config.toml`, `puxirum` when it is
not set.

## Starting a run

Start `puxirum run` with the Bash tool's `run_in_background`, so the conversation
stays free while agents work, and tell the person it started. Start one at a
time: if it answers that another `puxirum run` is working, one already is; say
so and don't retry. When you are told the background command finished, run
`puxirum status` and sum up what moved: what merged (with the PR), what waits
for whom, and what it cost.

Inside tuios the run opens the workbench in this workspace, beside this pane:
the dashboard, the core's log under it and every agent's steps beside the log.
Point the person there instead of copying its output into the conversation.

When this conversation ends, a run it started ends with it. Nothing is lost: the
next `puxirum run` stops anything the last one left running and picks every job
up where it was.

## Reading what happened

Each job is a folder, `.puxirum/state/jobs/<job id>/` (the id is the issue
number and a few words of its title, like `004-editar-o-titulo-de`):

| File | What it holds |
|---|---|
| `job.json` | stage, round, PR, escalations, the last error |
| `issue.md` | the issue as the core read it |
| `intake.md` | the intake's decision, and its questions for the author |
| `spec.md` | what will be built and how it will be checked |
| `build.md` | the builder's report on its latest round |
| `round-<n>/checks.md` | the gate's result for that round |
| `round-<n>/review-<lens>.md` | one reviewer's verdict and findings for that round |
| `round-<n>/evidence/` | screenshots and other proof the reviewers left |
| `decision.md` | the approver's decision |
| `escalation-<k>.md` | why the job stopped for a person |
| `events.jsonl` | every step the core took, one JSON object per line |
| `logs/` | each agent run's full transcript. Large: search it, don't read it whole |

When the person asks why something happened, read the files and quote the part
that answers, naming the file.

## Jobs that wait

- **Waits for the author** (`needs-info`): the intake asked questions on the
  issue. Only the issue's author can answer them there; the next run reads the
  answer. If the person is the author and wants help, draft the reply with them,
  and post it with `gh issue comment <issue> --body-file -` only once they have
  approved the exact text.
- **Waits for you** (`needs-human`): read `escalation-<k>.md` and the round that
  led to it, then explain the choice: send it back with `puxirum feedback`
  (the builder gets the feedback in its next round) or end it with
  `puxirum reject`. Both need the person's decision, in their words; never pick
  for them. Then start a run for it to move.

## Filing an issue for the queue

Help the person write it: what is wrong or missing, what they expect instead,
and how they will know it is done. Write the title and body down, show them,
and create the issue only once they agree:
`gh issue create --label <queue label> --title "<title>" --body-file -`.
The intake agent decides from that text alone whether the issue is clear enough
to build, so a vague issue comes back with questions.
