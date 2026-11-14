"""Tests for the build-once sha resolver (DELIVERY-002 / ADR-056).

The resolver reads the staging-validated immutable ``sha-<short>`` pinned in
``values/staging.yaml`` so release.yml can re-tag that exact digest as the prod
semver — never a rebuild. Pure file read: no registry, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features import promotion

_VALUES_TEMPLATE = """\
apps:
  platform:
    api:
{api_version}
    web:
      version: sha-c8fa9a6
"""


def _write_values(root: Path, api_version: str) -> Path:
    values_dir = root / "infra" / "config" / "values"
    values_dir.mkdir(parents=True, exist_ok=True)
    path = values_dir / "staging.yaml"
    indented = f"      version: {api_version}" if api_version else "      domain: api.staging"
    path.write_text(_VALUES_TEMPLATE.format(api_version=indented), encoding="utf-8", newline="\n")
    return path


@pytest.fixture
def root_patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(promotion, "settings", type("S", (), {"project_root": tmp_path}))
    return tmp_path


class TestResolveImageSha:
    def test_returns_pinned_sha(self, root_patched, monkeypatch) -> None:
        _write_values(root_patched, "sha-abc1234")
        # No registry mock: a network call here would raise — proving the resolver is offline.
        assert promotion.resolve_image_sha("staging", "api") == "sha-abc1234"

    def test_reads_per_app_pin(self, root_patched) -> None:
        _write_values(root_patched, "sha-abc1234")
        assert promotion.resolve_image_sha("staging", "web") == "sha-c8fa9a6"

    def test_errors_on_missing_pin(self, root_patched) -> None:
        _write_values(root_patched, "")  # api has no version key -> not validated
        with pytest.raises(ValueError, match="No staging-pinned|sha-<short>"):
            promotion.resolve_image_sha("staging", "api")

    def test_errors_on_dev_pin(self, root_patched) -> None:
        _write_values(root_patched, "dev")
        with pytest.raises(ValueError, match="not an immutable sha"):
            promotion.resolve_image_sha("staging", "api")

    def test_errors_on_semver_pin(self, root_patched) -> None:
        _write_values(root_patched, "1.2.0")
        with pytest.raises(ValueError, match="not an immutable sha"):
            promotion.resolve_image_sha("staging", "api")

    def test_errors_on_non_platform_app(self, root_patched) -> None:
        _write_values(root_patched, "sha-abc1234")
        with pytest.raises(ValueError, match="not a platform app"):
            promotion.resolve_image_sha("staging", "errors")


class TestImageTagAllowUnpinned:
    """`--allow-unpinned`: an app with no pin yet is a first promotion, not an error (console, ADR-074).

    staging-deploy.yml reads the current pin to refuse a downgrade. An app deployed for the
    first time has none, so the read failed and the job with it. The flag answers an empty
    string for that one case only, and every other bad pin still fails.
    """

    @staticmethod
    def _run(*extra: str):
        from typer.testing import CliRunner

        from toolkit.cli import deployment

        return CliRunner().invoke(deployment.app, ["image-tag", "--env", "staging", "--app", "api", *extra])

    def test_an_unpinned_app_prints_nothing_and_succeeds(self, root_patched) -> None:
        _write_values(root_patched, "")
        result = self._run("--allow-unpinned")
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == ""

    def test_without_the_flag_an_unpinned_app_still_fails(self, root_patched) -> None:
        _write_values(root_patched, "")
        assert self._run().exit_code == 1

    def test_a_pinned_app_prints_its_pin_with_the_flag(self, root_patched) -> None:
        _write_values(root_patched, "sha-abc1234")
        result = self._run("--allow-unpinned")
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == "sha-abc1234"

    @pytest.mark.parametrize("pin", ["dev", "1.2.0"])
    def test_a_pin_that_is_not_a_sha_still_fails_with_the_flag(self, root_patched, pin: str) -> None:
        """Only an ABSENT pin is tolerated: a malformed one is a real fault the guard must not hide."""
        _write_values(root_patched, pin)
        assert self._run("--allow-unpinned").exit_code == 1
