"""Unregistering a spoke must not prune it, and must not disarm the other hub.

The old `make unregister-spoke ENV=x` was written when there was exactly one
hub. Two exist during the AWS->GCP migration, and in that world it does two
dangerous things and omits a third:

    kubectl delete secret cluster-$(ENV) -n argocd --kubeconfig $(HUB_KUBECONFIG)
    kubectl delete -f infra/k8s/argocd/spoke-rbac.yaml --kubeconfig $(KUBECONFIG_PATH)

1. `HUB_KUBECONFIG` is a single global default. It now resolves to gcp1 -- the
   hub being migrated TO -- so `unregister-spoke ENV=staging`, run to detach
   aws1, would delete the credential of the hub you are keeping.

2. `spoke-rbac.yaml` lives on the SPOKE and is shared by every hub that
   reconciles it. Deleting it to detach one hub revokes the other hub's access
   at the same time.

3. It never removes the Application. A hub left holding an Application whose
   cluster secret is gone reports `Unknown` and fires `on-sync-failed` forever
   -- which is precisely the state gcp1 was found in on 2026-08-22.

And the obvious correction is itself a trap: an Argo CD Application carries
`resources-finalizer.argocd.argoproj.io`, so deleting it CASCADES and prunes
every resource it manages. Measured on aws1's live Application:

    finalizers: ["resources-finalizer.argocd.argoproj.io"]
    syncPolicy: {"automated":{"prune":true,"selfHeal":false}}

Deleting that without stripping the finalizer first would have destroyed the
entire staging namespace -- api, web, authelia, grafana, loki, n8n -- while
"detaching a hub".

So the order is load-bearing, and it is what these tests pin.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from toolkit.features import spoke_unregistration as su

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"
HUB = Path("/tmp/aws1.kubeconfig")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record every kubectl argv instead of running it."""
    recorded: list[list[str]] = []

    def fake(argv: list[str]) -> tuple[int, str]:
        recorded.append(list(argv))
        return 0, ""

    monkeypatch.setattr(su, "_kubectl", fake)
    return recorded


def _joined(calls: list[list[str]]) -> list[str]:
    return [" ".join(c) for c in calls]


class TestTheApplicationIsDefusedBeforeItIsDeleted:
    def test_the_finalizer_is_stripped_first(self, calls: list[list[str]]) -> None:
        """Order is the whole safety property, not a detail.

        Delete-then-patch is delete, and delete with this finalizer prunes the
        spoke. There is no undo for that.
        """
        su.unregister_spoke("staging", HUB)
        joined = _joined(calls)

        patch_at = next(i for i, c in enumerate(joined) if "patch" in c and "finalizers" in c)
        delete_at = next(i for i, c in enumerate(joined) if "delete application" in c)
        assert patch_at < delete_at, (
            "the Application is deleted before its finalizer is stripped. "
            "`resources-finalizer.argocd.argoproj.io` makes that a CASCADE: every "
            "resource the Application manages is pruned from the spoke."
        )

    def test_the_finalizer_patch_actually_empties_it(self, calls: list[list[str]]) -> None:
        joined = " ".join(_joined(calls) or [""])
        su.unregister_spoke("staging", HUB)
        joined = " ".join(_joined(calls))
        assert '"finalizers":[]' in joined.replace(" ", ""), (
            "the patch does not empty the finalizer list, so the cascade still fires"
        )

    def test_the_application_named_is_the_env_one(self, calls: list[list[str]]) -> None:
        su.unregister_spoke("staging", HUB)
        joined = " ".join(_joined(calls))
        assert "kubelab-staging" in joined
        assert "kubelab-prod" not in joined, "it touched an environment it was not asked about"


