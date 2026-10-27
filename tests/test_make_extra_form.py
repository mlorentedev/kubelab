"""No documented `EXTRA=` value starts with a flag.

`make provision` and `make reboot` pass EXTRA through as the value of
`--extra-vars`, so it takes `k=v` pairs and nothing else. A value written as
`EXTRA="-e k=v"` reaches Ansible as `--extra-vars '-e k=v'`, which argparse
refuses (`argument -e/--extra-vars: expected one argument`). The `rpi_boot` role
documented its reboot opt-in that way, so the command an operator would copy
from it failed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# EXTRA= followed by an optional quote and a dash: a flag where `k=v` belongs.
FLAG_FORM = re.compile(r"""\bEXTRA=["']?-""")


def _tracked_text_files() -> list[Path]:
    names = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [REPO / name for name in names.splitlines() if (REPO / name).is_file()]


def test_the_makefile_passes_extra_as_the_extra_vars_value() -> None:
    """The premise: if EXTRA ever became raw ansible arguments, `-e` would be right."""
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert '--extra-vars "$(EXTRA)"' in makefile


def test_no_documented_extra_value_starts_with_a_flag() -> None:
    offenders = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if FLAG_FORM.search(line) and path.resolve() != Path(__file__).resolve():
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not offenders, "EXTRA takes k=v pairs, not ansible flags:\n" + "\n".join(offenders)
