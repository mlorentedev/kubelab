"""#1583: retiring an alert rule takes two operations, and the repo only did one.

Deleting a rule's provisioning file removes it from the ConfigMap and from the
pod's disk. It does NOT remove the rule -- Grafana keeps it in its own database
and goes on evaluating it. Measured on both clusters on 2026-09-04, ten days
after #1529 deleted `security-rules.yaml` and two days after prod's pod restarted
without it, `obs015-crowdsec-ban-surge` was still querying Loki and still sending
to the notifier.

Nothing in the repo showed it. The file was gone, the rendered ConfigMap was
clean, Argo CD reported Synced/Healthy, and the alert kept arriving in Slack.

`deleted-rules.yaml` performs the second operation. These assertions exist so
that the two halves cannot drift apart again: a uid may not be both declared and
deleted, the retirement that started this must stay declared, and -- because a
generator entry is exactly the thing that can be dropped silently -- the file has
to be observed in the RENDER, not merely on disk.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ALERTING_DIR = REPO_ROOT / "infra/k8s/base/services/grafana-alerting"
DELETED_RULES = ALERTING_DIR / "deleted-rules.yaml"

#: The retirement that produced this file. A FLOOR, never a copy of the file's
#: contents: an expectation read from the file under test passes for whatever the
#: file happens to say, including nothing at all (lesson-416). Later retirements
#: add entries; this one may not disappear.
MUST_STAY_DELETED = "obs015-crowdsec-ban-surge"


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _deleted_uids() -> set[str]:
    doc = _load(DELETED_RULES)
    return {e["uid"] for e in doc.get("deleteRules", []) if isinstance(e, dict) and e.get("uid")}


def _declared_uids() -> set[str]:
    """Every alert-rule uid the repo still declares, across all rule files."""
    uids: set[str] = set()
    for path in sorted(ALERTING_DIR.glob("*.yaml")):
        if path == DELETED_RULES:
            continue
        doc = _load(path)
        for group in doc.get("groups", []) or []:
            for rule in group.get("rules", []) or []:
                if isinstance(rule, dict) and rule.get("uid"):
                    uids.add(rule["uid"])
    return uids


class TestTheDeletionIsDeclared:
    def test_the_retired_crowdsec_rule_is_declared_deleted(self) -> None:
        deleted = _deleted_uids()
        assert MUST_STAY_DELETED in deleted, (
            f"{MUST_STAY_DELETED} is not in deleteRules. Removing its entry does not "
            f"'clean up' anything: Grafana applies deleteRules on every start, a "
            f"missing rule is not an error, and an instance that has not yet "
            f"processed the deletion -- a restored PVC, a cluster rebuilt from an "
            f"older backup -- would resume evaluating a rule that was never once true."
        )

    def test_an_entry_carries_the_org_it_applies_to(self) -> None:
        """`orgId` defaults to 1, but a default is not a declaration."""
        entries = _load(DELETED_RULES).get("deleteRules", [])
        assert entries, "deleteRules is empty; this file's only purpose is its entries."
        missing = [e.get("uid", "<no uid>") for e in entries if "orgId" not in e]
        assert not missing, f"deleteRules entries without an explicit orgId: {missing}"


class TestTheTwoHalvesCannotContradict:
    def test_no_uid_is_both_declared_and_deleted(self) -> None:
        """A rule that is declared AND deleted has no defined outcome.

        Grafana provisions both blocks from the same directory; which one wins is
        not something this repo should be relying on. Re-adding a retired rule
        means removing its uid from deleteRules in the same change.
        """
        declared = _declared_uids()
        # Anti-vacuity floor on the DERIVED set, not on its input: if the parse
        # silently yields nothing, an intersection with it is empty and every
        # assertion below passes while checking nothing (lesson-416).
        assert len(declared) >= 5, (
            f"Only {len(declared)} declared rule uids were parsed from {ALERTING_DIR}. "
            f"The repo declares far more than that, so the parse is broken and the "
            f"contradiction check below would pass vacuously."
        )

        both = declared & _deleted_uids()
        assert not both, (
            f"These uids are both declared as rules and listed for deletion: "
            f"{sorted(both)}. Pick one -- re-adding a retired rule means dropping its "
            f"deleteRules entry in the same change."
        )


class TestTheDeletionSurvivesTheRender:
    """A generator entry is precisely what can be dropped without a visible failure.

    Reading `deleted-rules.yaml` off disk proves only that someone wrote it. If it
    is not listed in the ConfigMap generator it never reaches the cluster, the
    rule is never deleted, and every file-reading check still agrees with the
    author's intent -- the same shape as the `tls: {}` patch that let prod retry
    an impossible ACME order for months.
    """

    @staticmethod
    def _rendered_alerting_configmap(env: str) -> dict:
        if shutil.which("kubectl") is None:
            pytest.skip(
                "CANNOT CHECK: kubectl is not installed, so the render cannot be "
                "produced. This is not a pass -- the deletion is unverified here."
            )
        result = subprocess.run(
            ["kubectl", "kustomize", str(REPO_ROOT / f"infra/k8s/overlays/{env}")],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.fail(f"kubectl kustomize {env} failed:\n{result.stderr}")
        cms = [
            d
            for d in yaml.safe_load_all(result.stdout)
            if d
            and d.get("kind") == "ConfigMap"
            and d.get("metadata", {}).get("name", "").startswith("grafana-alerting")
        ]
        assert len(cms) == 1, f"expected one grafana-alerting ConfigMap in {env}, got {len(cms)}"
        return cms[0]

    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_the_deletion_reaches_the_configmap(self, env: str) -> None:
        cm = self._rendered_alerting_configmap(env)
        assert "deleted-rules.yaml" in cm["data"], (
            f"The {env} render's grafana-alerting ConfigMap has no deleted-rules.yaml. "
            f"The file exists on disk but is not wired into the generator, so no "
            f"cluster ever receives it and no rule is ever deleted."
        )
        doc = yaml.safe_load(cm["data"]["deleted-rules.yaml"])
        rendered = {e["uid"] for e in doc.get("deleteRules", [])}
        assert MUST_STAY_DELETED in rendered, (
            f"{MUST_STAY_DELETED} is absent from the {env} rendered deletion list."
        )
