---
id: lesson-746-bare-bash-on-windows-is-the-wsl-launcher
type: lesson
status: active
created: "2026-11-13"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, windows, testing]
---

# On Windows a bare `"bash"` argv starts the WSL launcher, even when Git Bash is on PATH

**Context**: The first full test run on `windows-latest` (#3409) failed 805 tests, and a read-only audit put about 585 of them down as Linux-only, because they ran shell scripts.

**Problem**: `subprocess.run(["bash", ...])` goes through `CreateProcess`, which searches `System32` before `PATH`. It therefore starts `C:\Windows\System32\bash.exe`, the WSL launcher. On a machine with no distro installed, that launcher prints a UTF-16 "no installed distributions" message and exits 1. `shutil.which("bash")` searches `PATH` only and returns Git Bash, so every `skipif(which("bash") is None)` guard let these tests run. Some tests that expected exit 1 passed for the wrong reason. A second mechanism was `Path.write_text` without `newline=`, which writes CRLF fixtures that the scripts under test then read. The toolkit had the same bug in the code that renders committed files.

**Solution**: Run 43556340653 resolved `bash` through `which` and made `write_text` default to LF, both in throwaway test-side shims. Failures went from 805 to 491, with 314 fixed and 0 new. In the toolkit (#3480), every `write_text` now passes `newline="\n"`, and `tests/test_toolkit_writes_lf.py` fails on any call that omits it. The controller-side headscale probe now opens its connection from Python, with no `timeout` and no `bash`.

**Rule**: On Windows, pass a shell to a subprocess by its full path, taken from `shutil.which`, never as a bare name. Pin `newline="\n"` on every text write whose bytes matter. Before marking a test platform-only, measure it with the suspected mechanism removed: a classification made by reading the code is a hypothesis.

**Tags**: `#windows` `#testing` `#issue-3409` `#issue-3480`
