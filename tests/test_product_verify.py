"""Tests for product_verify — `toolkit infra argo verify-product` (GITOPS-003 AC4, #1478).

A green job is not a deploy: eleven web releases once never reached prod while
every job was green, and a staging auto-sync that failed was never retried
(lesson-407). The check reads two consequences, the Application on the hub and
the commit web serves, and each test pins one way a "green" could be a lie.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.argo_manager import HubUnreachableError
from toolkit.features.product_verify import (
    HostUnreachableError,
    NoContractError,
    Served,
    ServedError,
    Verdict,
    classify_application,
    classify_served,
    descends_from,
    pinned_tag,
    targets_at,
    verify,
)

HEAD = "ed5747f5ecfc11306a4d34a5e0cb0f71c82a2c25"
OLDER = "4ab30833f72e6b7ec622d39dcd61715d4f933ea3"
NEWER = "9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d"


def _app(
    *,
    sync: str = "Synced",
    revision: str = HEAD,
    phase: str | None = "Succeeded",
    op_revision: str = OLDER,
    message: str = "successfully synced (all tasks run)",
    health: str = "Healthy",
) -> dict[str, Any]:
    """An Application shaped like the live `kubelab-staging` read on 2026-10-20."""
    status: dict[str, Any] = {
        "sync": {"status": sync, "revision": revision},
        "health": {"status": health},
    }
    if phase is not None:
        status["operationState"] = {
            "phase": phase,
            "message": message,
            "operation": {"sync": {"revision": op_revision}},
            "syncResult": {"revision": op_revision},
        }
    return {"metadata": {"name": "kubelab-staging"}, "status": status}


class TestClassifyApplication:
    def test_synced_at_head_with_a_succeeded_operation_is_ready(self) -> None:
        # The last operation applied an OLDER commit: master moved without
        # touching the overlay, so Argo compared HEAD, found it equal, and ran
        # nothing. Measured on the hub 2026-10-20. Requiring the operation's
        # revision to be HEAD would fail every such commit.
        state = classify_application(_app(), HEAD)
        assert state.ready and not state.failed

    def test_sync_revision_behind_head_waits(self) -> None:
        state = classify_application(_app(revision=OLDER), HEAD)
        assert not state.ready and not state.failed

    def test_out_of_sync_at_head_waits(self) -> None:
        state = classify_application(_app(sync="OutOfSync"), HEAD)
        assert not state.ready and not state.failed

    def test_a_failed_operation_at_head_fails_at_once_with_its_message(self) -> None:
        # Argo makes one automated attempt per revision: waiting for a retry
        # at HEAD is waiting for something that never comes (lesson-407).
        msg = "runtime error: invalid memory address or nil pointer dereference"
        state = classify_application(_app(sync="OutOfSync", phase="Error", op_revision=HEAD, message=msg), HEAD)
        assert state.failed
        assert msg in state.summary

    def test_an_operation_that_errored_before_any_result_is_judged_by_its_requested_revision(self) -> None:
        # A panic leaves no syncResult. An automated operation still names the
        # resolved sha it was asked for, not "HEAD": read live on both hub
        # Applications on 2026-10-21 (initiatedBy.automated, operation.sync.revision
        # equal to syncResult.revision, a 40-hex sha).
        app = _app(sync="OutOfSync", phase="Error", op_revision=HEAD, message="panic")
        del app["status"]["operationState"]["syncResult"]
        state = classify_application(app, HEAD)
        assert state.failed

    def test_a_failed_operation_at_an_older_revision_waits(self) -> None:
        # A new revision gets its own automated attempt, so a failure left over
        # from an older one is not yet this merge's verdict.
        state = classify_application(_app(sync="OutOfSync", phase="Failed", op_revision=OLDER), HEAD)
        assert not state.ready and not state.failed

    def test_a_running_operation_waits(self) -> None:
        state = classify_application(_app(phase="Running", op_revision=HEAD), HEAD)
        assert not state.ready and not state.failed

    def test_no_operation_state_waits(self) -> None:
        state = classify_application(_app(phase=None), HEAD)
        assert not state.ready and not state.failed

    def test_degraded_health_is_not_a_condition(self) -> None:
        # Staging was Degraded on 2026-10-20 by vikunja (#1783); web's own
        # health is judged by what it serves, not by the whole Application.
        assert classify_application(_app(health="Degraded"), HEAD).ready

    def test_the_summary_always_carries_the_operation_message(self) -> None:
        state = classify_application(_app(revision=OLDER, message="one or more objects failed"), HEAD)
        assert "one or more objects failed" in state.summary


class TestClassifyServed:
    def test_commit_equal_to_the_tag_minus_sha_matches(self) -> None:
        assert classify_served({"version": "1.16.0", "commit": "7ebd808"}, "sha-7ebd808")[0] is Served.MATCH

    def test_another_commit_is_a_mismatch(self) -> None:
        assert classify_served({"version": "1.16.0", "commit": "1234567"}, "sha-7ebd808")[0] is Served.MISMATCH

    def test_a_local_build_is_a_mismatch(self) -> None:
        # web reports "local" when the image was built without the build arg:
        # whatever is running, it is not the promoted image.
        assert classify_served({"version": "1.16.0", "commit": "local"}, "sha-7ebd808")[0] is Served.MISMATCH

    def test_no_commit_is_not_verifiable_never_a_match(self) -> None:
        # What staging serves until web#435 ships (measured 2026-10-20).
        assert classify_served({"version": "1.16.0"}, "sha-7ebd808")[0] is Served.ABSENT

    def test_a_semver_tag_compares_the_version(self) -> None:
        # Prod pins the released semver (ADR-046); its image is a digest
        # re-tag of a staging sha, so the commit cannot be derived from the tag.
        assert classify_served({"version": "1.16.0", "commit": "7ebd808"}, "1.16.0")[0] is Served.MATCH
        assert classify_served({"version": "1.15.2", "commit": "7ebd808"}, "1.16.0")[0] is Served.MISMATCH

    def test_a_full_length_commit_is_a_mismatch_that_names_the_convention(self) -> None:
        # Strict by design, but a producer emitting the 40-hex sha must read as a
        # convention breach, not as "another commit is running" (PR-Agent on #2579).
        full = "7ebd808" + "0" * 33
        outcome, detail = classify_served({"version": "1.16.0", "commit": full}, "sha-7ebd808")
        assert outcome is Served.MISMATCH
        assert "convention" in detail

    def test_the_detail_names_both_sides(self) -> None:
        _, detail = classify_served({"version": "1.16.0", "commit": "1234567"}, "sha-7ebd808")
        assert "1234567" in detail and "7ebd808" in detail


DEPLOYMENTS = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  template:
    spec:
      containers:
        - name: api
          image: docker.io/mlorentedev/kubelab-api:sha-7d09373
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web}
spec:
  template:
    spec:
      initContainers:
        - name: wait
          image: busybox:1.36
      containers:
        - name: web
          image: docker.io/mlorentedev/kubelab-web:sha-7ebd808
"""


