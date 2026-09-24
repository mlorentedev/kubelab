"""Repository Actions secrets delivered from SOPS to the forge (TOOL-062, #1626).

Gitea resolves an unset Actions secret to an empty string, not an error, so a
workflow that reads one fails somewhere downstream that does not name the cause.
These tests pin the three things that make delivery trustworthy when the forge
itself cannot confirm any of them:

1. **What is delivered.** The catalog is the declaration, and the expected set is
   written as LITERALS for the reason `test_secret_manager_sync.py` gives: deriving
   it from `SECRET_CATALOG` would compute the expected value from the actual one
   and pass by construction (lesson-357).
2. **What the plan does.** Create what is declared and absent, never push an empty
   value, never delete, and re-push only when asked to -- the API returns neither a
   value nor an `updated_at`, so a rotation is invisible to it.
3. **That no value reaches output.** The plan carries no value at all; the only
   place one exists is the call that sends it.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.gitea_actions_secrets import (
    SecretTarget,
    delivery_targets,
    execute_actions_secrets,
    format_actions_secrets_plan,
    plan_actions_secrets,
)
from toolkit.features.secrets_manager import (
    SECRET_CATALOG,
    SecretKind,
    SecretSpec,
    forge_actions_secret_name,
    secrets_delivered_to_forge,
)

RESUME = "personal/resume"
PREFIX = "apps.services.core.gitea.actions_secrets.personal.resume"
VALUE = "1//a-refresh-token-that-must-never-be-printed"

# Every SOPS-authored value a forge repository receives as an Actions secret.
# A literal on purpose -- see the module docstring. Adding one widens what a CI
# job can read, so it costs a deliberate edit here.
EXPECTED_DELIVERED = {
    (f"{PREFIX}.gdrive_oauth_client_id", RESUME),
    (f"{PREFIX}.gdrive_oauth_client_secret", RESUME),
    (f"{PREFIX}.gdrive_oauth_refresh_token", RESUME),
    (f"{PREFIX}.gdrive_folder_id", RESUME),
}


def _t(name: str, repo: str = RESUME) -> SecretTarget:
    return SecretTarget(repo=repo, name=name.upper(), key_path=f"{PREFIX}.{name}")


# --- the declaration ----------------------------------------------------------


def test_the_delivered_set_is_exactly_what_is_declared_here() -> None:
    actual = {(s.key_path, repo) for s in secrets_delivered_to_forge() for repo in s.forge_actions}
    assert actual == EXPECTED_DELIVERED, (
        "the set of secrets pushed to forge repositories has drifted from this test. "
        "Adding one widens what a CI job can read, so it is a deliberate edit here."
    )


def test_every_delivered_secret_is_audited_in_prod() -> None:
    """The forge's credential lives in prod, and so must everything it pushes.

    A delivered secret scoped to another env would be pushed from a config the
    command never reads, and `secrets audit` would report prod complete without it.
    """
    for spec in secrets_delivered_to_forge():
        assert spec.envs == ("prod",), f"{spec.key_path} is delivered to the forge but envs={spec.envs}"


def test_every_delivered_secret_says_what_rotating_it_costs() -> None:
    """A rotation in SOPS alone leaves the forge holding the old value until a
    forced push, and nothing can detect that -- so the note has to say it."""
    for spec in secrets_delivered_to_forge():
        assert "--force" in spec.rotate_note, (
            f"{spec.key_path}: rotate_note must name the forced re-push; the forge "
            f"cannot tell a stale value from a current one."
        )


def test_no_two_delivered_secrets_share_a_name_in_one_repository() -> None:
    """The name is derived from the leaf, so two leaves can collide.

    A collision does not error on the forge: the second PUT replaces the first,
    and a workflow reads one secret's value under another's name.
    """
    seen: dict[tuple[str, str], str] = {}
    for spec in secrets_delivered_to_forge():
        for repo in spec.forge_actions:
            key = (repo, forge_actions_secret_name(spec.key_path))
            assert key not in seen, f"{spec.key_path} and {seen[key]} both deliver {key[1]} to {repo}"
            seen[key] = spec.key_path


class TestTheNameRule:
    def test_the_leaf_upper_cased_is_the_secret_name(self) -> None:
        assert forge_actions_secret_name(f"{PREFIX}.gdrive_folder_id") == "GDRIVE_FOLDER_ID"

    @pytest.mark.parametrize("leaf", ["github_token", "gitea_token", "9lives", "has-dash"])
    def test_a_name_gitea_would_refuse_is_rejected_here(self, leaf: str) -> None:
        """Gitea rejects names starting with GITHUB_/GITEA_ or a digit, and any
        character outside [A-Za-z0-9_]. Refusing at the rule turns a 400 at apply
        time into a failure at the moment the catalog entry is written."""
        with pytest.raises(ValueError):
            forge_actions_secret_name(f"a.b.{leaf}")


def test_delivery_targets_resolve_repo_name_and_path_once() -> None:
    spec = SecretSpec(
        key_path=f"{PREFIX}.gdrive_folder_id",
        description="",
        kind=SecretKind.EXTERNAL,
        forge_actions=(RESUME, "teledyne/fae-brain"),
    )
    assert delivery_targets([spec]) == (
        SecretTarget(RESUME, "GDRIVE_FOLDER_ID", spec.key_path),
        SecretTarget("teledyne/fae-brain", "GDRIVE_FOLDER_ID", spec.key_path),
    )


def test_the_catalog_itself_resolves_without_error() -> None:
    """Every real entry must pass the name rule, not just the fixtures above."""
    assert delivery_targets(SECRET_CATALOG)


# --- the plan -----------------------------------------------------------------


class TestThePlan:
    def test_declared_absent_and_valued_is_created(self) -> None:
        targets = (_t("gdrive_folder_id"),)
        plan = plan_actions_secrets(targets, live={RESUME: set()}, valued={targets[0].key_path})
        assert plan.to_create == targets
        assert not plan.is_noop

    def test_declared_and_already_present_is_left_alone(self) -> None:
        targets = (_t("gdrive_folder_id"),)
        plan = plan_actions_secrets(targets, live={RESUME: {"GDRIVE_FOLDER_ID"}}, valued={targets[0].key_path})
        assert plan.to_create == ()
        assert plan.present == targets
        assert plan.is_noop

    def test_a_missing_sops_value_is_reported_and_never_planned_for_a_write(self) -> None:
        targets = (_t("gdrive_oauth_refresh_token"),)
        plan = plan_actions_secrets(targets, live={RESUME: set()}, valued=set())
        assert plan.missing_values == targets
        assert plan.to_create == ()
        assert not plan.is_complete

    def test_a_missing_value_is_reported_even_when_the_forge_already_has_the_name(self) -> None:
        """SOPS is the source. A name on the forge with no source behind it is a
        value nobody can re-push or rotate, which is the state #1626 found."""
        targets = (_t("gdrive_folder_id"),)
        plan = plan_actions_secrets(targets, live={RESUME: {"GDRIVE_FOLDER_ID"}}, valued=set())
        assert plan.missing_values == targets
        assert not plan.is_complete

    def test_an_undeclared_live_secret_is_reported_and_never_removed(self) -> None:
        plan = plan_actions_secrets((), live={RESUME: {"LEFTOVER"}}, valued=set())
        assert plan.undeclared == ((RESUME, "LEFTOVER"),)
        assert plan.is_noop
        field_names = set(plan.__dataclass_fields__)
        assert not any("delete" in f or "remove" in f for f in field_names), field_names

    def test_a_repository_the_forge_could_not_answer_for_is_unreachable_not_empty(self) -> None:
        """`None` means the listing failed or the repository is absent. Reading it
        as "no secrets" would plan creates against a repository that is not there."""
        targets = (_t("gdrive_folder_id"),)
        plan = plan_actions_secrets(targets, live={RESUME: None}, valued={targets[0].key_path})
        assert plan.unreachable == targets
        assert plan.to_create == ()
        assert not plan.is_complete

    def test_force_rewrites_every_valued_declared_secret_and_nothing_else(self) -> None:
        valued_present, valued_absent, unvalued = _t("gdrive_folder_id"), _t("gdrive_oauth_client_id"), _t("x_y")
        plan = plan_actions_secrets(
            (valued_present, valued_absent, unvalued),
            live={RESUME: {"GDRIVE_FOLDER_ID", "X_Y"}},
            valued={valued_present.key_path, valued_absent.key_path},
            force=True,
        )
        assert plan.to_create == (valued_absent,)
        assert plan.to_overwrite == (valued_present,)
        assert plan.missing_values == (unvalued,)
        assert not plan.is_noop


