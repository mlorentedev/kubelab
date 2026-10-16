"""PREP-002 (#244): the VPS snapshot is an idempotent, labelled, verified action.

A snapshot is the rollback of last resort for the prod host, taken before a risky
change. It is crash-consistent only (ADR-024): SQLite may be torn, so it is not a
backup. These tests run the real client against an in-memory Hetzner Cloud that
behaves the way the API documents (`POST /servers/{id}/actions/create_image`
answers an action and an image in `creating`; the image becomes `available` when
the action succeeds), so the polling, the idempotency and the pruning are
exercised, not asserted by reading the code.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features.vps_snapshot import (
    MANAGED_LABEL,
    HetznerClient,
    PruneError,
    SnapshotError,
    apply,
    description_for,
    plan,
)

# The committed SSOT, not a copy of it: a renamed server or a new address must reach these
# tests, because `make vps-snapshot` reads the same keys at runtime.
CONFIG = yaml.safe_load(Path("infra/config/values/common.yaml").read_text(encoding="utf-8"))
SERVER_NAME = CONFIG["networking"]["vps"]["hetzner_server_name"]
PUBLIC_IP = CONFIG["networking"]["vps"]["public_ip"]
TODAY = date(2026, 10, 16)


class FakeHetzner:
    """Enough of Hetzner Cloud for the snapshot flow. Records every request."""

    def __init__(
        self, *, server_ip: str = PUBLIC_IP, servers: int = 1, action_status: str = "success", delete_status: int = 204
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.server_ip = server_ip
        self.n_servers = servers
        self.action_status = action_status
        self.delete_status = delete_status
        self.images: dict[int, dict[str, Any]] = {}
        self.next_id = 100

    def add_snapshot(self, description: str, created: str, status: str = "available", *, managed: bool = True) -> int:
        self.next_id += 1
        labels = {MANAGED_LABEL[0]: MANAGED_LABEL[1], "server": SERVER_NAME} if managed else {"keep": "me"}
        self.images[self.next_id] = {
            "id": self.next_id,
            "type": "snapshot",
            "description": description,
            "created": created,
            "status": status,
            "labels": labels,
        }
        return self.next_id

    def request(self, method: str, url: str, **kwargs: Any) -> MagicMock:
        path = url.split("/v1", 1)[1]
        self.calls.append((method, path, kwargs))
        status, body = self._route(method, path, kwargs)
        resp = MagicMock()
        resp.ok = status < 400
        resp.status_code = status
        resp.content = b"x"
        resp.text = str(body)
        resp.json.return_value = body
        return resp

    def _route(self, method: str, path: str, kwargs: dict[str, Any]) -> tuple[int, Any]:
        if method == "GET" and path == "/servers":
            if kwargs["params"].get("name") != SERVER_NAME or self.n_servers == 0:
                return 200, {"servers": []}
            one = {"id": 7, "name": SERVER_NAME, "public_net": {"ipv4": {"ip": self.server_ip}}}
            return 200, {"servers": [one] * self.n_servers}
        if method == "GET" and path == "/images":
            selector = kwargs["params"].get("label_selector", "")
            wanted = dict(p.split("=") for p in selector.split(",") if p)
            found = [i for i in self.images.values() if all(i["labels"].get(k) == v for k, v in wanted.items())]
            return 200, {"images": found}
        if method == "POST" and path == "/servers/7/actions/create_image":
            body = kwargs["json"]
            self.next_id += 1
            self.images[self.next_id] = {
                "id": self.next_id,
                "type": "snapshot",
                "description": body["description"],
                "created": "2026-10-16T12:00:00+00:00",
                "status": "creating",
                "labels": body["labels"],
            }
            return 201, {"action": {"id": 900, "status": "running"}, "image": self.images[self.next_id]}
        if method == "GET" and path == "/actions/900":
            error = {"code": "server_error", "message": "boom"} if self.action_status == "error" else None
            if self.action_status == "success":
                for image in self.images.values():
                    if image["status"] == "creating":
                        image["status"] = "available"
            return 200, {"action": {"id": 900, "status": self.action_status, "error": error}}
        if method == "GET" and path.startswith("/images/"):
            return 200, {"image": self.images[int(path.rsplit("/", 1)[1])]}
        if method == "DELETE" and path.startswith("/images/"):
            if self.delete_status >= 400:
                return self.delete_status, {"error": {"message": "gone"}}
            del self.images[int(path.rsplit("/", 1)[1])]
            return 204, {}
        return 404, {"error": {"message": f"unrouted {method} {path}"}}

    def verbs(self) -> list[str]:
        return [f"{m} {p}" for m, p, _ in self.calls]


def client_for(fake: FakeHetzner) -> HetznerClient:
    c = HetznerClient(token="t0ken")
    c.session = MagicMock()
    c.session.request.side_effect = fake.request
    return c


def run(fake: FakeHetzner, *, keep: int | None = None, apply_it: bool = True) -> Any:
    c = client_for(fake)
    p = plan(c, CONFIG, today=TODAY, keep=keep)
    return p, (apply(c, p, interval=0, timeout=0.2) if apply_it else None)


# ── what the snapshot is called and labelled ─────────────────────────────────


def test_the_description_is_dated() -> None:
    assert description_for(TODAY) == "kubelab-vps-2026-10-16"


def test_the_snapshot_is_labelled_so_nothing_else_is_ever_touched() -> None:
    fake = FakeHetzner()
    run(fake)
    (create,) = [kw for m, p, kw in fake.calls if m == "POST"]
    assert create["json"]["type"] == "snapshot"
    assert create["json"]["labels"][MANAGED_LABEL[0]] == MANAGED_LABEL[1]
    # The literal is a cross-system contract (the prune selector, the runbook, and the
    # snapshots already taken carry it): renaming it must be a deliberate edit here too.
    assert MANAGED_LABEL == ("managed-by", "kubelab-toolkit")
    assert create["json"]["description"] == "kubelab-vps-2026-10-16"


def test_the_token_travels_in_the_header_only() -> None:
    fake = FakeHetzner()
    run(fake)
    for _, path, kw in fake.calls:
        assert kw["headers"]["Authorization"] == "Bearer t0ken"
        assert "t0ken" not in path and "t0ken" not in str(kw.get("params", "")) + str(kw.get("json", ""))


# ── the right server, or nothing ─────────────────────────────────────────────


def test_a_server_at_another_address_is_refused() -> None:
    """The firewall module's guard, reused: a renamed server must not be snapshotted as the VPS."""
    with pytest.raises(SnapshotError, match=PUBLIC_IP):
        run(FakeHetzner(server_ip="10.9.9.9"))


