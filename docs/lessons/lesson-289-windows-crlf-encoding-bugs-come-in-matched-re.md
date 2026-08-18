---
id: lesson-289-windows-crlf-encoding-bugs-come-in-matched-re
type: lesson
status: active
created: "2026-07-08"
owner: manu
tags: [kubelab, lesson, windows, encoding, utf-8, cp1252, testing, tdd, tool-020, gotcha]
---

# Windows CRLF/encoding bugs come in matched read+write pairs, and pytest's own capture can hide the bug you're testing for (TOOL-020)

**Context:** Fixed `toolkit sync all --check` permanently failing on Windows (process-audit P1) — CRLF writer drift plus a homepage `charmap` crash. Two more instances of the same bug class only surfaced by running the full check end-to-end on a real Windows workstation, not from unit tests alone.

**Problem:** Two traps. (1) Every unguarded `open()`/`read_text()` in the sync scripts had a write-side counterpart already suspected, but the read side stayed invisible until non-ASCII content (em-dashes, middots) already committed to the repo got silently mis-decoded under a non-UTF-8 locale (cp1252) and re-encoded as mojibake on the next write — corruption, not a crash, so it never announces itself. (2) A test asserting `sys.stdout.encoding == "utf-8"` after importing the fixed module passed even with the fix commented out, because pytest's own capture stream is already UTF-8 regardless of host OS — the test proved nothing about the real Windows-console crash it was supposed to guard.

**Solution:** For the read side, add `encoding="utf-8"` to every `open(`/`read_text(` call in the same lane the writes were fixed in — the fix search doesn't stop at `write_text()`. For the test, manufacture a real `cp1252` `io.TextIOWrapper` via monkeypatch and prove it genuinely raises `UnicodeEncodeError` before asserting the fix neutralizes it.

**Rule:** When fixing a platform-encoding bug in a script, grep the whole module for `open(`/`read_text(`/`write_text(` — the fix is rarely one-sided. When a test claims to reproduce an environment-dependent crash, verify the harness reproduces it independent of the test runner's own defaults (pytest capture, CI locale) before trusting the green — a test that cannot fail without the fix teaches nothing.

**Tags:** `#windows` `#encoding` `#utf-8` `#cp1252` `#testing` `#tdd` `#tool-020` `#gotcha`
