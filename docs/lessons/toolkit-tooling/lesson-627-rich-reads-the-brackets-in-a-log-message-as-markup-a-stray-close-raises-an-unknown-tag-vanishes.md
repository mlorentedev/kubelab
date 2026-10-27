---
id: lesson-627-rich-reads-the-brackets-in-a-log-message-as-markup-a-stray-close-raises-an-unknown-tag-vanishes
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, logging, rich, markup, mutate]
---

# Rich reads the brackets in a log message as markup: a stray close raises, an unknown tag vanishes

**Context**: `PlatformLogger.info` and its siblings built the line as
`f"[blue][INFO][/blue] {message}"` and handed it to a rich `Console`. The message is
whatever the caller reports, and `toolkit tools mutate` relays pytest's output through
`logger.info(line)` one line at a time.

**Problem**: The message was parsed as markup, with two different outcomes (rich 15.0.0).
A closing tag that matches nothing raises: `logger.info("[/blue] x")` ends in
`MarkupError: closing tag '[/blue]' ... doesn't match any open tag`, and `[/]` in
`has nothing to close`. An opening or unknown tag does not raise, it disappears with its
text: `logger.info("t.py::test_x[param-1] FAILED")` prints `[INFO] t.py::test_x FAILED`,
and `[bold]x` prints `x` (the style is applied to nothing). So the common case, a
parametrize id, loses part of a test name with no error anywhere. The grammar is narrow,
which hides it: only `[` followed by `a-z`, `#`, `/` or `@` opens a tag. `[DRY-RUN]`,
`[INFO]` and `[100%]` print as written, and the eight `[DRY-RUN]` call sites in `toolkit/`
were never affected.

**Solution**: The logger escapes the message (`rich.markup.escape`) and keeps its label
as markup, so the level colour is unchanged. Three details of doing it right:

- `escape()` doubles a trailing backslash, so that it cannot escape a tag written right
  after the text. Where nothing follows (the end of the line), that second backslash
  prints: `x\` came out as `x\\`. A substring assertion passed on it. `_literal()` drops
  the extra one, and the test compares the whole line.
- Emoji codes are a smaller case of the same hazard: `a0:cd:11` printed a disc, because
  `:cd:` is a rich emoji name. The logger passes `emoji=False`.
- One caller wrote markup on purpose (`toolkit services list`, a cyan heading). A scan of
  every logger call in `toolkit/` found it alone, so the methods take an explicit
  `markup=True`. That shadows rich's own `markup=` print argument, which the methods used
  to forward and nothing used.

`tests/test_logger_escapes_markup.py` holds the hostile shapes (stray close, unknown tag,
`[#ff0000]`, backslashes, emoji codes) for every level and for `section` and `subsection`.

**Rule**: A formatter that puts a caller's value into a markup string escapes the value in
the formatter, not in each caller, and the fix is not finished until the test compares the
whole output: a substring check passes on the doubled backslash and on the dropped tag
alike. Look for the intentional markup users before changing the default, by scanning the
call sites rather than grepping the colour names.

**Tags**: `#logging` `#rich` `#markup` `#mutate`