@pytest.mark.parametrize("count", [0, 2])
def test_the_name_must_resolve_to_exactly_one_server(count: int) -> None:
    with pytest.raises(SnapshotError, match="exactly one"):
        run(FakeHetzner(servers=count))


@pytest.mark.parametrize("missing", ["hetzner_server_name", "public_ip"])
def test_the_ssot_keys_are_required(missing: str) -> None:
    config = {"networking": {"vps": {k: v for k, v in CONFIG["networking"]["vps"].items() if k != missing}}}
    with pytest.raises(SnapshotError, match=f"networking.vps.{missing}"):
        plan(client_for(FakeHetzner()), config, today=TODAY)


# ── idempotent per day ───────────────────────────────────────────────────────


def test_the_first_run_creates_and_waits_for_the_image() -> None:
    fake = FakeHetzner()
    p, image = run(fake)
    assert p.exists is False
    assert image["status"] == "available"
    assert "GET /actions/900" in fake.verbs()


def test_a_second_run_the_same_day_changes_nothing() -> None:
    fake = FakeHetzner()
    run(fake)
    before = len(fake.images)
    p, image = run(fake)
    assert p.exists is True
    assert len(fake.images) == before
    assert image["description"] == "kubelab-vps-2026-10-16"
    assert [v for v in fake.verbs() if v.startswith("POST")].count("POST /servers/7/actions/create_image") == 1


