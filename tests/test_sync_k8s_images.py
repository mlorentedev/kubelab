"""Tests for sync_k8s_images — errors on the single-SSOT sync lane (DELIVERY-003).

`errors` is a semver-in-common.yaml image (one edge.errors.version, shared across
envs), so its K3s tag is derived by the same sync that handles third-party images
— not hand-edited and not the per-env promote lane. Pure config -> image-list
policy; no disk, no network.
"""

from __future__ import annotations

from toolkit.scripts import sync_k8s_images


def _config() -> dict:
    return {
        "registry": "docker.io/mlorentedev",
        "edge": {"errors": {"image_name": "kubelab-errors", "version": "1.2.3"}},
        "apps": {
            "services": {
                "core": {"gitea": {"image": "gitea/gitea:1.25.5"}},
            }
        },
    }


class TestResolveErrorsImage:
    def test_builds_image_from_structured_keys(self) -> None:
        # Same string Ansible renders for the VPS: {registry}/{image_name}:{version}.
        assert sync_k8s_images.resolve_errors_image(_config()) == (
            "docker.io/mlorentedev/kubelab-errors",
            "1.2.3",
        )

    def test_returns_none_when_edge_errors_absent(self) -> None:
        assert sync_k8s_images.resolve_errors_image({"registry": "docker.io/mlorentedev"}) is None

    def test_returns_none_without_version(self) -> None:
        cfg = {"registry": "docker.io/mlorentedev", "edge": {"errors": {"image_name": "kubelab-errors"}}}
        assert sync_k8s_images.resolve_errors_image(cfg) is None


class TestCollectImages:
    def test_includes_errors_alongside_third_party(self) -> None:
        images = sync_k8s_images.collect_images(_config())
        assert ("docker.io/mlorentedev/kubelab-errors", "1.2.3") in images
        assert ("gitea/gitea", "1.25.5") in images

    def test_errors_emitted_in_block(self) -> None:
        block = sync_k8s_images.build_images_block(sync_k8s_images.collect_images(_config()))
        assert "docker.io/mlorentedev/kubelab-errors" in block
        assert "newTag: 1.2.3" in block