# --- no value in output -------------------------------------------------------


def test_the_plan_holds_no_values_by_construction() -> None:
    """The planner is given the SET of key paths that have a value, not the
    values, so there is nothing in a plan that could leak."""
    targets = (_t("gdrive_oauth_refresh_token"),)
    plan = plan_actions_secrets(targets, live={RESUME: set()}, valued={targets[0].key_path})
    assert VALUE not in repr(plan)
    assert VALUE not in format_actions_secrets_plan(plan)


def test_the_formatted_plan_says_existence_is_not_correctness() -> None:
    targets = (_t("gdrive_folder_id"),)
    plan = plan_actions_secrets(targets, live={RESUME: {"GDRIVE_FOLDER_ID"}}, valued={targets[0].key_path})
    text = format_actions_secrets_plan(plan)
    assert "GDRIVE_FOLDER_ID" in text
    assert "--force" in text, "a present secret must be reported as unverifiable, with the way to re-push it"


# --- execution ----------------------------------------------------------------


class _FakeForge:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.fail_on = fail_on or set()

    def put_actions_secret(self, owner: str, repo: str, name: str, value: str) -> None:
        if name in self.fail_on:
            raise RuntimeError(f"Gitea API PUT /repos/{owner}/{repo}/actions/secrets/{name} -> 500")
        self.calls.append((owner, repo, name, value))


