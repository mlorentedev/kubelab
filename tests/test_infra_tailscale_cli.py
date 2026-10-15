"""#2283 (TOOL-115): the infra suite finds the Tailscale CLI on macOS.

The macOS app keeps its CLI inside the bundle and puts nothing on PATH, so a
lookup by name alone reported "VPN not connected" and skipped every infra test
on the Mac while the tailnet was up. Nothing here spawns `tailscale`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.infra import fixtures


def test_the_cli_on_path_wins(tmp_path: Path) -> None:
    bundle = tmp_path / "Tailscale"
    bundle.touch(mode=0o755)
    assert fixtures.tailscale_cli(which=lambda _: "/usr/bin/tailscale", bundle=bundle) == "/usr/bin/tailscale"


def test_the_macos_bundle_is_used_when_path_has_none(tmp_path: Path) -> None:
    bundle = tmp_path / "Tailscale"
    bundle.touch(mode=0o755)
    assert fixtures.tailscale_cli(which=lambda _: None, bundle=bundle) == str(bundle)


def test_no_cli_anywhere_is_none(tmp_path: Path) -> None:
    assert fixtures.tailscale_cli(which=lambda _: None, bundle=tmp_path / "absent") is None


def test_the_bundle_path_is_the_one_the_macos_app_installs() -> None:
    assert Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale") == fixtures.MACOS_TAILSCALE_CLI


def test_an_absent_cli_is_not_reported_as_a_down_tailnet(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fixtures, "tailscale_cli", lambda: None)
    monkeypatch.setattr(fixtures, "MACOS_TAILSCALE_CLI", tmp_path / "absent")
    reason = fixtures.vpn_unavailable()
    assert reason is not None
    assert reason.startswith("Tailscale CLI not found")
    assert "not connected" not in reason


@pytest.mark.parametrize(("returncode", "expected"), [(0, None), (1, "exited 1")])
def test_a_found_cli_reports_the_tailnet_state(
    monkeypatch: pytest.MonkeyPatch, returncode: int, expected: str | None
) -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **_: object) -> object:
        calls.append(cmd)
        return type("Done", (), {"returncode": returncode})()

    monkeypatch.setattr(fixtures, "tailscale_cli", lambda: "/opt/ts/tailscale")
    monkeypatch.setattr(fixtures.subprocess, "run", run)
    reason = fixtures.vpn_unavailable()
    assert calls == [["/opt/ts/tailscale", "status", "--json"]]
    if expected is None:
        assert reason is None
    else:
        assert reason is not None and "not connected" in reason and expected in reason


def test_a_bundle_that_cannot_be_executed_is_not_a_cli(tmp_path: Path) -> None:
    bundle = tmp_path / "Tailscale"
    bundle.touch(mode=0o644)
    assert fixtures.tailscale_cli(which=lambda _: None, bundle=bundle) is None


def test_a_cli_that_cannot_run_is_not_reported_as_a_down_tailnet(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(cmd: list[str], **_: object) -> object:
        raise PermissionError(13, "Permission denied", cmd[0])

    monkeypatch.setattr(fixtures, "tailscale_cli", lambda: "/opt/ts/tailscale")
    monkeypatch.setattr(fixtures.subprocess, "run", run)
    reason = fixtures.vpn_unavailable()
    assert reason is not None and reason.startswith("Tailscale CLI cannot run")
    assert "not connected" not in reason


def test_a_bundle_without_its_execute_bit_is_named_as_such(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundle = tmp_path / "Tailscale"
    bundle.touch(mode=0o644)
    monkeypatch.setattr(fixtures, "tailscale_cli", lambda: None)
    monkeypatch.setattr(fixtures, "MACOS_TAILSCALE_CLI", bundle)
    reason = fixtures.vpn_unavailable()
    assert reason == f"Tailscale CLI cannot run: {bundle} is not executable"


@pytest.mark.parametrize(
    "reason",
    ["Tailscale CLI not found: not on PATH", "Tailscale CLI cannot run: x", "Tailscale not connected: exited 1"],
)
def test_the_infra_skip_carries_the_reason(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    """What an operator reads in `make test-infra`: the fixture, not the helper."""
    from tests.infra import conftest

    monkeypatch.setattr(conftest, "vpn_unavailable", lambda: reason)
    with pytest.raises(pytest.skip.Exception) as skipped:
        conftest.require_vpn.__wrapped__()
    assert str(skipped.value).startswith(f"{reason} — ")


def test_the_infra_fixture_does_not_skip_on_a_connected_tailnet(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.infra import conftest

    monkeypatch.setattr(conftest, "vpn_unavailable", lambda: None)
    assert conftest.require_vpn.__wrapped__() is None
