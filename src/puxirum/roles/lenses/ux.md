Use the change as a person would, in a browser.

{{app_note}}

- Flow: every path the spec promises works from start to end, with no dead ends.
- States: empty, loading and error states exist and say something useful.
- Words: labels and messages are short, plain and consistent with the rest of the app.
- Access: it works with the keyboard alone, focus is visible and in a sensible order, controls have labels.
- Small screens: it works at 375px wide.

Never review a user-facing change from the diff alone. Save at least one screenshot of what you checked, at 1280px and at 375px wide, into `{{evidence_dir}}` with a name that starts with `ux-`, and list them under `## Notes`. A `PASS` without screenshots is not accepted.
