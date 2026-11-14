"""Which Uptime Kuma monitors are DOWN right now (#3156).

`make alerts` read Grafana only, so an outage Uptime Kuma saw never reached a
session. This is the read it adds, and it raises rather than answering "nothing
is down" when Kuma cannot be asked.
"""

from __future__ import annotations

from typing import Any

from uptime_kuma_api import MonitorStatus

from toolkit.config.settings import get_settings
from toolkit.features.monitoring import _connect


class KumaUnavailableError(RuntimeError):
    """Uptime Kuma could not be asked; distinct from "nothing is down"."""


def _flat_beats(beats: list[Any]) -> list[dict[str, Any]]:
    """The beats, with any history the client nested as one element spread back out.

    uptime-kuma-api 1.2.1 appends a monitor's `heartbeatList` as a single element
    when a live `heartbeat` for it arrived first, instead of extending (#3458).
    """
    flat: list[dict[str, Any]] = []
    for beat in beats:
        flat.extend(beat if isinstance(beat, list) else [beat])
    return flat


def down_monitors(monitors: list[dict[str, Any]], heartbeats: dict[int, list[dict[str, Any]]]) -> list[dict[str, str]]:
    """Active monitors whose newest heartbeat is DOWN, with that beat's message and time."""
    down = []
    for monitor in monitors:
        beats = _flat_beats(heartbeats.get(monitor["id"]) or [])
        if not monitor.get("active") or not beats:
            continue
        latest = max(beats, key=lambda beat: beat.get("time") or "")
        if latest.get("status") == MonitorStatus.DOWN:
            msg = (latest.get("msg") or "").strip().splitlines()
            down.append({"name": monitor["name"], "msg": msg[0] if msg else "", "checked": latest.get("time") or ""})
    return down


def ask_down_monitors() -> list[dict[str, str]]:
    try:
        api, _ = _connect(get_settings().project_root)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - every failure means "not asked"
        raise KumaUnavailableError(f"could not reach Uptime Kuma: {exc}") from exc
    try:
        return down_monitors(api.get_monitors(), api.get_heartbeats())
    except Exception as exc:  # noqa: BLE001
        raise KumaUnavailableError(f"Uptime Kuma did not answer: {exc}") from exc
    finally:
        api.disconnect()
