"""Tests for sync_k8s_images — errors on the single-SSOT sync lane (DELIVERY-003).

`errors` is a semver-in-common.yaml image (one edge.errors.version, shared across
envs), so its K3s tag is derived by the same sync that handles third-party images
— not hand-edited and not the per-env promote lane. Pure config -> image-list
policy; no disk, no network.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from toolkit.cli.sync import _run_with_check
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


class TestWindowsSafeCheckIdempotency:
    """TOOL-020 regression: `sync --check` must not report drift from its own write.

    Reproduces the process-audit-2026-07-07.md P1 repro at the unit level: on
    Windows, `write_text()` with no `newline=` emits CRLF while the checked-out
    baseline is LF, so the byte-level comparator in `_run_with_check` reported
    false drift on every run — even immediately after a clean sync.
    """

    def test_check_reports_in_sync_after_its_own_write(self, tmp_path: Path) -> None:
        common_yaml = tmp_path / "common.yaml"
        common_yaml.write_text(
            yaml.safe_dump(_config()),
            encoding="utf-8",
            newline="\n",
        )

        # Baseline: what's already checked out from git — LF, per .gitattributes
        # (`*.yaml text eol=lf`). Built independently of `sync()` so this test
        # doesn't just compare the buggy write against itself.
        images = sync_k8s_images.collect_images(_config())
        images_block = sync_k8s_images.build_images_block(images)
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(
            f"apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n{images_block}",
            encoding="utf-8",
            newline="\n",
        )

        def _sync() -> int:
            return sync_k8s_images.sync(common_yaml=common_yaml, kustomization=kustomization)

        # The actual P1 repro: common.yaml hasn't changed, so re-running the
        # sync under --check against the LF baseline must report no drift —
        # not "a fresh write happens to match a fresh write" (which would be
        # true even with the CRLF bug, since both sides would be equally wrong).
        assert _run_with_check([kustomization], _sync, "images") is True

    def test_preserves_non_ascii_comments_on_reread(self, tmp_path: Path) -> None:
        # TOOL-020 (found during implementation, not in the original ticket):
        # `kustomization.read_text()` had no `encoding=`, so on a host whose
        # locale-preferred encoding isn't UTF-8 (this Windows box uses
        # cp1252), reading a UTF-8 file containing an em-dash in a comment
        # mis-decoded it — then re-writing re-encoded the already-mangled
        # text, permanently corrupting the file (mojibake, not a crash).
        common_yaml = tmp_path / "common.yaml"
        common_yaml.write_text(yaml.safe_dump(_config()), encoding="utf-8", newline="\n")

        # The em-dash sits in configMapGenerator, untouched by the images-block
        # regex substitution — round-tripping it verbatim is exactly what
        # read_text()/write_text_lf() must preserve.
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\n"
            "kind: Kustomization\n"
            "configMapGenerator:\n"
            "  # Homepage config — hash suffix triggers rolling update\n"
            "  - name: homepage-config\n"
            "images:\n",
            encoding="utf-8",
            newline="\n",
        )

        assert sync_k8s_images.sync(common_yaml=common_yaml, kustomization=kustomization) == 0

        result = kustomization.read_text(encoding="utf-8")
        assert "—" in result
        assert "â€" not in result  # mojibake signature for a mis-decoded em-dash
