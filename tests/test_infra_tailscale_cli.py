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
    bundle.touch()
    assert fixtures.tailscale_cli(which=lambda _: "/usr/bin/tailscale", bundle=bundle) == "/usr/bin/tailscale"


def test_the_macos_bundle_is_used_when_path_has_none(tmp_path: Path) -> None:
    bundle = tmp_path / "Tailscale"
    bundle.touch()
    assert fixtures.tailscale_cli(which=lambda _: None, bundle=bundle) == str(bundle)


def test_no_cli_anywhere_is_none(tmp_path: Path) -> None:
    assert fixtures.tailscale_cli(which=lambda _: None, bundle=tmp_path / "absent") is None


def test_the_bundle_path_is_the_one_the_macos_app_installs() -> None:
    assert Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale") == fixtures.MACOS_TAILSCALE_CLI


def test_an_absent_cli_is_not_reported_as_a_down_tailnet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fixtures, "tailscale_cli", lambda: None)
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
