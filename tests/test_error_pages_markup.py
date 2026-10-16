"""The branded error pages are what a reader sees at the worst moment (#1753).

An audit found no `<h1>` on any status page (the code was a styled `<div>`) and
no robots directive on a page whose 503 body is served from other hosts' URLs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parent.parent / "edge" / "errors" / "html"
PAGES = sorted([*HTML.glob("errors/*.html"), HTML / "maintenance.html"])


def test_the_scan_finds_the_pages() -> None:
    assert len(PAGES) == 10, [p.name for p in PAGES]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_a_page_has_exactly_one_h1(page: Path) -> None:
    assert len(re.findall(r"<h1[\s>]", page.read_text(encoding="utf-8"))) == 1


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_a_page_asks_not_to_be_indexed(page: Path) -> None:
    assert '<meta name="robots" content="noindex">' in page.read_text(encoding="utf-8")


def test_the_orphaned_webp_stays_gone() -> None:
    """UX-7 named one file; it had already been removed when this guard was written."""
    assert not (HTML / "errors" / "404-southpark.webp").exists()


def test_no_asset_sits_in_the_errors_directory_unreferenced() -> None:
    """A tripwire for the next binary shipped in every image and read by nothing.

    On today's tree the candidate set is empty, so this proves nothing about UX-7
    itself; the test above does that.
    """
    pages = "\n".join(p.read_text(encoding="utf-8") for p in PAGES)
    # A real reference (src=/href=/url()), not a substring: "404" appears as text in the 404 page.
    referenced = {
        Path(m).name
        for m in re.findall(r"""(?:src|href)=["']([^"']+)["']|url\(["']?([^)"']+)""", pages)
        for m in m
        if m
    }
    orphans = [f.name for f in (HTML / "errors").iterdir() if f.suffix != ".html" and f.name not in referenced]
    assert not orphans, orphans
