---
id: lesson-581-a-fetcher-that-lists-one-level-deep-reads-a-grouped-corpus-as-no-recurrence
type: lesson
status: active
created: "2026-10-16"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, curator, ai-012]
---

# A fetcher that lists one level deep reads a grouped corpus as "no recurrence"

**Context**: AI-012 part 6a ports hermes-nan's recurrence analyzer, which fetches each repository's `docs/lessons/` through the GitHub contents API.

**Problem**: kubelab keeps its lessons in category folders. The ported fetcher listed the directory one level deep, saw only subdirectories and `_index.md`, and took no lesson from the repository with the most of them. The run still ended `0`, wrote a candidates file, and read as a quiet week: a thin corpus and a corpus with no recurrence print the same output.

**Solution**: the analyzer downloads the repository tarball (one request, no API quota) and walks it, so depth does not matter. A repository that yields no lessons now fails the run with exit 3 and no candidates file, and the provision asserts the file reports a non-empty corpus. Measured on ace2: 1962 corpus files, 6536 units, 8 candidates.

**Rule**: a detector whose only output is "nothing found" needs a second output that says how much it looked at. Fail on an empty input, and report the input's size next to the verdict.

**Tags**: `#hermes` `#curator` `#ai-012`