class TestPinnedTag:
    def test_reads_the_tag_of_the_named_image(self) -> None:
        assert pinned_tag(DEPLOYMENTS, "kubelab-web") == "sha-7ebd808"

    def test_an_image_nowhere_in_the_overlay_raises(self) -> None:
        with pytest.raises(ValueError, match="kubelab-blog"):
            pinned_tag(DEPLOYMENTS, "kubelab-blog")

    def test_the_committed_staging_overlay_pins_web(self) -> None:
        from pathlib import Path

        import yaml

        text = Path("infra/k8s/overlays/staging/generated/deployments.yaml").read_text(encoding="utf-8")
        # The overlay pins api and web, both `sha-*`: read web's own Deployment
        # independently, or a function returning api's tag would pass (PR-Agent on #2579).
        web = next(d for d in yaml.safe_load_all(text) if d and d["metadata"]["name"] == "web")
        expected = web["spec"]["template"]["spec"]["containers"][0]["image"].rsplit(":", 1)[1]
        assert pinned_tag(text, "kubelab-web") == expected


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _run(
    apps: list[Any],
    served: list[Any],
    timeout: float = 30,
    tag: str = "sha-7ebd808",
    tags_at: dict[str, Any] | None = None,
):
    """Run verify() against scripted answers; the last answer repeats.

    ``tags_at`` maps a revision newer than HEAD to the tag it pins (or an
    exception to raise); a revision absent from it does not descend from HEAD.
    """
    clock = FakeClock()
    tags_at = tags_at or {}

    def tag_at(rev: str) -> str:
        item = tags_at[rev]
        if isinstance(item, Exception):
            raise item
        return item

    def answer(script: list[Any]):
        def call() -> Any:
            item = script.pop(0) if len(script) > 1 else script[0]
            if isinstance(item, Exception):
                raise item
            return item

        return call

    return verify(
        head=HEAD,
        tag=tag,
        read_app=answer(apps),
        fetch_served=answer(served),
        descends=lambda rev: rev in tags_at,
        tag_at=tag_at,
        timeout=timeout,
        poll=10,
        now=clock.now,
        sleep=clock.sleep,
    )


