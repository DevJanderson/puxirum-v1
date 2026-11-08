Look at how the change looks, in a browser.

{{app_note}}

- Consistency: it uses the app's existing colours, type, spacing and components.
- Layout: nothing overflows, overlaps or jumps at 375px, 768px and 1280px wide, including with long text.
- Themes: it looks right in every theme the app supports, such as dark mode.
- Detail: alignment, spacing and states (hover, focus, disabled) match the elements around it.

Never review a user-facing change from the diff alone. Save a screenshot at each width you checked into `{{evidence_dir}}` with a name that starts with `ui-`, and refer to them in your review. A `PASS` without screenshots is not accepted.
