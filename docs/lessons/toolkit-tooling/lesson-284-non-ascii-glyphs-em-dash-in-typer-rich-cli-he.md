---
id: lesson-284-non-ascii-glyphs-em-dash-in-typer-rich-cli-he
type: lesson
status: active
created: "2026-06-22"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# Non-ASCII glyphs (-> em-dash) in Typer/Rich CLI help/log strings crash `--help` on the Windows cp1252 console

**Context:** TOOL-014 added the `infra k8s access {connect,disconnect,status}` sub-Typer, whose help text and INFO log lines originally used the Unicode arrow (U+2192) and em-dash (U+2014) for readability (e.g. `ts-bridge <arrow> 100.64.0.11:6443`).

**Problem:** On a Windows console using the legacy `cp1252` code page, Typer/Rich render `--help` (and emit log output) through a stream encoder that cannot represent those glyphs, raising `UnicodeEncodeError` and crashing the command before it does anything. It is not a font/display glitch — it is a hard exception at encode time. Same class as the SOPS-basename portability trap: a non-portable character silently embedded in a string that only fails on one OS.

**Solution:** Keep all CLI help text and log strings ASCII-only — use `->` for the arrow and `-` for the em-dash. Reserve non-ASCII for files that are always UTF-8 (vault markdown, this `docs/`), never for strings that pass through a Typer/Rich console renderer on Windows. A quick guard: grep new CLI/log strings for non-ASCII (`[^\x00-\x7F]`) before committing.

**Tags:** `#windows` `#cp1252` `#typer` `#rich` `#cli` `#unicode` `#tool-014` `#gotcha`
