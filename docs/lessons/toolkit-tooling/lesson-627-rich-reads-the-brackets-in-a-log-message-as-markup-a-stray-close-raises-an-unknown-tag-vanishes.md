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

**Solution**: The logger no longer puts the message into a markup string at all. The label
is a `Text` the module builds (`Text("[INFO]", style="blue")`, which rich never parses), and
the message is passed to `Console.print` as its own argument with `markup=False`, so the
level colour is unchanged and the message is plain text. `section` and `subsection` print a
`Text` for the same reason. The first design escaped the message with `rich.markup.escape`
and was rejected in review, because escaping only protects what it recognises:

- `escape()` protects tag-shaped brackets only, and rich's renderer drops a backslash in
  front of ANY `[`. So `foo\[1\]` printed as `foo[1\]` and `bad escape \[` as `bad escape [`.
- `escape()` doubles a trailing backslash so that it cannot escape a tag written right after
  the text. Where nothing follows (the end of the line) that second backslash prints, so the
  first design needed a helper to trim it; where a tag does follow (`section`), an odd run of
  three or more is not doubled and eats the closing tag: a 60-character title ending in
  `\\\` printed `...\[/bold cyan]`. Every fix for one position broke another, which is the
  sign that the position is the wrong place to fix it.
- Emoji codes are the same hazard in a smaller size: `a0:cd:11` printed a disc, because
  `:cd:` is a rich emoji name. The logger passes `emoji=False`, and a `Text` has no emoji
  step at all.
- One caller wrote markup on purpose (`toolkit services list`, a cyan heading). A scan of
  every logger call in `toolkit/` found it alone, so the methods take an explicit
  `markup=True`. That shadows rich's own `markup=` print argument, which the methods used
  to forward and nothing used.

Passing the message as a separate `print` argument keeps rich's automatic highlighter on it
(numbers, paths and URLs are still coloured). The one visible difference in a terminal is
the label: its brackets were bolded by that highlighter, as a side effect of being part of
the same string, and are now the plain level colour.

`tests/test_logger_escapes_markup.py` holds the hostile shapes (stray close, unknown tag,
`[#ff0000]`, every backslash position including the unpadded and odd-run ones, emoji
codes) for every level, `section` and `subsection`, compares each whole line, and pins the
console width, so `COLUMNS=40` no longer wraps the lines it compares.

**Rule**: A formatter that puts a caller's value into a markup string cannot make it safe
by escaping it: the escape is correct only for the position it was written for. Give the
renderer the value as data (a `Text`, or its own `print` argument with `markup=False`)
instead, and keep markup for the strings the formatter itself wrote. Test by comparing the
whole output: a substring check passes on the doubled backslash and on the dropped tag
alike. Look for the intentional markup users before changing the default, by scanning the
call sites rather than grepping the colour names.

**Tags**: `#logging` `#rich` `#markup` `#mutate`