def test_execute_writes_exactly_the_planned_secrets_with_their_values() -> None:
    create, overwrite = _t("gdrive_oauth_client_id"), _t("gdrive_folder_id")
    plan = plan_actions_secrets(
        (create, overwrite),
        live={RESUME: {"GDRIVE_FOLDER_ID"}},
        valued={create.key_path, overwrite.key_path},
        force=True,
    )
    forge = _FakeForge()
    report = execute_actions_secrets(plan, forge, {create.key_path: VALUE, overwrite.key_path: "folder"}.__getitem__)
    assert forge.calls == [
        ("personal", "resume", "GDRIVE_OAUTH_CLIENT_ID", VALUE),
        ("personal", "resume", "GDRIVE_FOLDER_ID", "folder"),
    ]
    assert report.written == [create, overwrite]
    assert not report.failed


def test_a_failed_write_is_recorded_per_secret_and_the_rest_still_run() -> None:
    first, second = _t("gdrive_oauth_client_id"), _t("gdrive_folder_id")
    plan = plan_actions_secrets((first, second), live={RESUME: set()}, valued={first.key_path, second.key_path})
    forge = _FakeForge(fail_on={"GDRIVE_OAUTH_CLIENT_ID"})
    report = execute_actions_secrets(plan, forge, lambda _k: VALUE)
    assert [t for t, _ in report.failed] == [first]
    assert report.written == [second]
    assert VALUE not in repr(report)


def test_execute_never_writes_a_missing_value() -> None:
    target = _t("gdrive_oauth_refresh_token")
    plan = plan_actions_secrets((target,), live={RESUME: set()}, valued=set())
    forge = _FakeForge()
    execute_actions_secrets(plan, forge, lambda _k: "")
    assert forge.calls == []


# --- the client ---------------------------------------------------------------