SERVED_OK = {"version": "1.16.0", "commit": "7ebd808"}


class TestVerify:
    def test_ready_and_serving_the_tag_is_verified(self) -> None:
        verdict, _ = _run([_app()], [SERVED_OK])
        assert verdict is Verdict.VERIFIED

    def test_waits_for_the_sync_then_for_the_rollout(self) -> None:
        old = {"version": "1.16.0", "commit": "1234567"}
        verdict, _ = _run([_app(revision=OLDER), _app()], [old, SERVED_OK])
        assert verdict is Verdict.VERIFIED

    def test_a_failed_operation_at_head_is_red_before_the_deadline(self) -> None:
        msg = "one or more synchronization tasks are not valid"
        verdict, lines = _run([_app(sync="OutOfSync", phase="Failed", op_revision=HEAD, message=msg)], [SERVED_OK])
        assert verdict is Verdict.FAILED
        assert any(msg in line for line in lines)
        # The deadline path also ends FAILED with the message; only this one
        # returns without waiting and names the manual re-sync.
        assert not any("deadline" in line for line in lines)
        assert any("make sync-app" in line for line in lines)

    def test_never_synced_at_head_is_red_at_the_deadline_with_the_message(self) -> None:
        msg = "Skipping auto-sync: failed previous sync attempt"
        verdict, lines = _run([_app(revision=OLDER, message=msg)], [SERVED_OK])
        assert verdict is Verdict.FAILED
        assert any(msg in line for line in lines)

    def test_serving_another_commit_at_the_deadline_is_red(self) -> None:
        verdict, lines = _run([_app()], [{"version": "1.16.0", "commit": "1234567"}])
        assert verdict is Verdict.FAILED
        assert any("1234567" in line for line in lines)

    def test_no_commit_at_the_deadline_is_not_verifiable(self) -> None:
        verdict, _ = _run([_app()], [{"version": "1.16.0"}])
        assert verdict is Verdict.NOT_VERIFIABLE

    def test_no_commit_during_a_rollout_keeps_waiting(self) -> None:
        # The old pod may answer without `commit` while the new one rolls out.
        verdict, _ = _run([_app()], [{"version": "1.16.0"}, SERVED_OK])
        assert verdict is Verdict.VERIFIED

    def test_an_unreachable_hub_at_the_deadline_cannot_check(self) -> None:
        verdict, _ = _run([HubUnreachableError("dial tcp: i/o timeout")], [SERVED_OK])
        assert verdict is Verdict.CANNOT_CHECK

    def test_an_unreachable_host_at_the_deadline_cannot_check(self) -> None:
        verdict, _ = _run([_app()], [HostUnreachableError("no such host")])
        assert verdict is Verdict.CANNOT_CHECK

    def test_an_http_error_at_the_deadline_is_red(self) -> None:
        # The host answered, and what it answered is not the promoted web.
        verdict, _ = _run([_app()], [ServedError("HTTP 404 text/html")])
        assert verdict is Verdict.FAILED

    def test_the_host_is_not_read_before_the_sync_is_ready(self) -> None:
        # Matching the served commit while Argo is still on an older revision
        # would verify the previous deploy, not this merge.
        calls: list[str] = []

        def fetch() -> dict[str, str]:
            calls.append("fetch")
            return SERVED_OK

        clock = FakeClock()
        verdict, _ = verify(
            head=HEAD,
            tag="sha-7ebd808",
            read_app=lambda: _app(revision=OLDER),
            fetch_served=fetch,
            descends=lambda rev: False,
            tag_at=lambda rev: "sha-7ebd808",
            timeout=30,
            poll=10,
            now=clock.now,
            sleep=clock.sleep,
        )
        assert verdict is Verdict.FAILED
        assert calls == []

    def test_exit_codes_are_stable(self) -> None:
        # Makefile and runbook callers branch on these numbers.
        assert [v.value for v in Verdict] == [0, 1, 2, 3, 4]


