"""An app's `version:` key sits with its siblings, not below the next section's comment.

`version` is the one key in this repository that decides which image production
serves. In `infra/config/values/prod.yaml` it had drifted to a position where it
reads as if it belonged to `services:`:

    web:
      ...
      enable_contact: false

  # Third-party services
      version: 1.12.0
  services:

That parses correctly — six-space indent keeps it inside `apps.platform.web`, and
a YAML comment does not break a mapping — which is exactly what makes it worth a
test rather than a shrug. **The file is wrong to a human and right to the
parser.** The failure mode is a reader dedenting `version` to match the comment
it appears to belong to, moving a production image tag out of the app block. The
prod overlay would then regenerate with no pin, and the drift gate would compare
a generated file against a source of truth that had silently lost a key.

`toolkit.features.promotion.promote` cannot fix this on its own and does not
cause it on any run you are likely to watch. It round-trips with ruamel, so an
*existing* key is rewritten in place. The misplacement is created once, on an
app's **first** promotion, when `app_cfg["version"] = version` appends a new key
to the end of the mapping — and ruamel holds `# Third-party services` as a
post-comment of the previous last key, so the new key lands after it. From then
on the round-trip preserves the wrong position faithfully and forever.

So this test guards two things at once: that the one-time repair stays repaired,
and that the next app to receive its first promotion does not reintroduce it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VALUES_DIR = REPO_ROOT / "infra" / "config" / "values"

# The environments whose values files pin a promoted image tag. `common.yaml` is
# excluded on purpose: its `version` keys belong to k3s, operators and the errors
# edge service, none of which go through `deployment promote`'s append path.
ENVIRONMENTS = ("staging.yaml", "prod.yaml")

_KEY = re.compile(r"^(\s*)([A-Za-z0-9_.-]+):")


def _key_lines(text: str) -> list[tuple[int, list[str], str]]:
    """Yield `(line_number, dotted_path, raw_line)` for every mapping key.

    Indentation alone determines nesting here, which is sound because these files
    are generated-adjacent and never use flow mappings for the app blocks.
    """
    found: list[tuple[int, list[str], str]] = []
    stack: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = _KEY.match(line)
        if match is None:
            continue
        indent, key = len(match.group(1)), match.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        found.append((number, [k for _, k in stack], line))
    return found


def _platform_version_keys(text: str) -> list[tuple[int, str]]:
    """Every `apps.platform.<app>.version` key, as `(line_number, app)`."""
    return [
        (number, path[2])
        for number, path, _ in _key_lines(text)
        if len(path) == 4 and path[0] == "apps" and path[1] == "platform" and path[3] == "version"
    ]


@pytest.mark.parametrize("filename", ENVIRONMENTS)
def test_every_platform_app_pins_a_version(filename: str) -> None:
    """The premise of the placement test: there is something to place."""
    text = (VALUES_DIR / filename).read_text()
    apps = [app for _, app in _platform_version_keys(text)]
    assert apps, f"{filename} pins no apps.platform.<app>.version at all"
    assert len(apps) == len(set(apps)), f"{filename} pins a version twice for {apps}"


def _stranded_version_keys(label: str, text: str) -> list[str]:
    """Every `apps.platform.<app>.version` that something separates from its block.

    The rule this applies is stated in full on
    `test_version_key_is_adjacent_to_its_siblings`, and exercised directly on
    synthetic input by `TestPlacementRule` — so the rule is guarded even when the
    committed files happen to satisfy it, which they now do.
    """
    lines = text.splitlines()
    offenders = []

    for number, app in _platform_version_keys(text):
        indent = len(lines[number - 1]) - len(lines[number - 1].lstrip())
        previous = lines[number - 2] if number >= 2 else ""
        stripped = previous.strip()
        previous_indent = len(previous) - len(previous.lstrip())

        if not stripped:
            adjacent = False
        elif stripped.startswith("#"):
            # A comment indented into the block is about this app; one outdented
            # below it belongs to an enclosing section and strands the key.
            adjacent = previous_indent >= indent
        else:
            match = _KEY.match(previous)
            # A sibling key, or the app key that opens this block.
            adjacent = match is not None and (
                previous_indent == indent or (match.group(2) == app and previous_indent < indent)
            )

        if not adjacent:
            reason = "a blank line" if not stripped else f"{stripped!r} (outdented to {previous_indent})"
            offenders.append(f"  {label}:{number} apps.platform.{app}.version — preceded by {reason}")
    return offenders


_BLOCK = (
    "apps:\n"
    "  platform:\n"
    "    web:\n"
    "{body}"
    "\n"
    "  # Third-party services\n"
    "  services:\n"
    "    core: {{}}\n"
)


class TestPlacementRule:
    """The rule itself, on synthetic input — independent of what is committed."""

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("after a sibling key", "      domain: example.com\n      version: 1.0.0\n"),
            ("first in the block", "      version: 1.0.0\n      domain: example.com\n"),
            (
                "after a comment indented into the block",
                "      # this app is pinned deliberately\n      version: 1.0.0\n      domain: example.com\n",
            ),
        ],
    )
    def test_accepts(self, label: str, body: str) -> None:
        assert not _stranded_version_keys(label, _BLOCK.format(body=body)), label

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("stranded by a blank line", "      domain: example.com\n\n      version: 1.0.0\n"),
            (
                "stranded under an outdented comment",
                "      domain: example.com\n  # Third-party services\n      version: 1.0.0\n",
            ),
        ],
    )
    def test_rejects(self, label: str, body: str) -> None:
        assert _stranded_version_keys(label, _BLOCK.format(body=body)), label


@pytest.mark.parametrize("filename", ENVIRONMENTS)
def test_version_key_is_adjacent_to_its_siblings(filename: str) -> None:
    """Nothing separates `version:` from the block it belongs to.

    Three placements satisfy that, and the test accepts all three because all
    three are unambiguous to a reader:

    - preceded by a **sibling key** at the same indent — where the existing pins
      sit, and where ruamel's in-place rewrite keeps them;
    - preceded by the **app's own key** one level out, i.e. first in the block —
      where `promote` now inserts a new pin, that being the one position which
      cannot collide with a comment trailing the block;
    - preceded by a **comment indented into the block**, which is a comment about
      this app. ruamel keeps such a comment above an `insert(0, ...)` rather than
      being displaced by it — measured, not assumed.

    What it rejects is a blank line, or a comment **outdented below the block's
    own indentation**, which by that outdent belongs to an enclosing section.
    Indentation is the whole signal: `# Third-party services` sits at two spaces
    while the key it stranded sits at six, and that gap is precisely what made the
    file read wrong. A rule phrased as "no comment at all" would fail a legitimate
    per-app note; a rule phrased as "previous *non-blank* line" would accept the
    stranded form that `prod.yaml`'s api entry had. This is the rule between them.
    """
    offenders = _stranded_version_keys(filename, (VALUES_DIR / filename).read_text())

    assert not offenders, (
        "A version key is separated from the block it belongs to:\n"
        + "\n".join(offenders)
        + "\n\nMove it up beside its sibling keys. A reader who trusts the layout "
        "will re-indent it into the wrong mapping and unpin a deployed image."
    )
