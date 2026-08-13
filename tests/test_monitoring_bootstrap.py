"""Unit tests for `monitoring.bootstrap` and its `_run_setup` helper (#962).

`bootstrap()` used to infer "admin already exists" from whichever exception
`UptimeKumaApi.setup()` raised — including a v1-era wrapper timing out against
Kuma v2's setup handshake, which then fell through to `login()` and failed with
the wrong error on a genuinely fresh instance. It also used to import the seed
via `upload_backup`'s v1 backup envelope, which turned out to time out against
v2 too (confirmed live, not just mocked) — the fresh-install branch now
delegates to `apply_monitors`, which already owns a working, tested create path.

An already-configured instance must still come out of this untouched:
`bootstrap` runs unattended on every rpi3 provision (Ansible), not just the
first one, so it must never gain `apply_monitors`'s delete-what-the-seed-
dropped power on that automated path — that is exactly the hazard #962/#925
removed from `apply_monitors` itself.

These tests exercise the branch selection with a mocked API, no live Uptime
Kuma required. Live coverage — `_run_setup` and `apply_monitors` end to end
against a real v2 container, including the fresh-instance path this file only
mocks — is `test_monitoring_integration.py`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from toolkit.features import monitoring

_CREDS = {"url": "http://kuma:3001", "host": "kuma", "username": "admin", "password": "secret"}


def _api(need_setup: bool) -> MagicMock:
    api = MagicMock()
    api.timeout = 60
    api.need_setup.return_value = need_setup
    return api


class TestRunSetup:
    """The raw-socket workaround in isolation — no `bootstrap()` involved."""

    def test_returns_normally_on_a_positive_ack(self) -> None:
        api = MagicMock()
        api.timeout = 5
        api.sio.emit.side_effect = lambda event, data, callback: callback({"ok": True, "msg": "successAdded"})

        monitoring._run_setup(api, "admin", "secret")  # must not raise

        call = api.sio.emit.call_args
        assert call.args == ("setup", ("admin", "secret"))
        assert callable(call.kwargs["callback"])

    def test_raises_runtime_error_on_a_negative_ack(self) -> None:
        api = MagicMock()
        api.timeout = 5
        api.sio.emit.side_effect = lambda event, data, callback: callback(
            {"ok": False, "msg": "Admin user already exists"}
        )

        with pytest.raises(RuntimeError, match="Admin user already exists"):
            monitoring._run_setup(api, "admin", "secret")

    def test_raises_timeout_error_when_the_server_never_acks(self) -> None:
        """The regression itself: a swallowed timeout must surface as failure."""
        api = MagicMock()
        api.timeout = 0  # deadline already elapsed by the first poll check
        api.sio.emit.side_effect = lambda event, data, callback: None  # no ack, ever

        with pytest.raises(TimeoutError):
            monitoring._run_setup(api, "admin", "secret")


class TestBootstrap:
    """`bootstrap()`'s branch selection — must come from `need_setup()`, not from
    catching whatever `setup()` raises — and its delegation to `apply_monitors`."""

    def test_fresh_instance_runs_setup_then_converges_monitors(self, tmp_path) -> None:
        api = _api(need_setup=True)
        with (
            patch.object(monitoring, "_get_kuma_creds", return_value=_CREDS),
            patch.object(monitoring, "UptimeKumaApi", return_value=api),
            patch.object(monitoring, "_run_setup") as run_setup,
            patch.object(monitoring, "apply_monitors") as apply_monitors,
        ):
            monitoring.bootstrap(tmp_path)

        run_setup.assert_called_once_with(api, "admin", "secret")
        api.disconnect.assert_called_once()
        apply_monitors.assert_called_once_with(tmp_path)

    def test_existing_instance_skips_setup_and_leaves_monitors_untouched(self, tmp_path) -> None:
        """An already-configured instance must never gain a delete path (#962/#925)."""
        api = _api(need_setup=False)
        with (
            patch.object(monitoring, "_get_kuma_creds", return_value=_CREDS),
            patch.object(monitoring, "UptimeKumaApi", return_value=api),
            patch.object(monitoring, "_run_setup") as run_setup,
            patch.object(monitoring, "apply_monitors") as apply_monitors,
        ):
            monitoring.bootstrap(tmp_path)

        run_setup.assert_not_called()
        api.disconnect.assert_called_once()
        apply_monitors.assert_not_called()

    def test_a_setup_timeout_propagates_instead_of_reading_as_already_exists(self, tmp_path) -> None:
        """The exact defect: a timeout must abort, never fall through as success."""
        api = _api(need_setup=True)
        with (
            patch.object(monitoring, "_get_kuma_creds", return_value=_CREDS),
            patch.object(monitoring, "UptimeKumaApi", return_value=api),
            patch.object(monitoring, "_run_setup", side_effect=TimeoutError("no ack")),
            patch.object(monitoring, "apply_monitors") as apply_monitors,
        ):
            with pytest.raises(TimeoutError):
                monitoring.bootstrap(tmp_path)

        apply_monitors.assert_not_called()
