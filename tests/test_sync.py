"""Tests for toolkit sync CLI — drift detection (ADR-027)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from toolkit.cli.sync import (
    HOMEPAGE_DYNAMIC_PATTERNS,
    _normalize_content,
    _restore_snapshots,
    _run_with_check,
)
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

    def test_crlf_and_lf_normalize_equal(self) -> None:
        # TOOL-020: a Windows write (CRLF) and a Linux write (LF) of the same
        # generated content must compare equal — the newline convention isn't
        # SSOT drift.
        lf_content = b"images:\n  - name: foo\n    newTag: v1\n"
        crlf_content = lf_content.replace(b"\n", b"\r\n")
        assert _normalize_content(lf_content, []) == _normalize_content(crlf_content, [])

    def test_svg_payload_normalizes_regardless_of_length(self) -> None:
        # TOOL-020: mermaid.ink is an external, best-effort dependency (now
        # gated in CI for the first time). A transient failure on one run
        # must not look like SSOT drift against a run where it succeeded.
        succeeded = '  topology: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0i",'
        failed = '  topology: "data:image/svg+xml;base64,",'  # empty payload, key still present
        assert _normalize_content(succeeded.encode(), HOMEPAGE_DYNAMIC_PATTERNS) == _normalize_content(
            failed.encode(), HOMEPAGE_DYNAMIC_PATTERNS
        )


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

    def test_a_drift_report_names_the_lines_not_only_the_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The gate is the only check that runs on Windows, so its output is the whole debugger.

        Measured 2026-09-06: `platform.json` drifted on the Windows runner and
        passed on Linux, and the job's entire output was the filename. A
        platform-specific drift is reproducible nowhere a maintainer can attach
        a debugger, so a report that says only THAT something drifted cannot be
        acted on at all.
        """
        f = tmp_path / "generated.json"
        f.write_bytes(b'{\n  "total": 33\n}\n')

        def sync_fn() -> int:
            f.write_bytes(b'{\n  "total": 35\n}\n')
            return 0

        assert _run_with_check([f], sync_fn, "test") is False

        # The project logger renders through Rich to stdout, not through the
        # `logging` module, so caplog sees nothing here — capsys is the surface
        # a CI log actually shows.
        report = capsys.readouterr().out
        assert '-  "total": 33' in report, "the committed value is missing from the diff"
        assert '+  "total": 35' in report, "the generated value is missing from the diff"

    def test_a_difference_the_normalizer_flattens_is_named_as_such(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Bytes differing while normalized text matches is a real state, and an empty diff is not a report.

        `_normalize_content` folds CRLF to LF, so two files can compare unequal
        upstream of it and identical inside it. Printing nothing there would
        leave the reader with a drift claim and no evidence.
        """
        f = tmp_path / "generated.json"
        f.write_bytes(b'{"a": 1}\r\n')

        def sync_fn() -> int:
            f.write_bytes(b'{"a": 1}\n')
            return 0

        result = _run_with_check([f], sync_fn, "test")

        # The normalizer folds this, so the gate itself must stay green.
        assert result is True
        assert "drift detected" not in capsys.readouterr().out

    def test_the_diff_hides_what_the_check_itself_ignores(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A diagnostic that disagrees with its own gate sends people after the wrong line.

        `_run_with_check` compares NORMALIZED bytes, so a value matched by a
        dynamic pattern is deliberately not drift. If the diff were rendered
        from the raw content it would show that value as a change — a line the
        gate had already decided to ignore, printed as the reason it failed.
        """
        f = tmp_path / "generated.json"
        f.write_bytes(b'{\n  "today": "2026-01-01",\n  "total": 33\n}\n')

        def sync_fn() -> int:
            f.write_bytes(b'{\n  "today": "2026-09-06",\n  "total": 35\n}\n')
            return 0

        patterns = [(r'"today": "\d{4}-\d{2}-\d{2}"', '"today": "DATE"')]
        assert _run_with_check([f], sync_fn, "test", dynamic_patterns=patterns) is False

        report = capsys.readouterr().out
        assert '"total": 35' in report, "the real change is missing from the diff"
        assert "2026-09-06" not in report, (
            "the diff shows a value the gate normalizes away — it is rendering raw bytes, "
            "so it reports as the cause a line that was never the cause"
        )

    def test_a_wholesale_regeneration_does_not_bury_the_log(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A file regenerated from scratch differs in every line, and an uncapped diff is not a report."""
        f = tmp_path / "generated.json"
        f.write_bytes(b"".join(b'"old-%d"\n' % i for i in range(400)))

        def sync_fn() -> int:
            f.write_bytes(b"".join(b'"new-%d"\n' % i for i in range(400)))
            return 0

        assert _run_with_check([f], sync_fn, "test") is False

        report = capsys.readouterr().out
        assert "diff truncated" in report, "an 800-line diff went to the log unbounded"
        assert report.count("new-") < 400, "the cap did not bound the output"

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
