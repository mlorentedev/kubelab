---
id: "lesson-582-hermes-injects-a-jobs-script-output-into-its-prompt-so-a-record-parser-cannot-use-the-prompt-section"
type: lesson
status: active
title: "Hermes injects a job's script output into its prompt, so a record parser cannot use the Prompt section"
created: "2026-10-16"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, curator, ai-012]
---

# Hermes injects a job's script output into its prompt, so a record parser cannot use the Prompt section

**Context**: AI-012 part 6b: an agent job (the curator's judge) has a pre-run script that prints trimmed lesson excerpts, and a second job (the emitter) parses the judge's run record to turn its verdicts into drafts.

**Problem**: Hermes writes each run as `cron/output/<job id>/<time>.md` with the prompt, then the response. The prompt section contains the injected script output, and lesson excerpts hold `## ` lines. The emitter found the judge's run by searching the Prompt section for a phrase, and the section ended early at the first `## ` line of an excerpt, so the phrase was never seen: the live run ended `ok`, wrote nothing, and printed nothing, which is also what a quiet week looks like.

**Solution**: identify the run by the record's first line (`# Cron Job: <name>`), which no injected data can alter, and read the response as the record's last section. Take the evidence from the analyzer's own file by id, not from the record.

**Rule**: when a tool puts data it was handed into a document you parse, the document's structure is not yours to trust: key on the parts the tool writes itself (title, run time), never on a section the data can end. And a job that is silent by design needs a proof that makes it speak once (the live run that wrote four drafts), or the first week of silence proves nothing.

**Tags**: `#hermes` `#curator` `#ai-012`
