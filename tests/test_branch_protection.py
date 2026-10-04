"""Branch protection is reconciled from a declaration, and the write does not clear what it omits.

The defect this file guards is not "the setting is wrong". It is that GitHub's
`PUT /repos/{o}/{r}/branches/{b}/protection` is a **whole-object replace** that
answers 200 to a partial body and silently resets everything the body left out.
`master` carries `enforce_admins: true`; a naive write of just the status checks
turns that off and reports success.

So the tests below are mostly about what the PUT body *carries* rather than what
it *changes*, and about the post-condition being re-read rather than assumed —
the `gitea_repos.ensure_settings` argument (TOOL-063, #1633) with a sharper edge,
because there an unapplied field stayed as it was and here it is cleared.

The last test is a different question: a required context is matched by NAME, and
a name that never reports blocks every merge on the branch forever. So the
declaration is checked against the workflows that would have to produce it.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from toolkit.features.branch_protection import (
    BranchProtectionError,
    DeclaredProtection,
    ensure_protection,
    load_declared,
    protection_changes,
    put_body,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMON_YAML = REPO_ROOT / "infra/config/values/common.yaml"
WORKFLOWS = REPO_ROOT / ".github/workflows"


def live_object(**overrides: Any) -> dict[str, Any]:
    """The shape GitHub actually returns, taken from the real master read."""
    base: dict[str, Any] = {
        "url": "https://api.github.com/repos/o/r/branches/master/protection",
        "required_status_checks": {
            "url": "https://api.github.com/…/required_status_checks",
            "strict": True,
            "contexts": ["Validate", "Detect Changes", "review-attestation"],
            "contexts_url": "https://api.github.com/…/contexts",
            "checks": [{"context": "Validate", "app_id": 15368}],
        },
        "required_pull_request_reviews": {
            "url": "https://api.github.com/…/required_pull_request_reviews",
            "dismiss_stale_reviews": False,
            "require_code_owner_reviews": False,
            "require_last_push_approval": False,
            "required_approving_review_count": 0,
        },
        "required_signatures": {"url": "https://api.github.com/…", "enabled": False},
        "enforce_admins": {"url": "https://api.github.com/…", "enabled": True},
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "block_creations": {"enabled": False},
        "required_conversation_resolution": {"enabled": False},
        "lock_branch": {"enabled": False},
        "allow_fork_syncing": {"enabled": False},
    }
    base.update(overrides)
    return base


DECLARED = DeclaredProtection(
    strict=False,
    required_contexts=("Validate", "Detect Changes", "review-attestation", "Tests"),
)


class FakeClient:
    """Records the PUT body and answers the second GET with what was written.

    It applies the body the way the API does — whole-object replace — rather than
    echoing the request. A fake that merges instead of replacing would encode the
    belief under test and certify it (lesson 415).
    """

    def __init__(self, live: dict[str, Any] | None) -> None:
        self.state = live
        self.puts: list[dict[str, Any]] = []

    def get_protection(self, branch: str) -> dict[str, Any] | None:
        return self.state

    def put_protection(self, branch: str, body: dict[str, Any]) -> None:
        self.puts.append(body)
        self.state = {
            "required_status_checks": {
                "strict": body["required_status_checks"]["strict"],
                "contexts": list(body["required_status_checks"]["contexts"]),
            },
            "enforce_admins": {"enabled": bool(body.get("enforce_admins"))},
            "required_pull_request_reviews": body.get("required_pull_request_reviews"),
            "required_linear_history": {"enabled": bool(body.get("required_linear_history"))},
            "allow_force_pushes": {"enabled": bool(body.get("allow_force_pushes"))},
            "allow_deletions": {"enabled": bool(body.get("allow_deletions"))},
            "block_creations": {"enabled": bool(body.get("block_creations"))},
            "required_conversation_resolution": {"enabled": bool(body.get("required_conversation_resolution"))},
            "lock_branch": {"enabled": bool(body.get("lock_branch"))},
            "allow_fork_syncing": {"enabled": bool(body.get("allow_fork_syncing"))},
        }


class TestThePutBodyCarriesWhatTheDeclarationOmits:
    """The trap: a partial body is accepted, and clears the rest."""

    def test_enforce_admins_survives_a_declaration_that_never_mentions_it(self) -> None:
        body = put_body(live_object(), DECLARED)
        assert body["enforce_admins"] is True, (
            "the PUT body dropped enforce_admins. GitHub's PUT is a whole-object replace: "
            "a body without this field turns admin enforcement OFF on master and answers 200."
        )

    def test_every_writable_field_is_present_even_when_undeclared(self) -> None:
        body = put_body(live_object(), DECLARED)
        for field in (
            "enforce_admins",
            "required_linear_history",
            "allow_force_pushes",
            "allow_deletions",
            "block_creations",
            "required_conversation_resolution",
            "lock_branch",
            "allow_fork_syncing",
            "required_pull_request_reviews",
            "restrictions",
        ):
            assert field in body, f"{field} would be cleared by this PUT"

    def test_enabled_objects_become_bare_booleans(self) -> None:
        """GET answers `{"enabled": true}`; PUT wants `true`. Feeding one to the other fails."""
        body = put_body(live_object(), DECLARED)
        assert body["required_linear_history"] is True
        assert body["allow_force_pushes"] is False
        assert not isinstance(body["enforce_admins"], dict)

    def test_read_only_fields_are_not_sent_back(self) -> None:
        body = put_body(live_object(), DECLARED)
        assert "required_signatures" not in body, "required_signatures has its own endpoint; the PUT rejects it"
        assert "url" not in body
        assert "url" not in body["required_pull_request_reviews"]

    def test_absent_restrictions_are_an_explicit_null_not_an_omission(self) -> None:
        body = put_body(live_object(), DECLARED)
        assert body["restrictions"] is None
        assert "restrictions" in body

    def test_the_declaration_is_what_lands_in_the_status_checks(self) -> None:
        body = put_body(live_object(), DECLARED)
        assert body["required_status_checks"]["strict"] is False
        assert "Tests" in body["required_status_checks"]["contexts"]


class TestTheChangeSetIsOnePredicate:
    def test_a_matching_branch_reports_no_changes(self) -> None:
        live = live_object(
            required_status_checks={"strict": False, "contexts": list(DECLARED.required_contexts)},
        )
        assert protection_changes(live, DECLARED) == []

    def test_strict_and_contexts_are_reported_separately(self) -> None:
        fields = [field for field, _, _ in protection_changes(live_object(), DECLARED)]
        assert fields == ["required_status_checks.strict", "required_status_checks.contexts"]

    def test_context_order_is_not_a_difference(self) -> None:
        live = live_object(
            required_status_checks={"strict": False, "contexts": list(reversed(DECLARED.required_contexts))},
        )
        assert protection_changes(live, DECLARED) == []


class TestEnsureReadsBackRatherThanTrustingThe200:
    def test_an_agreeing_branch_is_not_written_at_all(self) -> None:
        client = FakeClient(
            live_object(required_status_checks={"strict": False, "contexts": list(DECLARED.required_contexts)})
        )
        assert ensure_protection(client, "master", DECLARED) == []
        assert client.puts == [], "a converged branch must not be written — that is what makes a re-run changed=0"

    def test_applying_twice_writes_once(self) -> None:
        client = FakeClient(live_object())
        first = ensure_protection(client, "master", DECLARED)
        second = ensure_protection(client, "master", DECLARED)
        assert first and second == []
        assert len(client.puts) == 1

    def test_a_write_that_did_not_take_is_raised_not_reported_as_success(self) -> None:
        class LyingClient(FakeClient):
            def put_protection(self, branch: str, body: dict[str, Any]) -> None:
                self.puts.append(body)  # accepted, and nothing changes — the 200 that means nothing

        client = LyingClient(live_object())
        with pytest.raises(BranchProtectionError, match="still disagrees after a PUT that returned success"):
            ensure_protection(client, "master", DECLARED)

    def test_an_unprotected_branch_is_refused_rather_than_created(self) -> None:
        with pytest.raises(BranchProtectionError, match="not protected at all"):
            ensure_protection(FakeClient(None), "master", DECLARED)

    def test_enforce_admins_lost_as_a_side_effect_is_caught(self) -> None:
        """The failure this module exists for, asserted rather than assumed."""

        class ClearingClient(FakeClient):
            def put_protection(self, branch: str, body: dict[str, Any]) -> None:
                stripped = dict(body)
                stripped.pop("enforce_admins", None)  # what a partial body does
                super().put_protection(branch, stripped)

        client = ClearingClient(live_object())
        with pytest.raises(BranchProtectionError, match="enforce_admins"):
            ensure_protection(client, "master", DECLARED)


class TestTheDeclaration:
    def test_strict_must_be_stated_not_defaulted(self) -> None:
        with pytest.raises(BranchProtectionError, match="declared explicitly"):
            DeclaredProtection.from_config({"required_contexts": ["Validate"]})

    def test_the_real_common_yaml_declares_master_for_each_repository(self) -> None:
        config = yaml.safe_load(COMMON_YAML.read_text(encoding="utf-8"))
        declared = load_declared(config)
        assert set(declared) == {"mlorentedev/kubelab", "mlorentedev/web"}
        for repo, branches in declared.items():
            assert "master" in branches, f"{repo}: master is the branch this repository reconciles"
            assert branches["master"].required_contexts, "an empty context list matches nothing and requires nothing"

    def test_web_declares_what_its_adr_057_records(self) -> None:
        """web's values live in web's ADR-057; this entry is the one place they are reconciled.

        Pinned here so an edit to either side is a visible diff, not a quiet
        disagreement between the ADR and what the check enforces.
        """
        config = yaml.safe_load(COMMON_YAML.read_text(encoding="utf-8"))
        web = load_declared(config)["mlorentedev/web"]["master"]
        assert web.strict is False
        assert sorted(web.required_contexts) == ["GitGuardian Security Checks", "PR gate"]

    def test_the_old_branch_keyed_shape_is_refused_not_read_as_kubelab(self) -> None:
        """Before #374 on web, `ci.branch_protection.<branch>` was implicitly kubelab's.

        Reading that shape now would attribute it to whichever repository was
        asked about, which is the defect the re-key removes. It fails instead.
        """
        old = {"ci": {"branch_protection": {"master": {"strict": False, "required_contexts": ["Tests"]}}}}
        with pytest.raises(BranchProtectionError, match="keyed by repository"):
            load_declared(old)

    def test_a_repository_key_must_be_owner_slash_name(self) -> None:
        for key in ("kubelab", "a/b/c"):
            bad = {"ci": {"branch_protection": {key: {"master": {"strict": False, "required_contexts": ["x"]}}}}}
            with pytest.raises(BranchProtectionError, match="not a repository"):
                load_declared(bad)

    def test_every_required_context_is_produced_by_a_workflow(self) -> None:
        """A required context that never reports blocks every merge on the branch, forever.

        Matching is by name, so a typo or a renamed job is indistinguishable from a
        check that has not run yet — the branch simply never becomes mergeable. The
        names are therefore checked against the workflows that must produce them:
        a job `name:` for a check-run, or a literal in the file that publishes a
        commit status.
        """
        config = yaml.safe_load(COMMON_YAML.read_text(encoding="utf-8"))
        # kubelab's own entry only: web's contexts are produced by web's
        # workflows and by an app, neither of which is visible from this tree.
        declared = load_declared(config)["mlorentedev/kubelab"]["master"]

        job_names: set[str] = set()
        for path in WORKFLOWS.glob("*.yml"):
            content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for job_id, job in (content.get("jobs") or {}).items():
                job_names.add(job.get("name") or job_id if isinstance(job, dict) else job_id)

        raw_text = "\n".join(p.read_text(encoding="utf-8") for p in WORKFLOWS.glob("*.yml"))

        unproduced = [
            context for context in declared.required_contexts if context not in job_names and context not in raw_text
        ]
        assert not unproduced, (
            f"no workflow produces these required contexts: {unproduced}. A required context is "
            f"matched by name; one that never reports leaves master permanently unmergeable."
        )


class TestTheCommandComparesEachRepositoryWithItsOwnEntry:
    """`--repo` used to change only the target, against kubelab's one declaration.

    Pointed at web, it compared web with kubelab's required contexts and called
    the difference drift. Each repository is now read against its own entry, an
    undeclared one is refused, and `--all` walks every entry.
    """

    CONFIG = {
        "ci": {
            "branch_protection": {
                "o/one": {"master": {"strict": False, "required_contexts": ["A"]}},
                "o/two": {"master": {"strict": False, "required_contexts": ["B"]}},
            }
        }
    }

    def _run(self, monkeypatch: pytest.MonkeyPatch, live: dict[str, dict[str, Any]], *args: str) -> tuple[Any, list[str]]:
        from typer.testing import CliRunner

        from toolkit.cli import tools as cli

        asked: list[str] = []

        class Config:
            def __init__(self, *_: Any) -> None:
                pass

            def get_merged_config(self) -> dict[str, Any]:
                return TestTheCommandComparesEachRepositoryWithItsOwnEntry.CONFIG

        class Client(FakeClient):
            def __init__(self, repo: str) -> None:
                super().__init__(live[repo])
                asked.append(repo)

        monkeypatch.setattr("toolkit.features.configuration.ConfigurationManager", Config)
        monkeypatch.setattr("toolkit.features.branch_protection.GitHubBranchProtectionClient", Client)
        return CliRunner().invoke(cli.app, ["branch-protection", *args]), asked

    @staticmethod
    def _live(*contexts: str) -> dict[str, Any]:
        obj = live_object()
        obj["required_status_checks"] = {**obj["required_status_checks"], "strict": False, "contexts": list(contexts)}
        return obj

    def test_each_repository_is_checked_against_its_own_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        live = {"o/one": self._live("A"), "o/two": self._live("B")}
        result, asked = self._run(monkeypatch, live, "--check", "--all")
        assert result.exit_code == 0, result.output
        assert asked == ["o/one", "o/two"]

    def test_drift_in_one_repository_fails_the_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        live = {"o/one": self._live("A"), "o/two": self._live("A")}
        result, _ = self._run(monkeypatch, live, "--check", "--repo", "o/two")
        assert result.exit_code == 1

    def test_an_undeclared_repository_is_refused_not_compared_with_another_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live = {"o/one": self._live("A")}
        result, asked = self._run(monkeypatch, live, "--check", "--repo", "o/three")
        assert result.exit_code == 1
        assert asked == [], "nothing may be read for a repository with no entry"
