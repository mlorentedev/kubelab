"""AUTH-024 (#3148): a machine account that owns a repository fails the reconcile.

ADR-065 D1 requires the bot, the reviewer and the agents' account to own nothing,
so that retiring one is a membership deletion. `_report_machine_ownership` used to
print VIOLATED and exit 0, a detector nothing downstream could act on. These tests
drive the real report (only the forge is faked) through every ending of the
command, so a call site that loses its check turns its own row red.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tests.test_gitea_repo_reconcile import _NoForgeAdmin
from toolkit.features.gitea_client import GiteaError
from toolkit.features.gitea_repos import ReconcilePlan, RepoSpec

IDENTITIES = {"bot": "hefesto", "reviewer": "mentor", "agent": "dedalo", "renovate": "proteo"}


class _Forge(_NoForgeAdmin):
    """A forge where `owned` maps a login to what it owns; `unreadable` refuses the read."""

    def __init__(self, owned: dict[str, set[str]], unreadable: frozenset[str] = frozenset()) -> None:
        self.owned = owned
        self.unreadable = unreadable

    def list_owned_repos(self, username: str) -> set[str]:
        if username in self.unreadable:
            raise GiteaError(403, "forbidden")
        return self.owned.get(username, set())


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    forge: _Forge,
    *,
    declared: bool = True,
    work: dict[str, tuple[str, ...]] | None = None,
    args: tuple[str, ...] = (),
) -> tuple[int, str]:
    import toolkit.cli.services as cli
    import toolkit.features.gitea_repos as repos

    class _Config:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def get_merged_config(self) -> dict[str, object]:
            return {"apps": {"auth": {"identities": IDENTITIES}}}

    plan = ReconcilePlan(**(work or {}))  # type: ignore[arg-type]
    monkeypatch.setattr(cli, "_gitea_clients", lambda env: (forge, None, "hefesto", "https://forge.invalid"))
    monkeypatch.setattr(cli, "ConfigurationManager", _Config)
    monkeypatch.setattr(repos, "load_declaration", lambda merged: {"personal": [RepoSpec("tool")]} if declared else {})
    monkeypatch.setattr(repos, "load_settings", lambda merged: None)
    monkeypatch.setattr(repos, "load_webhooks", lambda merged: ())
    monkeypatch.setattr(repos, "plan_reconcile", lambda *a, **k: plan)
    monkeypatch.setattr(repos, "execute", lambda *a, **k: repos.ExecutionReport())

    result = CliRunner().invoke(cli.app, ["gitea", "reconcile", *args])
    return result.exit_code, result.output


ENDINGS = [
    pytest.param({"declared": False}, id="empty declaration"),
    pytest.param({}, id="nothing to do"),
    pytest.param({"work": {"orgs_to_create": ("personal",)}}, id="plan only"),
    pytest.param({"work": {"orgs_to_create": ("personal",)}, "args": ("--apply",)}, id="after --apply"),
]


@pytest.mark.parametrize("ending", ENDINGS)
@pytest.mark.parametrize("login", sorted(IDENTITIES.values()))
def test_every_ending_fails_when_a_machine_account_owns_a_repository(
    monkeypatch: pytest.MonkeyPatch, ending: dict[str, object], login: str
) -> None:
    code, output = _invoke(monkeypatch, _Forge({login: {f"{login}/stray"}}), **ending)  # type: ignore[arg-type]

    assert code == 1, output
    assert "VIOLATED" in output


@pytest.mark.parametrize("ending", ENDINGS)
def test_every_ending_passes_when_no_machine_account_owns_anything(
    monkeypatch: pytest.MonkeyPatch, ending: dict[str, object]
) -> None:
    code, output = _invoke(monkeypatch, _Forge({}), **ending)  # type: ignore[arg-type]

    assert code == 0, output


def test_every_account_is_reported_before_the_run_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot is checked first; failing on it alone would hide the other two."""
    code, output = _invoke(monkeypatch, _Forge({"hefesto": {"hefesto/a"}, "dedalo": {"dedalo/b"}}))

    assert code == 1, output
    assert "hefesto/a" in output and "dedalo/b" in output
    assert "mentor owns: (none)" in output


def test_an_unreadable_ownership_is_unchecked_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused read means 'I did not look' (lesson-408). It must neither pass as
    'owns nothing' nor fail as a violation nobody observed."""
    code, output = _invoke(monkeypatch, _Forge({}, unreadable=frozenset({"dedalo"})))

    assert code == 0, output
    assert "AUTH-022 AC3 unchecked" in output