def test_a_plan_alone_writes_nothing() -> None:
    fake = FakeHetzner()
    p, _ = run(fake, apply_it=False)
    assert p.exists is False
    assert not [v for v in fake.verbs() if v.split()[0] in {"POST", "DELETE"}]


# ── failure is loud ──────────────────────────────────────────────────────────


def test_a_failed_action_raises_with_the_reason() -> None:
    with pytest.raises(SnapshotError, match="boom"):
        run(FakeHetzner(action_status="error"))


def test_the_plan_does_not_call_an_unfinished_image_a_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHetzner()
    # The command takes its own "today", so the fixture is dated by the same clock.
    fake.add_snapshot(description_for(TODAY), "2026-10-16T08:00:00+00:00", status="creating")
    result = _invoke(monkeypatch, fake)
    assert result.exit_code == 0, result.output
    assert "already exists" not in result.output
    assert "creating" in result.output


@pytest.mark.parametrize("status", ["creating", "unavailable"])
def test_a_rerun_never_reports_an_unfinished_snapshot_as_done(status: str) -> None:
    # A timed-out run leaves today's image behind; the rerun finds it by description and
    # must not call it a rollback point until Hetzner says `available` (PR-Agent, #2351).
    fake = FakeHetzner()
    fake.add_snapshot("kubelab-vps-2026-10-16", "2026-10-16T08:00:00+00:00", status=status)
    with pytest.raises(SnapshotError, match=status):
        run(fake)
    assert not [v for v in fake.verbs() if v.split()[0] in {"POST", "DELETE"}]


def test_an_action_that_never_finishes_times_out() -> None:
    with pytest.raises(SnapshotError, match="did not finish"):
        run(FakeHetzner(action_status="running"))


# ── pruning is opt-in and label-scoped ───────────────────────────────────────


def test_no_snapshot_is_deleted_unless_asked() -> None:
    fake = FakeHetzner()
    for day in range(1, 6):
        fake.add_snapshot(f"kubelab-vps-2026-10-0{day}", f"2026-10-0{day}T00:00:00+00:00")
    run(fake)
    assert len(fake.images) == 6
    assert not [v for v in fake.verbs() if v.startswith("DELETE")]


def test_prune_keeps_the_newest_n_managed_snapshots_and_never_a_foreign_one() -> None:
    fake = FakeHetzner()
    for day in range(1, 6):
        fake.add_snapshot(f"kubelab-vps-2026-10-0{day}", f"2026-10-0{day}T00:00:00+00:00")
    foreign = fake.add_snapshot("hand-made", "2020-01-01T00:00:00+00:00", managed=False)
    run(fake, keep=2)
    kept = sorted(i["description"] for i in fake.images.values())
    assert kept == ["hand-made", "kubelab-vps-2026-10-05", "kubelab-vps-2026-10-16"]
    assert foreign in fake.images


def test_prune_never_deletes_the_snapshot_just_taken_or_all_of_them() -> None:
    fake = FakeHetzner()
    with pytest.raises(SnapshotError, match="at least 1"):
        plan(client_for(fake), CONFIG, today=TODAY, keep=0)


def test_a_failed_image_never_takes_a_keep_slot_from_a_restorable_one() -> None:
    fake = FakeHetzner()
    fake.add_snapshot("kubelab-vps-2026-10-01", "2026-10-01T00:00:00+00:00")
    fake.add_snapshot("kubelab-vps-2026-10-02", "2026-10-02T00:00:00+00:00")
    stuck = fake.add_snapshot("kubelab-vps-2026-10-15", "2026-10-15T00:00:00+00:00", status="creating")
    run(fake, keep=2)
    kept = {i["description"] for i in fake.images.values()}
    # keep=2 means today's plus the newest restorable one; the unfinished image is left alone
    assert kept == {"kubelab-vps-2026-10-02", "kubelab-vps-2026-10-15", "kubelab-vps-2026-10-16"}
    assert stuck in fake.images


