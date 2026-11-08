# Installing Puxirum in a project

These steps are written for a coding agent (Claude Code) working in the root of
the project's git repository, with the person who owns it watching. A person
can follow them too.

The person starts it with one sentence, for example:

> Install Puxirum in this project: https://github.com/DevJanderson/puxirum/blob/main/INSTALL.md

Work through the steps in order. Tell the person what you found at each step.
Stop and ask them whenever a step says so, or when something does not fit what
is described here. Don't guess.

## 0. Check the prerequisites

Run each check. Collect everything that is missing, then tell the person all
of it at once, with how to install it on their system. Don't install system
packages yourself.

| Needs | Check | Why |
|---|---|---|
| a git repository with a GitHub `origin` | `git remote get-url origin` | issues and pull requests live there |
| GitHub CLI, signed in | `gh auth status` | the core reads issues and opens and merges pull requests with it |
| Claude Code | `claude --version` | every agent is a `claude -p` run |
| Python 3.11 or newer | `python3 --version` | Puxirum is Python, standard library only |
| uv (or pipx) | `uv --version` | to install the `puxirum` command |
| bubblewrap and socat (Linux) | `command -v bwrap socat` | the builder's shell runs in Claude Code's OS sandbox |
| tuios (optional) | `command -v tuios` | the workbench: dashboard, run log and live agents |

On Arch Linux the system packages are `pacman -S github-cli bubblewrap socat`;
on Debian and Ubuntu, `apt install gh bubblewrap socat`.

Also check that the working tree is clean (`git status --short` prints nothing)
and that it is on the base branch, usually `main`. If not, ask the person what
to do with their changes first.

## 1. Install the `puxirum` command

```bash
uv tool install git+https://github.com/DevJanderson/puxirum
puxirum --version
```

With pipx instead: `pipx install git+https://github.com/DevJanderson/puxirum`.
If `puxirum` is not found afterwards, the tool directory is not on `PATH`:
`uv tool update-shell` fixes that for new shells.

## 2. Run `puxirum init`

Tell the person first: it creates three labels on the GitHub repository.

```bash
puxirum init
```

It never overwrites a file. It creates `.puxirum/config.toml`,
`.puxirum/checks.sh` (a template that fails on purpose) and
`.claude/skills/puxirum/SKILL.md`; adds `.puxirum/state/` and `.worktrees/` to
`.gitignore`; lets the /puxirum skill run Puxirum's reading commands and
`puxirum run` without asking, in `.claude/settings.json`; and creates the queue
labels `puxirum`, `puxirum:needs-info` and `puxirum:needs-human`.

## 3. Fit it to the project

This is the step that needs judgement. Read how the project builds and tests
itself: its README, `AGENTS.md` or `CLAUDE.md`, CI workflows (`.github/workflows/`),
and its package manifest (`package.json` scripts, `pyproject.toml`, `Makefile`,
`Cargo.toml`, `go.mod`...).

### `.puxirum/checks.sh`: the gate

The gate runs this script in each job's worktree after every build and before
every merge. A job only merges when it exits 0, so it decides what "good"
means for this project. Replace the template's two last lines with the
project's own checks, in this order, keeping only the ones the project has:

1. install dependencies from the lockfile (`npm ci`, `uv sync --frozen`,
   `pip install -r requirements.txt`, `cargo fetch`...)
2. lint
3. typecheck
4. tests
5. build

Use the commands the project already uses, preferably the ones its CI runs.
Don't invent checks it does not have, and don't add tools. Then run it on the
base branch:

```bash
bash .puxirum/checks.sh
```

It must pass. If it fails on the untouched base branch, the project itself is
broken or the script is wrong: show the person the failure and stop. Don't
fix the project's code to make it pass.

### `.puxirum/config.toml`

Every key is optional and the comments show the defaults. Uncomment and set
only what differs:

- `[git] base` and `merge_method`: the default branch and a merge method the
  repository allows. Check with
  `gh repo view --json defaultBranchRef,mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed`.
- `[agents] network`: the hosts the builder's sandboxed shell may reach, which
  is none by default. A builder that installs packages needs its registry:
  `registry.npmjs.org` for npm, `pypi.org` and `files.pythonhosted.org` for pip
  and uv, `crates.io`, `index.crates.io` and `static.crates.io` for cargo,
  `proxy.golang.org` for Go.
- `[agents] sandbox_writes`: that package manager's cache, which the sandbox
  must be allowed to write: `~/.npm`, `~/.cache/pip`, `~/.cache/uv`,
  `~/.cargo/registry`, `~/go/pkg/mod`.
- `[app]`: only for a project with a dev server, such as a web app. `setup`
  installs dependencies and `command` starts the server; `{port}` is replaced
  by the job's port, and the server must fail rather than pick another port
  when that one is taken (for Vite, `--strictPort`). Both are lists of words,
  like `["npm", "run", "dev", "--", "--port", "{port}", "--strictPort"]`.
  The UX and UI reviewers look at the running app.

Leave the models, budgets and routing at their defaults unless the person asks.

### `AGENTS.md`

If the project has an `AGENTS.md` or `CLAUDE.md`, add a short section so that
other agents working in it know about the factory, in the file's own language
and style:

- issues labelled `puxirum` are worked by Puxirum, which opens and merges their
  pull requests itself;
- don't commit to or push branches starting with `puxirum/`, and don't edit
  `.worktrees/` or `.puxirum/state/`;
- `.puxirum/checks.sh` is the gate: every change must keep it passing;
- the /puxirum skill shows the queue and starts runs.

## 4. Verify

```bash
puxirum doctor
```

Every line must be `OK`, except that a `WARN` for tuios is fine when the person
does not use it, and `.puxirum/checks.sh is committed` stays a `WARN` until the
next step. Fix any `FAIL` before going on.

## 5. Commit

Show the person `git status` and `git diff`, and commit only once they agree:

```bash
git add .puxirum .claude .gitignore AGENTS.md   # the files that changed
git commit -m "Install Puxirum"
```

Push only when the person asks, but before the first run: each job's worktree
starts from the base branch on GitHub, and its agents read `AGENTS.md` there.

## 6. Tell the person how to use it

- Label an issue `puxirum` to put it in the queue, or ask the /puxirum skill to
  file one.
- Run the queue with `/puxirum roda a fila` (or any words to that effect), or
  `puxirum run` in a terminal. In tuios, the workbench opens beside the pane it
  was started from.
- `/puxirum` answers questions about the queue, the jobs, their costs and what
  each agent decided.