class TestMasterMovesDuringThePoll:
    """GITOPS-007 (#2584): HEAD is read once, and another merge may land while the check polls."""

    def test_a_newer_commit_pinning_the_same_tag_still_verifies_the_promotion(self) -> None:
        # B landed and Argo synced it, but B did not touch this app's pin:
        # what HEAD promised is what B serves.
        verdict, lines = _run([_app(revision=NEWER, op_revision=NEWER)], [SERVED_OK], tags_at={NEWER: "sha-7ebd808"})
        assert verdict is Verdict.VERIFIED, lines

    def test_a_newer_commit_pinning_another_tag_supersedes_the_promotion(self) -> None:
        served: list[Any] = []

        def fetch() -> Any:
            served.append(1)
            return SERVED_OK

        clock = FakeClock()
        verdict, lines = verify(
            head=HEAD,
            tag="sha-7ebd808",
            read_app=lambda: _app(revision=NEWER, op_revision=NEWER, message="pre-sync hook ran"),
            fetch_served=fetch,
            descends=lambda rev: rev == NEWER,
            tag_at=lambda rev: "sha-1111111",
            timeout=30,
            poll=10,
            now=clock.now,
            sleep=clock.sleep,
        )
        # Neither a pass under B's tag nor a red: the promotion can no longer be observed.
        assert verdict is Verdict.SUPERSEDED
        assert served == [] and clock.t == 0
        assert any("sha-1111111" in line and "sha-7ebd808" in line for line in lines)
        # Like every other non-zero exit, it carries the operation message.
        assert any("pre-sync hook ran" in line for line in lines)

    def test_a_failed_operation_at_an_accepted_newer_commit_is_red_at_once(self) -> None:
        app = _app(sync="OutOfSync", revision=NEWER, phase="Failed", op_revision=NEWER, message="hook failed")
        verdict, lines = _run([app], [SERVED_OK], tags_at={NEWER: "sha-7ebd808"})
        assert verdict is Verdict.FAILED
        assert not any("deadline" in line for line in lines)

    def test_an_older_sync_revision_still_waits(self) -> None:
        # OLDER does not descend from HEAD: the merge has not been synced yet.
        verdict, lines = _run([_app(revision=OLDER)], [SERVED_OK], tags_at={NEWER: "sha-7ebd808"})
        assert verdict is Verdict.FAILED
        assert any("deadline" in line for line in lines)

    def test_an_unreadable_newer_pin_cannot_check(self) -> None:
        verdict, _ = _run([_app(revision=NEWER, op_revision=NEWER)], [SERVED_OK], tags_at={NEWER: ValueError("gone")})
        assert verdict is Verdict.CANNOT_CHECK

    def test_a_contract_removed_at_the_newer_commit_cannot_check(self) -> None:
        gone = NoContractError("'web' has no product contract")
        verdict, _ = _run([_app(revision=NEWER, op_revision=NEWER)], [SERVED_OK], tags_at={NEWER: gone})
        assert verdict is Verdict.CANNOT_CHECK

    def test_a_reader_bug_is_not_reported_as_an_unreadable_pin(self) -> None:
        # Only the pin read is a "could not be read"; a KeyError from reading the
        # Application is a bug, and polling to the deadline would hide it.
        with pytest.raises(KeyError):
            _run([KeyError("status")], [SERVED_OK], tags_at={NEWER: "sha-7ebd808"})