class _Response:
    def __init__(self, status: int, payload: Any = None) -> None:
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.content = b"" if payload is None else b"x"
        self.text = "" if payload is None else str(payload)

    def json(self) -> Any:
        return self._payload


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append((method, url, kwargs))
        return self.response


def _client(response: _Response) -> tuple[Any, _Session]:
    from toolkit.features.gitea_client import GiteaBasicAuthClient

    client = GiteaBasicAuthClient("https://gitea.example.invalid", "manu", "pw")
    session = _Session(response)
    client.session = session  # type: ignore[assignment]
    return client, session


def test_the_value_travels_in_the_body_only() -> None:
    client, session = _client(_Response(204))
    client.put_actions_secret("personal", "resume", "GDRIVE_FOLDER_ID", VALUE)
    [(method, url, kwargs)] = session.calls
    assert method == "PUT"
    assert url.endswith("/api/v1/repos/personal/resume/actions/secrets/GDRIVE_FOLDER_ID")
    assert kwargs["json"] == {"data": VALUE}
    assert VALUE not in url


def test_listing_returns_names_only() -> None:
    client, _ = _client(_Response(200, [{"name": "GDRIVE_FOLDER_ID", "created_at": "2026-09-24T00:00:00Z"}]))
    assert client.list_actions_secret_names("personal", "resume") == {"GDRIVE_FOLDER_ID"}


def test_a_missing_repository_lists_as_none_not_as_empty() -> None:
    client, _ = _client(_Response(404, {"message": "not found"}))
    assert client.list_actions_secret_names("personal", "absent") is None


# --- the command --------------------------------------------------------------

LEAVES = ("gdrive_oauth_client_id", "gdrive_oauth_client_secret", "gdrive_oauth_refresh_token", "gdrive_folder_id")


def _merged(**values: str) -> dict[str, Any]:
    """A prod config holding the forge credential and whichever GDRIVE values are given."""
    resume = dict(values)
    return {
        "apps": {
            "services": {
                "core": {
                    "gitea": {
                        "domain": "gitea.example.invalid",
                        "admin_password": "pw",
                        "actions_secrets": {"personal": {"resume": resume}},
                    }
                }
            },
            "auth": {"identities": {"superadmin": "manu"}},
        }
    }


class _CliForge:
    def __init__(self, live: set[str] | None = None) -> None:
        self.live = set() if live is None else live
        self.puts: list[tuple[str, str, str, str]] = []

    def list_actions_secret_names(self, owner: str, name: str) -> set[str]:
        return set(self.live)

    def put_actions_secret(self, owner: str, name: str, secret_name: str, value: str) -> None:
        self.puts.append((owner, name, secret_name, value))


def _invoke(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any], forge: _CliForge, *args: str) -> Any:
    from typer.testing import CliRunner

    import toolkit.cli.services as cli

    monkeypatch.setattr(cli, "_gitea_merged_config", lambda env: config)
    monkeypatch.setattr("toolkit.features.gitea_authoring.authoring_client", lambda merged: forge)
    return CliRunner().invoke(cli.app, ["gitea", "actions-secrets", *args])


def test_plan_only_writes_nothing_and_never_prints_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    forge = _CliForge()
    result = _invoke(monkeypatch, _merged(**{leaf: VALUE for leaf in LEAVES}), forge)
    assert result.exit_code == 0, result.output
    assert forge.puts == []
    assert result.output.count("(create, from") == 4
    assert VALUE not in result.output


def test_apply_writes_all_four_and_a_second_run_has_nothing_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _merged(**{leaf: f"{VALUE}-{leaf}" for leaf in LEAVES})
    forge = _CliForge()
    result = _invoke(monkeypatch, config, forge, "--apply")
    assert result.exit_code == 0, result.output
    assert sorted(p[2] for p in forge.puts) == sorted(leaf.upper() for leaf in LEAVES)
    assert all(p[:2] == ("personal", "resume") for p in forge.puts)
    assert VALUE not in result.output

    second = _CliForge(live={leaf.upper() for leaf in LEAVES})
    rerun = _invoke(monkeypatch, config, second, "--apply")
    assert rerun.exit_code == 0, rerun.output
    assert second.puts == [], "changed=0 on re-run"


