---
id: lesson-727-a-fork-per-file-is-invisible-on-linux-and-a-hung-commit-on-windows
type: lesson
status: active
created: "2026-11-09"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, windows, portability, pre-commit]
---

# A fork per file is invisible on Linux and a hung commit on Windows

**Context**: `scripts/check-lessons.sh` runs as a pre-commit hook with
`files: ^docs/lessons/` and `pass_filenames: false`, so it walks the whole tree
(723 lessons across 13 category directories) on any commit that touches a
lesson. It spawned a process per lesson file — twice, in two places that looked
unrelated.

**Problem**: Committing a lesson on the Windows seat produced a `pre-commit`
process with no output for minutes; `git commit` looked hung and there was
nothing to read. The script was correct, so nothing failed: on Linux each fork
costs microseconds and the hook is instant, which is why the defect had survived
in the tree and would never have shown on `ubuntu-latest`. Measured on the seat,
a process costs **~0.22 s whatever it is** (20 `bash` spawns = 4.45 s; 10 `sed`
spawns inside one `bash` = 2.33 s), so ~1 400 forks is a five-minute hook.

**Solution**: Strip the path with parameter expansion and test index membership
in the shell. Four things are not obvious:

- **The trace names one line; the class is the loop.** The first fix replaced
  `$(basename "$f")`, and the hook still hung: `grep -qxF -- "$name" <<< "$targets"`
  was a second fork per file, three lines below. Removing the fork the trace
  pointed at took the run from >180 s to still >120 s. When the defect is
  "an external command per item", audit **every** command inside the loop.
- **One fork per directory is still the wrong shape.** Replacing the per-file
  `grep` with a per-directory `comm` of two sorted lists cost 9 forks × 13
  directories ≈ 23 s — better, and still dominated by spawns rather than by work.
  The membership test belongs in the shell, where a directory costs zero.
- **In-shell membership must stay a literal whole-line match.** `[[ $haystack ==
  *$'\n'"$name"$'\n'* ]]` — `$'\n'` is an ANSI-C quoted character, not a glob,
  and `"$name"` **is quoted**, so `*`, `?`, `[` or `+` in a filename cannot change
  the match. Unquoted, the name becomes a pattern and a filename is interpreted as
  one; without the delimiters it degrades to a substring test.
- **Keep it out of a pipe.** `grep -q` exits at its first match and a writer still
  feeding a large index takes SIGPIPE, which `pipefail` reports as no match —
  that was `#2765`, and an in-shell test cannot reintroduce it.

The same seat hid a second, unrelated trap in the test that runs this script.
`subprocess.run(["bash", script])` resolved to `C:\Windows\System32\bash.exe`, the
**WSL launcher**, because `CreateProcess` searches `System32` before `PATH` — while
`where bash` and PowerShell both list Git's bash first, so the two disagree about
what `bash` means. The WSL launcher drops every argument after the command and
cannot open a `C:/` path, so it answered `127 /bin/bash: C:/…: No such file or
directory` for a file that existed. Resolve the interpreter with `shutil.which`
and pass the path `as_posix()`.

**Rule**: A hook that walks a tree must do a **constant** number of spawns per
directory, not per file — and CI cannot see the difference, because the platform
it runs on makes a fork free. When a script is slow only on one platform, count
processes before profiling anything else, and audit the whole loop rather than
the line the trace stopped on. Likewise, never trust a bare tool name in
`subprocess`: on Windows it can be a different implementation than the one your
shell resolves, and the wrong one fails with a message that describes a missing
file.

**Tags**: `#windows` `#portability` `#pre-commit` `#tooling` `#3206`
