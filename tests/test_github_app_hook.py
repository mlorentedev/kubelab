"""The kubelab-console GitHub App's webhook, converged from the declaration (CONSOLE-004).

No network: the App JWT is checked against the public half of a key made here, and
the hook API is a fake that records what was sent.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from toolkit.features.github_app_hook import (
    GitHubAppHooks,
    HookConfigError,
    HookSpec,
    REQUIRED_PERMISSIONS,
    app_jwt,
    converge,
    declared_hook,
    hook_changes,
    installation_gaps,
)

NOW = 1_800_000_000


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()


def test_the_app_jwt_is_rs256_signed_and_bounded(key: rsa.RSAPrivateKey) -> None:
    token = app_jwt(5573076, _pem(key), now=NOW)
    header, claims, sig = token.split(".")
    assert json.loads(_b64(header)) == {"alg": "RS256", "typ": "JWT"}
    body = json.loads(_b64(claims))
    # Backdated for clock drift, and GitHub refuses an expiry past ten minutes.
    assert body == {"iss": "5573076", "iat": NOW - 60, "exp": NOW + 540}
    key.public_key().verify(_b64(sig), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())


def test_the_hook_url_is_derived_from_the_api_domain() -> None:
    merged = {"apps": {"platform": {"api": {"domain": "api.kubelab.live"}}}}
    assert declared_hook(merged) == HookSpec(url="https://api.kubelab.live/api/forge/webhooks/github")


def test_the_derived_url_is_the_receiver_route_prod_declares() -> None:
    with open("infra/config/values/prod.yaml", encoding="utf-8") as f:
        prod = yaml.safe_load(f)
    assert declared_hook(prod).url == f"https://{prod['apps']['platform']['api']['domain']}/api/forge/webhooks/github"


def test_changes_name_each_visible_field_that_differs() -> None:
    spec = HookSpec(url="https://api.example/api/forge/webhooks/github")
    live = {"url": "", "content_type": "form", "insecure_ssl": "0", "secret": "********"}
    assert hook_changes(live, spec) == (
        ("url", "", spec.url),
        ("content_type", "form", "json"),
    )
    assert hook_changes({**live, "url": spec.url, "content_type": "json"}, spec) == ()


#: What the installation reported on 2026-11-16 once the owner accepted the widened App.
GRANTED = {
    "checks": "read",
    "issues": "write",
    "metadata": "read",
    "pull_requests": "read",
    "statuses": "read",
}


class FakeHooks:
    def __init__(
        self,
        live: dict[str, Any],
        *,
        ignore_writes: bool = False,
        events: tuple[str, ...] = ("issues", "pull_request"),
        permissions: dict[str, str] | None = None,
        selection: str = "all",
    ) -> None:
        self.live = live
        self.events = set(events)
        self.installation_body = {
            "permissions": dict(GRANTED if permissions is None else permissions),
            "repository_selection": selection,
        }
        self.sent: list[dict[str, Any]] = []
        self.ignore_writes = ignore_writes

    def get_config(self) -> dict[str, Any]:
        return dict(self.live)

    def subscribed_events(self) -> set[str]:
        return set(self.events)

    def installation(self) -> dict[str, Any]:
        return dict(self.installation_body)

    def patch_config(self, body: dict[str, Any]) -> None:
        self.sent.append(body)
        if not self.ignore_writes:
            self.live.update({k: v for k, v in body.items() if k != "secret"})


SPEC = HookSpec(url="https://api.example/api/forge/webhooks/github")
CORRECT = {"url": SPEC.url, "content_type": "json", "insecure_ssl": "0"}


def test_a_correct_hook_is_left_alone() -> None:
    hooks = FakeHooks(dict(CORRECT))
    result = converge(hooks, SPEC, secret="s", apply=True)
    assert result.changes == () and not result.wrote and hooks.sent == []


def test_a_plan_never_writes() -> None:
    hooks = FakeHooks({"url": "", "content_type": "form", "insecure_ssl": "0"})
    result = converge(hooks, SPEC, secret="s", apply=False)
    assert result.changes and not result.wrote and hooks.sent == []


def test_apply_writes_the_whole_config_with_the_secret_and_reads_it_back() -> None:
    hooks = FakeHooks({"url": "", "content_type": "form", "insecure_ssl": "0"})
    result = converge(hooks, SPEC, secret="s3cret", apply=True)
    assert result.wrote
    assert hooks.sent == [{"url": SPEC.url, "content_type": "json", "insecure_ssl": "0", "secret": "s3cret"}]


def test_a_secret_resend_writes_even_when_the_visible_fields_match() -> None:
    # GitHub never returns the secret, so a rotation cannot be detected as drift.
    hooks = FakeHooks(dict(CORRECT))
    result = converge(hooks, SPEC, secret="new", apply=True, resend_secret=True)
    assert result.wrote and hooks.sent[0]["secret"] == "new"


def test_a_write_the_read_back_does_not_show_fails() -> None:
    hooks = FakeHooks({"url": "", "content_type": "json", "insecure_ssl": "0"}, ignore_writes=True)
    with pytest.raises(HookConfigError, match="read back"):
        converge(hooks, SPEC, secret="s", apply=True)


def test_no_secret_refuses_before_any_write() -> None:
    hooks = FakeHooks({"url": "", "content_type": "json", "insecure_ssl": "0"})
    with pytest.raises(HookConfigError, match="secret"):
        converge(hooks, SPEC, secret="", apply=True)
    assert hooks.sent == []


def test_an_unsubscribed_event_is_reported_as_the_operators_step() -> None:
    hooks = FakeHooks(dict(CORRECT), events=("issues",))
    result = converge(hooks, SPEC, secret="s", apply=True)
    assert result.missing_events == ("pull_request",) and not result.wrote


def test_an_app_with_no_webhook_says_how_to_create_one(monkeypatch: pytest.MonkeyPatch, key: rsa.RSAPrivateKey) -> None:
    import requests

    class Answer:
        status_code = 404

    monkeypatch.setattr(requests, "get", lambda *a, **k: Answer())
    with pytest.raises(HookConfigError, match="Webhook > Active"):
        GitHubAppHooks(1, 2, _pem(key)).get_config()


def test_the_granted_installation_is_clean() -> None:
    result = converge(FakeHooks(dict(CORRECT)), SPEC, secret="s", apply=False)
    assert result.permission_gaps == () and result.selection_problem == ""


def test_a_pending_acceptance_is_a_missing_permission() -> None:
    # The App requests issues:write; the installation has not accepted it, so it still reads "read".
    weaker = {**GRANTED, "issues": "read"}
    result = converge(FakeHooks(dict(CORRECT), permissions=weaker), SPEC, secret="s", apply=False)
    assert result.permission_gaps == (("issues", "write", "read"),)


def test_a_permission_the_installation_lacks_entirely_is_reported_with_no_live_level() -> None:
    absent = {k: v for k, v in GRANTED.items() if k not in ("checks", "statuses")}
    result = converge(FakeHooks(dict(CORRECT), permissions=absent), SPEC, secret="s", apply=False)
    assert result.permission_gaps == (("checks", "read", None), ("statuses", "read", None))


def test_a_stronger_permission_than_required_is_not_a_gap() -> None:
    stronger = {**GRANTED, "pull_requests": "write", "checks": "admin"}
    assert installation_gaps({"permissions": stronger, "repository_selection": "all"}) == ((), "")


def test_only_select_repositories_is_reported() -> None:
    result = converge(FakeHooks(dict(CORRECT), selection="selected"), SPEC, secret="s", apply=False)
    assert result.permission_gaps == ()
    assert "selected" in result.selection_problem and "all" in result.selection_problem


def test_the_permission_check_does_not_block_the_hook_write() -> None:
    # Independent defects: a weak grant must not leave a drifted hook unwritten.
    hooks = FakeHooks({"url": "", "content_type": "json", "insecure_ssl": "0"}, permissions={})
    result = converge(hooks, SPEC, secret="s", apply=True)
    assert result.wrote and result.permission_gaps


def test_the_installation_is_read_not_the_app(monkeypatch: pytest.MonkeyPatch, key: rsa.RSAPrivateKey) -> None:
    # GET /app lists what the App REQUESTS; a pending acceptance is exactly the difference,
    # so only GET /app/installations/{id} can see it.
    import requests

    asked: list[str] = []

    class Answer:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"permissions": GRANTED, "repository_selection": "all"}

    def fake_get(url: str, **_: Any) -> Answer:
        asked.append(url)
        return Answer()

    monkeypatch.setattr(requests, "get", fake_get)
    body = GitHubAppHooks(1, 177667607, _pem(key)).installation()
    assert asked == ["https://api.github.com/app/installations/177667607"]
    assert body["repository_selection"] == "all"


def test_an_unreadable_installation_says_which_call_failed(monkeypatch: pytest.MonkeyPatch, key: rsa.RSAPrivateKey) -> None:
    import requests

    class Answer:
        status_code = 404

    monkeypatch.setattr(requests, "get", lambda *a, **k: Answer())
    with pytest.raises(HookConfigError, match=r"GET /app/installations/2 answered 404"):
        GitHubAppHooks(1, 2, _pem(key)).installation()


def test_the_required_permissions_cover_what_the_console_does() -> None:
    # ADR-066 (issues write for the outbox) and ADR-074 D7 (checks and statuses for CI state).
    assert REQUIRED_PERMISSIONS == {
        "metadata": "read",
        "issues": "write",
        "pull_requests": "read",
        "checks": "read",
        "statuses": "read",
    }


def test_the_runbook_names_every_required_permission_and_the_check() -> None:
    with open("docs/runbooks/forge-console-operations.md", encoding="utf-8") as f:
        runbook = f.read()
    for name in REQUIRED_PERMISSIONS:
        assert f"`{name}`" in runbook, name
    assert "make forge-github-hook" in runbook


def _run_command(hooks: FakeHooks, *args: str) -> Any:
    """`toolkit services forge github-hook` against a fake App, with no SOPS and no network."""
    from unittest import mock

    from typer.testing import CliRunner

    from toolkit.cli.services import app

    merged = {
        "infra": {"forge": {"github": {"app_id": 1, "installation_id": 2}}},
        "apps": {
            "platform": {"api": {"domain": "api.example", "forge_github_webhook_secret": "s"}},
            "services": {"core": {"github_app": {"private_key": "pem"}}},
        },
    }
    hooks.live.update({"url": "https://api.example/api/forge/webhooks/github"})
    with (
        mock.patch("toolkit.cli.services.ConfigurationManager") as config,
        mock.patch("toolkit.features.github_app_hook.GitHubAppHooks", return_value=hooks) as api,
    ):
        config.return_value.get_merged_config.return_value = merged
        result = CliRunner().invoke(app, ["forge", "github-hook", *args])
    api.assert_called_once_with(1, 2, "pem")
    return result


def test_the_command_exits_zero_and_says_the_grant_is_ok() -> None:
    result = _run_command(FakeHooks(dict(CORRECT)))
    assert result.exit_code == 0, result.output
    assert "grant ok" in result.output


def test_the_command_exits_nonzero_on_a_pending_acceptance() -> None:
    result = _run_command(FakeHooks(dict(CORRECT), permissions={**GRANTED, "issues": "read"}))
    assert result.exit_code == 2, result.output
    assert "permission short" in result.output and "issues needs write" in result.output
    assert "grant ok" not in result.output


def test_the_command_exits_nonzero_on_only_select_repositories() -> None:
    result = _run_command(FakeHooks(dict(CORRECT), selection="selected"))
    assert result.exit_code == 2, result.output
    assert "repository access" in result.output
    assert "grant ok" not in result.output


class _BrokenInstallation(FakeHooks):
    def installation(self) -> dict[str, Any]:
        raise HookConfigError("GET /app/installations/2 answered 404")


def test_an_unreadable_installation_does_not_stop_the_hook_converging() -> None:
    # A wrong installation_id must not leave a drifted hook unwritten, as it was fine before the check.
    hooks = _BrokenInstallation({"url": "", "content_type": "json", "insecure_ssl": "0"})
    result = converge(hooks, SPEC, secret="s", apply=True)
    assert result.wrote and hooks.sent
    assert "answered 404" in result.installation_error
    assert result.permission_gaps == () and result.selection_problem == ""


def test_the_command_exits_nonzero_when_the_grant_could_not_be_read() -> None:
    result = _run_command(_BrokenInstallation(dict(CORRECT)))
    assert result.exit_code == 2, result.output
    assert "grant not checked" in result.output and "answered 404" in result.output
    assert "grant ok" not in result.output