def test_force_re_pushes_what_the_forge_already_has(monkeypatch: pytest.MonkeyPatch) -> None:
    forge = _CliForge(live={leaf.upper() for leaf in LEAVES})
    result = _invoke(monkeypatch, _merged(**{leaf: VALUE for leaf in LEAVES}), forge, "--apply", "--force")
    assert result.exit_code == 0, result.output
    assert len(forge.puts) == 4


def test_a_missing_value_is_named_never_written_and_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    present = {leaf: VALUE for leaf in LEAVES if leaf != "gdrive_oauth_refresh_token"}
    forge = _CliForge()
    result = _invoke(monkeypatch, _merged(**present), forge, "--apply")
    assert result.exit_code == 1
    assert "GDRIVE_OAUTH_REFRESH_TOKEN" in result.output
    assert "GDRIVE_OAUTH_REFRESH_TOKEN" not in {p[2] for p in forge.puts}
    assert len(forge.puts) == 3, "the secrets that do have a source still land"


def test_plan_only_also_fails_when_a_value_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live state today: only the folder id is in SOPS. A plan that exits 0
    there would report a declaration that cannot be met as fine."""
    forge = _CliForge()
    result = _invoke(monkeypatch, _merged(gdrive_folder_id="folder"), forge)
    assert result.exit_code == 1
    assert result.output.count("NO VALUE") == 3


def test_a_placeholder_is_not_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.config.constants import VAULT_PLACEHOLDERS

    placeholder = sorted(VAULT_PLACEHOLDERS)[0]
    forge = _CliForge()
    result = _invoke(monkeypatch, _merged(**{leaf: placeholder for leaf in LEAVES}), forge, "--apply")
    assert result.exit_code == 1
    assert forge.puts == []


# --- review of #1816 ------------------------------------------------------------


def test_execute_refuses_a_value_that_is_empty_at_write_time() -> None:
    """The planner and the writer read SOPS at different moments. A target the plan
    says to create must still not be sent if its value is empty when written."""
    from toolkit.features.gitea_actions_secrets import ActionsSecretsPlan

    target = _t("gdrive_folder_id")
    forge = _FakeForge()
    report = execute_actions_secrets(ActionsSecretsPlan(to_create=(target,)), forge, lambda _k: "")
    assert forge.calls == []
    assert [t for t, _ in report.failed] == [target]


def test_a_forge_error_that_echoes_the_value_is_redacted_in_the_report() -> None:
    class _EchoingForge(_FakeForge):
        def put_actions_secret(self, owner: str, repo: str, name: str, value: str) -> None:
            raise RuntimeError(f"422 invalid data {value!r}")

    target = _t("gdrive_oauth_refresh_token")
    plan = plan_actions_secrets((target,), live={RESUME: set()}, valued={target.key_path})
    report = execute_actions_secrets(plan, _EchoingForge(), lambda _k: VALUE)
    assert [t for t, _ in report.failed] == [target]
    assert VALUE not in repr(report)
    assert "<redacted>" in report.failed[0][1]


def test_a_repository_the_forge_cannot_list_is_reported_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.features.gitea_client import GiteaError

    class _BrokenListing(_CliForge):
        def list_actions_secret_names(self, owner: str, name: str) -> set[str]:
            raise GiteaError("Gitea API GET /repos/personal/resume/actions/secrets -> 500: boom", 500)

    forge = _BrokenListing()
    result = _invoke(monkeypatch, _merged(**{leaf: VALUE for leaf in LEAVES}), forge, "--apply")
    assert result.exit_code == 1
    # Counted by the row marker, not the reason: Rich wraps long rows at the test
    # runner's width, so a phrase can straddle a line break.
    assert result.output.count("! personal/resume") == 4
    assert "could not list" in result.output
    assert forge.puts == []
    assert not isinstance(result.exception, GiteaError)
