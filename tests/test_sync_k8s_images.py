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
                # A third-party image that is actually on the sync lane. It used
                # to be gitea, which stopped being one when ADR-061 moved that
                # workload off K3s to the Beelink — the assertion below then
                # failed for a correct reason, which is the point of pinning a
                # real IMAGE_SOURCES entry rather than an arbitrary string.
                "automation": {"n8n": {"image": "n8nio/n8n:1.100.0"}},
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
        assert ("n8nio/n8n", "1.100.0") in images

    def test_errors_emitted_in_block(self) -> None:
        block = sync_k8s_images.build_images_block(sync_k8s_images.collect_images(_config()))
        assert "docker.io/mlorentedev/kubelab-errors" in block
        assert "newTag: 1.2.3" in block


class TestProdOnlyImages:
    """TOOL-080: a manifest declared ONLY in overlays/prod/ needs its `images:`

    override in THAT kustomization, not base's. A transformer applies only to
    the resource set assembled at its own layer, so base's `images:` block
    never reaches a resource `pr-agent.yaml` adds directly in the prod overlay
    — adding the source path to `IMAGE_SOURCES` alone would resolve a `newTag`
    that touches nothing.
    """

    def _config(self) -> dict:
        return {
            "apps": {
                "services": {"automation": {"pr_agent": {"image": "pragent/pr-agent:0.45.0-gitea_app"}}},
            }
        }

    def test_pr_agent_is_a_prod_only_image_source(self) -> None:
        assert "apps.services.automation.pr_agent.image" in sync_k8s_images.PROD_IMAGE_SOURCES
        assert "apps.services.automation.pr_agent.image" not in sync_k8s_images.IMAGE_SOURCES

    def test_collect_images_resolves_from_a_custom_source_list(self) -> None:
        images = sync_k8s_images.collect_images(
            self._config(), sources=sync_k8s_images.PROD_IMAGE_SOURCES, include_errors=False
        )
        assert images == [("pragent/pr-agent", "0.45.0-gitea_app")]

    def test_sync_writes_the_prod_kustomization_from_the_prod_only_sources(self, tmp_path: Path) -> None:
        common_yaml = tmp_path / "common.yaml"
        common_yaml.write_text(yaml.safe_dump(self._config()), encoding="utf-8", newline="\n")
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n", encoding="utf-8", newline="\n"
        )

        rc = sync_k8s_images.sync(
            common_yaml=common_yaml,
            kustomization=kustomization,
            sources=sync_k8s_images.PROD_IMAGE_SOURCES,
            include_errors=False,
        )

        assert rc == 0
        result = kustomization.read_text(encoding="utf-8")
        assert "name: pragent/pr-agent" in result
        assert "newTag: 0.45.0-gitea_app" in result

    def test_main_writes_both_the_base_and_prod_kustomizations(self, tmp_path: Path, monkeypatch) -> None:
        base_kustomization = tmp_path / "base.yaml"
        prod_kustomization = tmp_path / "prod.yaml"
        base_kustomization.write_text("kind: Kustomization\n", encoding="utf-8")
        prod_kustomization.write_text("kind: Kustomization\n", encoding="utf-8")
        common_yaml = tmp_path / "common.yaml"
        common_yaml.write_text(
            yaml.safe_dump(
                {
                    "apps": {
                        "services": {
                            "automation": {
                                "n8n": {"image": "n8nio/n8n:1.0.0"},
                                "pr_agent": {"image": "pragent/pr-agent:0.45.0-gitea_app"},
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(sync_k8s_images, "COMMON_YAML", common_yaml)
        monkeypatch.setattr(sync_k8s_images, "KUSTOMIZATION", base_kustomization)
        monkeypatch.setattr(sync_k8s_images, "PROD_KUSTOMIZATION", prod_kustomization)

        assert sync_k8s_images.main() == 0
        assert "n8nio/n8n" in base_kustomization.read_text()
        assert "pragent/pr-agent" not in base_kustomization.read_text()
        assert "pragent/pr-agent" in prod_kustomization.read_text()
        assert "n8nio/n8n" not in prod_kustomization.read_text()


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
