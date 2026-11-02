"""The brand assets the platform serves (ADR-071, IDP-048).

`edge/errors/html/brand/` is what `assets.<env>.kubelab.live/brand/` serves, and
Authelia serves its own copy from a ConfigMap (it cannot fetch from the edge),
so the two have to stay the same bytes or the login portal and every other app
show different marks.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDGE = ROOT / "edge/errors/html/brand"
AUTHELIA = ROOT / "infra/k8s/base/services/authelia-assets"

SHARED = ["logo.svg", "favicon.svg", "logo.png", "favicon.ico"]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ICO_MAGIC = b"\x00\x00\x01\x00"


@pytest.mark.parametrize("name", SHARED)
def test_authelia_copy_is_the_edge_copy(name: str) -> None:
    assert (AUTHELIA / name).read_bytes() == (EDGE / name).read_bytes()


def test_favicon_ico_is_a_real_icon_with_several_sizes() -> None:
    """A PNG saved as `.ico` works in most browsers and fails in the rest."""
    data = (EDGE / "favicon.ico").read_bytes()
    assert data[:4] == ICO_MAGIC
    (count,) = struct.unpack_from("<H", data, 4)
    assert count >= 3


def test_logo_png_is_a_png_with_an_alpha_channel() -> None:
    """The apps put the logo on light and dark surfaces, so it cannot carry a background."""
    data = (EDGE / "logo.png").read_bytes()
    assert data[:8] == PNG_MAGIC
    colour_type = data[25]
    assert colour_type == 6  # RGBA
    assert struct.unpack(">II", data[16:24]) == (400, 400)  # apps scale it down, never up


@pytest.mark.parametrize("name", ["logo.svg", "mark.svg", "favicon.svg"])
def test_svg_marks_use_the_brand_primary_and_no_background(name: str) -> None:
    """The colour is the SSOT token, not a sampled one (ADR-071 D1)."""
    import yaml

    primary = yaml.safe_load((ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))["branding"][
        "palette"
    ]["primary"]
    svg = (EDGE / name).read_text(encoding="utf-8")
    assert primary.lower() in svg.lower()
    assert "<text" not in svg  # no font dependency: the mark is geometry only
    assert "<rect" not in svg  # a filled rectangle is how a background gets drawn
