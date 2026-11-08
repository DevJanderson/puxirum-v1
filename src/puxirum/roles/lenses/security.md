Look at the change as someone who wants to misuse it would.

- Untrusted input: anything from users, URLs, storage or the network is validated or escaped before it reaches HTML, SQL, shell commands, file paths or `eval`.
- Secrets: no keys, tokens or passwords in code, logs, tests or fixtures.
- Access: no check is weakened, skipped or moved to a place a user controls.
- Dependencies: new packages are necessary, well known and pinned the way the project pins them.
- Data: nothing deletes, exposes or rewrites stored data without a clear reason in the spec.

A finding needs a concrete path to harm. Don't report what can't happen in this app.