class TestDescendsFrom:
    @pytest.fixture
    def repo(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        import subprocess

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout

        git("init", "-q", "-b", "master")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "a")
        a = git("rev-parse", "HEAD").strip()
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "b")
        b = git("rev-parse", "HEAD").strip()
        monkeypatch.chdir(tmp_path)
        return a, b

    def test_a_child_descends_from_its_parent(self, repo) -> None:
        a, b = repo
        assert descends_from(a, b)

    def test_a_parent_does_not_descend_from_its_child(self, repo) -> None:
        a, b = repo
        assert not descends_from(b, a)

    def test_a_commit_does_not_descend_from_itself(self, repo) -> None:
        a, _ = repo
        assert not descends_from(a, a)

    def test_an_unknown_revision_does_not_descend(self, repo) -> None:
        a, _ = repo
        assert not descends_from(a, "f" * 40)

    def test_fetch_makes_a_commit_merged_while_polling_known(self, repo, tmp_path, monkeypatch) -> None:
        # The check runs from a checkout; the commit Argo synced landed on origin
        # after the check started, so it is unknown until fetched.
        import subprocess

        _, b = repo
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", "-q", str(tmp_path), str(clone)], check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c"],
            cwd=tmp_path,
            check=True,
        )
        c = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
        monkeypatch.chdir(clone)
        assert not descends_from(b, c)
        assert descends_from(b, c, fetch=True)


class TestTargetsAt:
    @staticmethod
    def _show_worktree(seen: list[tuple[str, str]]):
        from pathlib import Path

        def show(rev: str, path: str) -> str:
            seen.append((rev, path))
            return Path(path).read_text(encoding="utf-8")

        return show

    def test_the_url_is_the_contract_hostname_and_the_tag_the_overlay_pin(self) -> None:
        seen: list[tuple[str, str]] = []
        tag, url = targets_at(HEAD, "web", "staging", self._show_worktree(seen))
        assert tag.startswith("sha-")
        # Mirrors `hostnames.staging` in infra/config/products/contracts/web.yaml: a
        # literal keeps the assertion from being circular; a hostname rename edits both.
        assert url == "https://staging.mlorente.dev/version.json"
        assert "infra/config/products/contracts/web.yaml" in {path for _, path in seen}
        assert not any(path.startswith("infra/config/values/") for _, path in seen)

    def test_prod_reads_the_prod_snapshot_not_the_staging_one(self) -> None:
        """Prod runs the release's contract; the flat snapshot is what staging was last given."""
        seen: list[tuple[str, str]] = []
        _, url = targets_at(HEAD, "web", "prod", self._show_worktree(seen))
        # Mirrors `hostnames.prod` in infra/config/products/contracts/prod/web.yaml.
        assert url == "https://mlorente.dev/version.json"
        contracts = {path for _, path in seen if "/contracts/" in path}
        assert contracts == {"infra/config/products/contracts/prod/web.yaml"}

    def test_every_file_is_read_at_the_given_revision(self) -> None:
        seen: list[tuple[str, str]] = []
        targets_at(HEAD, "web", "prod", self._show_worktree(seen))
        assert {rev for rev, _ in seen} == {HEAD}

    def test_an_in_tree_product_is_refused(self) -> None:
        # api has no contract (ADR-048): nothing declares its hostname.
        with pytest.raises(NoContractError, match="api"):
            targets_at(HEAD, "api", "staging", self._show_worktree([]))

    def test_an_unregistered_product_is_refused(self) -> None:
        with pytest.raises(NoContractError, match="blog"):
            targets_at(HEAD, "blog", "staging", self._show_worktree([]))
