"""Tests for toolkit sync CLI — drift detection (ADR-027)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from toolkit.cli.sync import _normalize_content, _restore_snapshots, _run_with_check
from toolkit.main import app

runner = CliRunner()


class TestSyncCLI:
    """Verify sync commands are registered and respond to --help."""

    def test_sync_help(self) -> None:
        result = runner.invoke(app, ["sync", "--help"])
        assert result.exit_code == 0
        assert "homepage" in result.output
        assert "images" in result.output
        assert "oidc" in result.output
        assert "all" in result.output

    @pytest.mark.parametrize("cmd", ["homepage", "images", "oidc", "all"])
    def test_subcommand_help(self, cmd: str) -> None:
        result = runner.invoke(app, ["sync", cmd, "--help"])
        assert result.exit_code == 0
        assert "--check" in result.output

    def test_oidc_requires_env(self) -> None:
        result = runner.invoke(app, ["sync", "oidc", "--help"])
        assert "--env" in result.output


class TestNormalizeContent:
    """Test dynamic value normalization for deterministic comparison."""

    def test_normalizes_date_and_hash(self) -> None:
        patterns = [(r"synced \d{4}-\d{2}-\d{2} \u00b7 [a-f0-9]{7,}", "synced DATE HASH")]
        content = "footer: synced 2026-03-27 \u00b7 abc1234".encode()
        result = _normalize_content(content, patterns)
        assert b"synced DATE HASH" in result

    def test_normalizes_today_field(self) -> None:
        patterns = [(r'"today": "\d{4}-\d{2}-\d{2}"', '"today": "DATE"')]
        content = b'"today": "2026-03-27"'
        result = _normalize_content(content, patterns)
        assert result == b'"today": "DATE"'

    def test_normalizes_ip(self) -> None:
        patterns = [(r'"traefik_cluster_ip": "\d+\.\d+\.\d+\.\d+"', '"traefik_cluster_ip": "IP"')]
        content = b'"traefik_cluster_ip": "10.43.0.100"'
        result = _normalize_content(content, patterns)
        assert result == b'"traefik_cluster_ip": "IP"'

    def test_no_patterns_returns_unchanged(self) -> None:
        content = b"unchanged content"
        assert _normalize_content(content, []) == content

    def test_no_match_returns_unchanged(self) -> None:
        patterns = [(r"will_not_match", "REPLACED")]
        content = b"unchanged content"
        assert _normalize_content(content, patterns) == content


class TestRestoreSnapshots:
    """Test snapshot restoration."""

    def test_restores_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        original = b"original content"
        f.write_bytes(original)
        f.write_bytes(b"modified")
        _restore_snapshots({f: original})
        assert f.read_bytes() == original

    def test_removes_file_if_snapshot_was_none(self, tmp_path: Path) -> None:
        f = tmp_path / "new.txt"
        f.write_bytes(b"should not exist")
        _restore_snapshots({f: None})
        assert not f.exists()

    def test_creates_file_if_deleted(self, tmp_path: Path) -> None:
        f = tmp_path / "deleted.txt"
        _restore_snapshots({f: b"restored"})
        assert f.read_bytes() == b"restored"


class TestRunWithCheck:
    """Test the snapshot-compare-restore drift detection mechanism."""

    def test_no_drift_returns_true(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_bytes(b"key: value\n")

        def sync_fn() -> int:
            f.write_bytes(b"key: value\n")
            return 0

        assert _run_with_check([f], sync_fn, "test") is True
        assert f.read_bytes() == b"key: value\n"

    def test_drift_detected_returns_false(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_bytes(b"key: old_value\n")

        def sync_fn() -> int:
            f.write_bytes(b"key: new_value\n")
            return 0

        assert _run_with_check([f], sync_fn, "test") is False

    def test_originals_restored_after_check(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        original = b"original content"
        f.write_bytes(original)

        def sync_fn() -> int:
            f.write_bytes(b"modified content")
            return 0

        _run_with_check([f], sync_fn, "test")
        assert f.read_bytes() == original

    def test_originals_restored_on_error(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        original = b"original content"
        f.write_bytes(original)

        def sync_fn() -> int:
            f.write_bytes(b"modified before crash")
            raise RuntimeError("sync failed")

        with pytest.raises(RuntimeError, match="sync failed"):
            _run_with_check([f], sync_fn, "test")
        assert f.read_bytes() == original

    def test_dynamic_patterns_ignored_in_comparison(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.yaml"
        f.write_bytes(b'"today": "2026-03-26"\nkey: value\n')

        patterns = [(r'"today": "\d{4}-\d{2}-\d{2}"', '"today": "DATE"')]

        def sync_fn() -> int:
            f.write_bytes(b'"today": "2026-03-27"\nkey: value\n')
            return 0

        assert _run_with_check([f], sync_fn, "test", patterns) is True

    def test_real_drift_detected_despite_dynamic_patterns(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.yaml"
        f.write_bytes(b'"today": "2026-03-26"\nkey: old\n')

        patterns = [(r'"today": "\d{4}-\d{2}-\d{2}"', '"today": "DATE"')]

        def sync_fn() -> int:
            f.write_bytes(b'"today": "2026-03-27"\nkey: new\n')
            return 0

        assert _run_with_check([f], sync_fn, "test", patterns) is False

    def test_multiple_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.yaml"
        f2 = tmp_path / "b.yaml"
        f1.write_bytes(b"a: 1\n")
        f2.write_bytes(b"b: 2\n")

        def sync_fn() -> int:
            f1.write_bytes(b"a: 1\n")
            f2.write_bytes(b"b: changed\n")
            return 0

        assert _run_with_check([f1, f2], sync_fn, "test") is False