def test_the_plan_counts_what_accumulates_without_keep() -> None:
    fake = FakeHetzner()
    for day in range(1, 5):
        fake.add_snapshot(f"kubelab-vps-2026-10-0{day}", f"2026-10-0{day}T00:00:00+00:00")
    p, _ = run(fake, apply_it=False)
    assert p.managed_count == 4


def test_the_command_warns_when_snapshots_pile_up_without_keep(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHetzner()
    for day in range(1, 5):
        fake.add_snapshot(f"kubelab-vps-2026-10-0{day}", f"2026-10-0{day}T00:00:00+00:00")
    result = _invoke(monkeypatch, fake)
    assert result.exit_code == 0, result.output
    assert "4 managed snapshots" in result.output
    assert "--keep" in result.output


def test_the_command_is_quiet_about_retention_when_few_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, FakeHetzner())
    assert result.exit_code == 0, result.output
    assert "does not exist yet" in result.output
    assert "managed snapshots" not in result.output


def test_a_failed_prune_still_reports_the_snapshot_that_was_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHetzner(delete_status=404)
    for day in range(1, 4):
        fake.add_snapshot(f"kubelab-vps-2026-10-0{day}", f"2026-10-0{day}T00:00:00+00:00")
    result = _invoke(monkeypatch, fake, "--apply", "--keep", "1")
    assert result.exit_code == 1, result.output
    assert "kubelab-vps-2026-10-16 is available" in result.output
    assert "pruning failed" in result.output


def test_a_failed_prune_raises_an_error_that_carries_the_image() -> None:
    fake = FakeHetzner(delete_status=404)
    fake.add_snapshot("kubelab-vps-2026-10-01", "2026-10-01T00:00:00+00:00")
    with pytest.raises(PruneError) as caught:
        run(fake, keep=1)
    assert caught.value.image["status"] == "available"


# ── the command ──────────────────────────────────────────────────────────────


def _invoke(monkeypatch: pytest.MonkeyPatch, fake: FakeHetzner, *args: str, token: str | None = "t0ken") -> Any:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app
    from toolkit.features import vps_snapshot

    cm = MagicMock()
    cm.get_secret_by_path.return_value = token
    cm.get_merged_config.return_value = CONFIG
    monkeypatch.setattr("toolkit.features.configuration.ConfigurationManager", lambda env: cm)

    def make_client(token: str) -> HetznerClient:
        return client_for(fake)

    monkeypatch.setattr(vps_snapshot, "HetznerClient", make_client)
    monkeypatch.setattr(vps_snapshot, "today_utc", lambda: TODAY)
    return CliRunner().invoke(app, ["vps", "snapshot", *args])


def test_the_command_reports_a_plan_and_writes_nothing_without_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHetzner()
    result = _invoke(monkeypatch, fake)
    assert result.exit_code == 0, result.output
    assert "plan only" in result.output
    assert not [v for v in fake.verbs() if v.split()[0] in {"POST", "DELETE"}]


def test_the_command_takes_the_snapshot_with_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHetzner()
    result = _invoke(monkeypatch, fake, "--apply")
    assert result.exit_code == 0, result.output
    assert "available" in result.output
    assert len(fake.images) == 1


def test_a_missing_token_is_an_exit_one_naming_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, FakeHetzner(), "--apply", token=None)
    assert result.exit_code == 1
    assert "hetzner.api_key" in result.output


def test_a_refused_server_is_an_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, FakeHetzner(server_ip="10.9.9.9"), "--apply")
    assert result.exit_code == 1
    assert "refusing" in result.output


def test_the_make_target_defaults_to_a_plan() -> None:
    from pathlib import Path

    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("vps-snapshot:", 1)[1].split("\n\n", 1)[0]
    assert "$(if $(APPLY),--apply)" in target and "infra vps snapshot" in target
