# Puxirum

A deterministic software factory: GitHub issues in, merged pull requests out.

*Puxirum* is an Amazonian word of Tupi origin for collective work, where a community gathers so each person does a
part of the job until it is done.

## How it works

Label an issue `puxirum` and run `puxirum run`. A deterministic core, written in Python, takes the issue through a
fixed set of stages and runs a Claude Code agent for each one:

```
issue ─► intake ─► spec ─► builder ─► gate ─► reviewers ─► approver ─► merge
           │                  ▲          │         │
           ▼                  └──────────┴─────────┘
   questions to the author        another round, up to a limit,
                                  then a person decides
```

- **intake** reads the issue and accepts it, asks its author questions, or rejects it.
- **spec** writes what will be built and how it will be checked.
- **builder** implements it on its own branch, in its own git worktree.
- **gate** runs the project's `.puxirum/checks.sh` (install, lint, typecheck, test, build). It is a script, not an
  agent.
- **reviewers** look at the change through lenses chosen by its risk and surface: code, UX and UI on the running
  app, security.
- **approver** decides whether it merges.

The core is a state machine whose every step is recorded in files, so a run that stops resumes where it was. Agents
only read, edit and write their report: they hold no credentials, the builder's shell runs in Claude Code's OS
sandbox, and only the core pushes, opens pull requests and merges. When a job runs out of rounds or something
fails, it waits for a person instead of guessing.

The design, its decisions and the capability checklist are in [docs/design.md](docs/design.md) (in Portuguese).

## Requirements

- A GitHub repository, and the [GitHub CLI](https://cli.github.com) signed in
- [Claude Code](https://claude.com/claude-code)
- Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/) or pipx
- On Linux, `bubblewrap` and `socat`, for the builder's sandbox
- Optionally, [tuios](https://github.com/Gaurav-Gosain/tuios), for the workbench

## Install

In Claude Code, in the root of your project, say:

> Install Puxirum in this project: https://github.com/DevJanderson/puxirum/blob/main/INSTALL.md

The agent follows [INSTALL.md](INSTALL.md): it checks the prerequisites, installs the `puxirum` command, runs
`puxirum init`, writes `.puxirum/checks.sh` from the way your project already builds and tests itself, sets up the
config, runs `puxirum doctor`, and asks you before committing.

By hand, the short version:

```bash
uv tool install git+https://github.com/DevJanderson/puxirum
cd your-project
puxirum init      # config, checks template, /puxirum skill, labels, .gitignore
$EDITOR .puxirum/checks.sh
puxirum doctor
```

## Use

In Claude Code, the `/puxirum` skill is the conversational way in: ask how the queue is doing, what a reviewer said
about a job, to file an issue for the queue, or to run it. It looks things up and passes on your decisions; it never
does a job's work itself.

The commands:

| Command | Does |
|---|---|
| `puxirum run [N]` | Work the queue, or only issue N, until every job waits or finishes |
| `puxirum status` | Every issue in the queue and what its job is doing |
| `puxirum report` | Costs and times by job, role, model and run |
| `puxirum feedback N -m "..."` | Send a job that waits for you back to work, with your feedback |
| `puxirum reject N -m "..."` | Reject a job that waits for you or for its author |
| `puxirum workbench` | Open the tuios workbench without running |
| `puxirum feed` | Follow every running agent, one line per step |
| `puxirum panel` | Serve the read-only web panel |
| `puxirum init` | Install Puxirum in a repository; it never overwrites a file |
| `puxirum doctor` | Check everything a run needs |

### The workbench

Inside [tuios](https://github.com/Gaurav-Gosain/tuios), a run lays out its workspace beside the pane it was started
from:

```
┌──────────────────┬──────────────────┐
│                  │    Dashboard     │
│   Claude Code    │                  │
│  (you, /puxirum) ├─────────┬────────┤
│                  │ Run log │ Agents │
└──────────────────┴─────────┴────────┘
```

The dashboard shows the jobs, their stages and costs, and what waits for you; a job that starts waiting for you also
lands in the tuios Inbox. Outside tuios, Puxirum runs the same, without the workbench.

### The web panel

A read-only panel for the browser, in Vue 3 and shadcn-vue, served by `puxirum panel`. Its Início tab draws the line:
every stage, the ways back with how often jobs took them, the job you pick with its rounds and reviewers' verdicts,
what waits for you, and its files, with the running agents' steps live beside it. It reads the job files only, so
it runs in a container with your repositories mounted read-only:

```bash
docker compose -f panel/compose.yaml up -d --build    # http://localhost:4410, finds every repo under ~/Projects
```

Or without Docker, after building it once (`cd panel/web && npm ci && npm run build`):

```bash
puxirum panel --projects ~/Projects --web panel/web/dist
```

## Status

Version 1 is complete: one runner (Claude Code) and one workbench (tuios). In the pilot, a small Vite and TypeScript
to-do app with five issues, it merged four, and the fifth needed a person's decision. It spent US$ 3.48 on agents and
nothing on coordination, against US$ 8.53 for the LLM-orchestrated factory it was compared with.

## Development

```bash
python3 -m unittest discover -s tests -t .
ruff check src tests
ruff format --check src tests
mypy
```

To run your working copy as the `puxirum` command: `uv tool install -e .`

The panel's front end lives in `panel/web` (Vue 3, Vite, TypeScript, Tailwind v4, shadcn-vue). Run
`puxirum panel --projects ~/Projects` for the API and `npm run dev` there; Vite proxies `/api` to it.
`npm run build` typechecks and builds it.

## License

Copyright (C) 2026 Janderson Lira.

[GPLv3](LICENSE) (GPL-3.0-only). You can use, modify and share this code, and any version you distribute must also
be released under GPLv3.
