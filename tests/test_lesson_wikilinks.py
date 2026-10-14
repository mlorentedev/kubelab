"""Every `[[lesson-...]]` link between lessons names a lesson that exists.

A lesson renamed after it was linked leaves the link pointing at a name no file
carries: lesson-425 linked lesson-416 by a slug lesson-416 lost, and only an
external formatter noticed. A bare `[[lesson-NNN]]` resolves by its number; a
link with a slug must match a file name exactly, whatever characters the slug
carries, so a stray capital or underscore is caught rather than skipped.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LESSONS = REPO_ROOT / "docs" / "lessons"

_LINK = re.compile(r"\[\[(lesson-(\d+)(?:-[^|\]]+)?)(?:\|[^\]]*)?\]\]")


def test_every_lesson_wikilink_resolves() -> None:
    files = {p.stem for p in LESSONS.rglob("lesson-*.md")}
    numbers = {stem.split("-")[1] for stem in files}
    assert len(files) > 500, "the lesson tree was not found"
    broken = []
    for path in sorted(LESSONS.rglob("*.md")):
        for match in _LINK.finditer(path.read_text(encoding="utf-8")):
            target, number = match.group(1), match.group(2)
            resolves = target in files if target != f"lesson-{number}" else number in numbers
            if not resolves:
                broken.append(f"{path.relative_to(LESSONS)} -> [[{target}]]")
    assert not broken, broken
