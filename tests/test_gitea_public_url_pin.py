"""Gitea's public URL comes from ROOT_URL, and the way it is detected is pinned (OPS-038).

Gitea 1.26 changed the default of `[server] PUBLIC_URL_DETECTION` to `auto` and added `never`;
the release notes do not say what an existing install without the key gets. An upgrade must not
change how the forge builds its own URLs (OIDC redirects, clone URLs) as a side effect of a
version bump, so the key is set explicitly and changed on its own, later, if at all.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "infra/ansible/roles/beelink_services/templates/compose.yml.j2"


def test_the_public_url_detection_is_pinned_to_the_pre_1_26_behaviour() -> None:
    assert 'GITEA__server__PUBLIC_URL_DETECTION: "legacy"' in COMPOSE.read_text(encoding="utf-8")
