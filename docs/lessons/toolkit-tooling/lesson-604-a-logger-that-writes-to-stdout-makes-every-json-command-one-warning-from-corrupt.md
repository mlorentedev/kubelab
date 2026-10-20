---
id: lesson-604-a-logger-that-writes-to-stdout-makes-every-json-command-one-warning-from-corrupt
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, logging, stdout, json, ci]
---

# A logger that writes to stdout makes every `--json` command one warning from corrupt

**Context**: `promote-prod.yml` pipes `toolkit product app-for-event --json` into `jq`
(#2526). The toolkit's `PlatformLogger` printed through a Rich `Console()`, which writes
to stdout.

**Problem**: On a hosted runner, which has no sops, building the settings logged
`[WARNING] SOPS is not installed` before the JSON object. `jq` failed on the `]` of
`[WARNING]` (`Invalid numeric literal at line 1, column 9`), and an empty lane read as
"not prod", so a web release would have ended green as a skip. Locally it passed,
because sops is on the Mac's PATH. #2526 fixed that one caller. The class remained: any
command whose path logs anything, on any host where something is missing.

**Solution**: #2536 splits the logger in two. Diagnostics (`info`, `warning`, `error`,
`section`, the `RichHandler`, progress) go through `err_console = Console(stderr=True)`.
`console` and `logger.console` stay on stdout for a command's data: tables, diffs, and
command output passed through. `tests/test_logger_streams.py` pins the contract once,
including a fresh interpreter without sops whose stdout must parse as JSON. The
content tests that read the logger now read both streams, so they do not depend on
which stream a line uses. The sops lookup moved from a `which` subprocess to
`shutil.which`.

**Rule**: Pin a stream contract at the logger, not per command, and test it in a
process missing what CI is missing. When you move output off stdout, audit the tests
that assert something is **absent** from stdout first. They stay green, and they stop
checking anything. `make mutate` against one of them is what proves the read still
covers the moved stream.

**Tags**: `#logging` `#stdout` `#pr-2526` `#issue-2536`
