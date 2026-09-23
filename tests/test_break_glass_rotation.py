"""AUTH-004 AC7: one operation rotates every break-glass account, and never loses a password.

Each account's password lives in the application's own database (Grafana, Gitea),
not in anything Argo CD applies. So a rotation that writes SOPS and stops would
leave SOPS saying one thing and the service another, which is the state in
which a break-glass path fails exactly when it is needed. The order is therefore
fixed, and every step after the first can be undone:

1. the current SOPS value must open the service, or nothing is touched (drift);
2. the new value is written to SOPS first (write-ahead);
3. the service is changed, authenticating with the old value;
4. the new value must open it and the old one must not;
5. any failure after step 2 restores SOPS, and the service too if it had changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from toolkit.features import break_glass_rotation as rot


@dataclass
class FakeService:
    """An application account: one live password, and knobs to make each step fail."""

    password: str
    refuse_set: bool = False
    set_but_keep_old: bool = False
    calls: list[str] = field(default_factory=list)

    def set_password(self, base_url: str, user: str, old: str, new: str) -> None:
        self.calls.append(f"set {old}->{new}")
        if old != self.password:
            raise RuntimeError("401")
        if self.refuse_set:
            raise RuntimeError("422 password rejected")
        if not self.set_but_keep_old:
            self.password = new

    def verify(self, base_url: str, user: str, password: str) -> bool:
        return password == self.password


@dataclass
class FakeVault:
    value: str | None
    fail_writes: int = 0
    writes: list[str] = field(default_factory=list)

    def read(self) -> str | None:
        return self.value

    def write(self, value: str) -> bool:
        self.writes.append(value)
        if self.fail_writes:
            self.fail_writes -= 1
            return False
        self.value = value
        return True


def _rotate(service: FakeService, vault: FakeVault) -> rot.Outcome:
    return rot.rotate_one(
        "grafana",
        "manu",
        base_url="http://127.0.0.1:1",
        reconciler=service,
        read=vault.read,
        write=vault.write,
        generate=lambda: "NEW",
    )


def test_a_clean_rotation_leaves_sops_and_the_service_on_the_new_value() -> None:
    service, vault = FakeService("OLD"), FakeVault("OLD")
    outcome = _rotate(service, vault)
    assert outcome.ok
    assert (vault.value, service.password) == ("NEW", "NEW")


def test_drift_between_sops_and_the_service_touches_nothing() -> None:
    service, vault = FakeService("LIVE"), FakeVault("STALE")
    outcome = _rotate(service, vault)
    assert not outcome.ok and "drift" in outcome.detail
    assert vault.writes == [] and service.calls == []


def test_a_missing_sops_value_touches_nothing() -> None:
    service, vault = FakeService("LIVE"), FakeVault(None)
    assert not _rotate(service, vault).ok
    assert vault.writes == [] and service.calls == []


def test_a_failed_write_ahead_leaves_the_service_untouched() -> None:
    service, vault = FakeService("OLD"), FakeVault("OLD", fail_writes=1)
    assert not _rotate(service, vault).ok
    assert service.calls == [] and service.password == "OLD"


def test_a_service_that_refuses_the_change_gets_sops_restored() -> None:
    service, vault = FakeService("OLD", refuse_set=True), FakeVault("OLD")
    outcome = _rotate(service, vault)
    assert not outcome.ok
    assert (vault.value, service.password) == ("OLD", "OLD")


def test_a_change_that_does_not_verify_is_undone_on_both_sides() -> None:
    service, vault = FakeService("OLD", set_but_keep_old=True), FakeVault("OLD")
    outcome = _rotate(service, vault)
    assert not outcome.ok
    assert (vault.value, service.password) == ("OLD", "OLD")


def test_a_restore_that_fails_says_so_and_names_the_recovery() -> None:
    service, vault = FakeService("OLD", refuse_set=True), FakeVault("OLD")
    vault.fail_writes = 0
    original_write = vault.write

    def write(value: str) -> bool:
        return value == "NEW" and original_write(value)  # write-ahead succeeds, the restore fails

    outcome = rot.rotate_one(
        "grafana", "manu", base_url="x", reconciler=service, read=vault.read, write=write, generate=lambda: "NEW"
    )
    assert not outcome.ok
    assert "NOT restored" in outcome.detail and "cluster credential" in outcome.detail


class TestTargets:
    """What gets rotated is derived from the break-glass declaration, never listed."""

    def test_only_account_declarations_are_rotated(self) -> None:
        decls: dict[str, Any] = {
            "grafana": {"identity": "superadmin", "secret": "apps.services.observability.grafana.admin_password"},
            "argocd": {"cluster": "hub"},
            "loki": {},
            "vikunja": {"none": "x"},
        }
        assert [t.service for t in rot.targets(decls)] == ["grafana"]

    def test_every_account_declaration_has_a_reconciler(self) -> None:
        from toolkit.features import break_glass as bg
        from toolkit.features.oidc_clients import load_values

        accounts = [t.service for t in rot.targets(bg.declarations(load_values("prod")))]
        assert accounts, "no break-glass account is declared: this test would pass vacuously"
        missing = [service for service in accounts if service not in rot.RECONCILERS]
        assert not missing, f"break-glass accounts with no way to rotate them: {missing}"


class TestReconcilers:
    """The two HTTP shapes, pinned without a network."""

    def test_grafana_changes_its_own_password_with_the_old_one(self) -> None:
        sent: list[tuple[str, str, Any, str]] = []
        grafana = rot.GrafanaAdminPassword(
            request=lambda m, u, body, auth: sent.append((m, u, body, auth)) or (200, {})
        )
        grafana.set_password("http://g", "manu", "OLD", "NEW")
        [(method, url, body, auth)] = sent
        assert (method, url) == ("PUT", "http://g/api/user/password")
        assert body == {"oldPassword": "OLD", "newPassword": "NEW", "confirmNew": "NEW"}
        assert auth == "manu:OLD"

    def test_gitea_sends_login_name_because_1_25_requires_it(self) -> None:
        sent: list[tuple[str, str, Any, str]] = []

        def request(method: str, url: str, body: Any, auth: str) -> tuple[int, Any]:
            sent.append((method, url, body, auth))
            return 200, {}

        rot.GiteaAdminPassword(request=request).set_password("http://t", "manu", "OLD", "NEW")
        [(method, url, body, auth)] = sent
        assert (method, url, auth) == ("PATCH", "http://t/api/v1/admin/users/manu", "manu:OLD")
        assert body["password"] == "NEW" and body["login_name"] == "manu" and body["must_change_password"] is False

    @pytest.mark.parametrize("cls", [rot.GrafanaAdminPassword, rot.GiteaAdminPassword])
    def test_verify_requires_the_right_user_not_just_a_200(self, cls: Any) -> None:
        ok = cls(request=lambda *a: (200, {"login": "manu"}))
        wrong_user = cls(request=lambda *a: (200, {"login": "someone-else"}))
        refused = cls(request=lambda *a: (401, {}))
        assert ok.verify("http://x", "manu", "p")
        assert not wrong_user.verify("http://x", "manu", "p")
        assert not refused.verify("http://x", "manu", "p")

    @pytest.mark.parametrize("cls", [rot.GrafanaAdminPassword, rot.GiteaAdminPassword])
    def test_a_refused_change_raises(self, cls: Any) -> None:
        with pytest.raises(rot.RotationError):
            cls(request=lambda *a: (422, {"message": "no"})).set_password("http://x", "manu", "OLD", "NEW")


def test_credentials_generate_preserves_break_glass_passwords() -> None:
    """`credentials generate` must not reset a break-glass password to the shared prompt value (#1355)."""
    from toolkit.features.credentials import CredentialsManager

    key = "apps.services.observability.grafana.admin_password"
    kept = CredentialsManager.preserve_break_glass({key: "prompt-value", "other": "x"}, {key: "rotated-value"})
    assert kept[key] == "rotated-value" and kept["other"] == "x"