class TestTheOtherHubIsLeftArmed:
    def test_shared_spoke_rbac_is_not_deleted_by_default(self, calls: list[list[str]]) -> None:
        """The RBAC lives on the SPOKE and every hub reconciling it depends on it."""
        su.unregister_spoke("staging", HUB)
        joined = " ".join(_joined(calls))
        assert "spoke-rbac" not in joined, (
            "the shared spoke RBAC was deleted. It lives on the spoke cluster and is "
            "used by EVERY hub that reconciles it, so removing it to detach one hub "
            "revokes the other hub's access too."
        )

    def test_removing_the_rbac_is_possible_but_must_be_asked_for(self, calls: list[list[str]]) -> None:
        """Legitimate only when the LAST hub detaches -- so it is opt-in, never default."""
        su.unregister_spoke("staging", HUB, remove_shared_rbac=True)
        joined = " ".join(_joined(calls))
        assert "spoke-rbac" in joined, "the opt-in flag did nothing"

    def test_every_call_targets_the_hub_it_was_given(self, calls: list[list[str]]) -> None:
        """No global default. Two hubs exist; the caller must say which."""
        su.unregister_spoke("staging", HUB)
        for call in calls:
            if "--kubeconfig" not in call:
                continue
            kubeconfig = call[call.index("--kubeconfig") + 1]
            # Hub-side calls must name the hub given. Spoke-side calls are only
            # produced by the opt-in flag, which this case does not set.
            assert kubeconfig == str(HUB), f"a call targeted {kubeconfig!r} instead of the hub given: {call}"


class TestDryRunTouchesNothing:
    def test_dry_run_performs_no_kubectl_write(self, calls: list[list[str]]) -> None:
        plan = su.unregister_spoke("staging", HUB, dry_run=True)
        writes = [c for c in _joined(calls) if " delete " in f" {c} " or " patch " in f" {c} "]
        assert not writes, f"dry-run performed writes: {writes}"
        assert plan, "dry-run returned no plan, so there is nothing to review before running it"


class TestTheMakefileNoLongerCarriesTheFootgun:
    def test_it_does_not_delete_shared_rbac_inline(self) -> None:
        recipe = _recipe("unregister-spoke")
        assert "spoke-rbac.yaml" not in recipe, (
            "the recipe still deletes the shared spoke RBAC, which disarms every "
            "other hub reconciling that spoke"
        )

    def test_the_kubeconfig_argument_is_the_explicit_hub(self) -> None:
        """The VALUE passed to --kubeconfig, not merely that `$(HUB)` appears somewhere.

        The first version asserted `"$(HUB)" in recipe`, and a mutation that
        swapped the argument back to `$(HUB_KUBECONFIG)` stayed green: `$(HUB)`
        still occurs in the usage message. Third time this session that a text
        scan matched an adjacent occurrence instead of the load-bearing one
        (lesson-363). The property is which variable reaches `--kubeconfig`.
        """
        recipe = _recipe("unregister-spoke")
        match = re.search(r"--kubeconfig\s+(\S+)", recipe)
        assert match, "the recipe passes no --kubeconfig at all"
        assert match.group(1) == "$(HUB)", (
            f"--kubeconfig receives {match.group(1)!r}. With two hubs live, a global "
            "default points at the one being migrated TO -- so detaching the old hub "
            "would delete the new hub's credential."
        )

    def test_the_hub_argument_is_mandatory(self) -> None:
        """A guard clause, so omitting HUB fails fast instead of picking a hub for you."""
        recipe = _recipe("unregister-spoke")
        assert re.search(r"test -n \"\$\(HUB\)\"", recipe), (
            "nothing refuses an empty HUB, so `make unregister-spoke ENV=staging` "
            "would run against whatever --kubeconfig resolves to"
        )

    def test_it_delegates_to_the_toolkit(self) -> None:
        recipe = _recipe("unregister-spoke")
        assert "infra argo unregister-spoke" in recipe


def _recipe(target: str) -> str:
    lines = MAKEFILE.read_text().splitlines()
    out: list[str] = []
    collecting = False
    for line in lines:
        if line.startswith(f"{target}:"):
            collecting = True
            continue
        if collecting:
            if line and not line.startswith("\t"):
                break
            out.append(line)
    assert out, f"target {target!r} not found in the Makefile"
    return "\n".join(out)
