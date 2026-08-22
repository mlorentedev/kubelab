"""Renovate tracks every image in the SSOT, or says why not — #974.

Dependabot parses Dockerfiles, not arbitrary YAML, so the service image tags
pinned in `common.yaml` were bumped entirely by hand. Renovate's regex manager
can read them.

**The failure mode of a regex manager is silence.** A pattern that matches
nothing does not error — Renovate reports zero dependencies and everyone
assumes the images are current. So the coverage is asserted here rather than
trusted, and the check is exhaustive in both directions: nothing may be
untracked, and nothing may be ignored without appearing in `ignoreDeps` where a
reader can see the decision.

Found by writing it: the first pattern required a `/`, so the three official
Docker Hub images (postgres, redis, traefik) matched nothing at all and would
have gone untracked with no signal.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RENOVATE = REPO / "renovate.json"
COMMON = REPO / "infra/config/values/common.yaml"


def _config() -> dict:
    return json.loads(RENOVATE.read_text(encoding="utf-8"))


def _python_pattern() -> re.Pattern[str]:
    """Renovate uses RE2's `(?<name>)`; Python needs `(?P<name>)`.

    Converted for the test only — the file keeps the syntax Renovate parses.
    Rewriting the file to suit the test would be the test dictating the
    production artifact.
    """
    raw = _config()["customManagers"][0]["matchStrings"][0]
    return re.compile(re.sub(r"\(\?<([a-zA-Z]\w*)>", r"(?P<\1>", raw), re.M)


def _declared_images() -> list[str]:
    """Every `*image:` value in the SSOT, whatever its nesting."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("image") and isinstance(value, str) and value:
                    found.append(value)
                walk(value)

    walk(yaml.safe_load(COMMON.read_text(encoding="utf-8")))
    return found


def test_the_pattern_matches_something_at_all() -> None:
    """The vacuity check, and it is not theoretical for a regex manager.

    A pattern that matches nothing is Renovate's quietest possible failure: no
    error, no PRs, and a dependency dashboard that looks like everything is up
    to date.
    """
    matches = list(_python_pattern().finditer(COMMON.read_text(encoding="utf-8")))
    assert len(matches) > 10, (
        f"the image pattern matched {len(matches)} lines in common.yaml. A regex "
        f"manager that matches nothing reports nothing and looks healthy."
    )


def test_every_image_is_either_tracked_or_explicitly_ignored() -> None:
    """No image may fall through the gap between the two.

    Untracked-and-unlisted is the state that looks identical to covered.
    """
    config = _config()
    tracked = {m.group("depName") for m in _python_pattern().finditer(COMMON.read_text())}
    ignored = set(config["ignoreDeps"])

    unaccounted = sorted(
        image
        for image in _declared_images()
        if image.split(":")[0] not in tracked and image.split(":")[0] not in ignored
    )
    assert not unaccounted, (
        f"these images are in the SSOT, matched by no pattern, and named in no "
        f"ignore list: {unaccounted}. They would be silently unmaintained — the "
        f"exact state #974 exists to end."
    )


def test_the_ignore_list_names_only_images_that_exist() -> None:
    """A stale ignore entry exempts nothing and hides nothing.

    It reads as a considered decision about a real image, and it is a leftover.
    """
    names = {image.split(":")[0] for image in _declared_images()}
    stale = sorted(set(_config()["ignoreDeps"]) - names)
    assert not stale, (
        f"ignoreDeps names images that are not in common.yaml: {stale}. Either the "
        f"image was removed and this entry outlived it, or the name is wrong and "
        f"the real image is being tracked when someone believed it was not."
    )


def test_the_unversionable_images_are_the_ignored_ones() -> None:
    """The ignore list is a statement about tag SHAPE, not preference.

    Each of these cannot be compared by a version scheme: two carry `latest`,
    one carries no tag at all, one is a distro codename that rolls in place,
    and MinIO uses `RELEASE.2025-09-07T16-13-09Z`, which is a timestamp rather
    than a version. Renovate would either guess wrong or do nothing.

    Pinned so that giving one of them a real tag forces a decision here instead
    of leaving it ignored out of habit.
    """
    ignored = set(_config()["ignoreDeps"])
    by_name = {i.split(":")[0]: i for i in _declared_images()}
    for name in ignored:
        image = by_name[name]
        tag = image.split(":")[-1] if ":" in image.split("/")[-1] else ""
        unversionable = (
            tag in ("", "latest")
            or tag.startswith("RELEASE")
            or not any(ch.isdigit() for ch in tag)
        )
        assert unversionable, (
            f"{image} is ignored but carries a comparable tag ({tag!r}). If it can be "
            f"versioned it should be tracked; leaving it here makes the ignore list "
            f"look like a policy when it is an omission."
        )


def test_the_dangerous_images_have_a_rule_of_their_own() -> None:
    """Three cannot be treated as one more bump, each for a different reason.

    headscale — its clients are the Tailscale daemons on 8 nodes, pinned
    separately and not tracked here, and it is the bootstrap dependency for the
    mesh used to reach the host that would fix it.
    postgres  — a major is a dump and restore, not an upgrade.
    authelia  — it guards everything behind ForwardAuth, Argo CD included.
    """
    rules = _config()["packageRules"]
    covered = {name for rule in rules for name in rule.get("matchPackageNames", [])}
    for image in ("headscale/headscale", "postgres", "authelia/authelia"):
        assert image in covered, (
            f"{image} has no rule of its own, so it would be grouped into the weekly "
            f"minor+patch PR and merged with everything else"
        )


def test_grouped_updates_never_include_a_major() -> None:
    """A major buried in a group of patches is a major that merges unread.

    The review question for a major is different in kind, and this repo forbids
    auto-merge precisely so that question gets asked.
    """
    for rule in _config()["packageRules"]:
        if rule.get("groupName") and rule.get("matchUpdateTypes"):
            assert "major" not in rule["matchUpdateTypes"], (
                f"rule {rule.get('groupName')!r} groups major updates with others"
            )
