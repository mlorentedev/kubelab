"""OBS-007 / AC6: the per-environment alert tier must be checked in the RENDER.

The prod overlay overrides one key of the `grafana-alerting` ConfigMap so that
prod pages and staging archives. Every way of checking that by reading the
overlay files is a check of intent against intent — the patch says what it wants,
and says nothing about whether Kustomize honoured it.

That distinction is not theoretical here. `overlays/prod/patches.yaml` carried a
`tls: {}` block, complete with a comment claiming it removed the base's ACME
resolver. An empty map in a strategic-merge patch means "change nothing", so the
resolver survived and prod retried an impossible Let's Encrypt order roughly once
a day for months. Every file-reading check agreed with the comment. Only the
rendered output disagreed (docs/lessons.md, 2026-08-09; fixed in #927).

So these assertions run `kubectl kustomize` and read what comes out.

The base default is deliberately the STAGING value, which makes the failure mode
observable: if the prod merge ever stops taking effect, prod renders
`apprise-log` and `test_prod_and_staging_differ` fails. Verified by rendering
`infra/k8s/base` alone on 2026-08-10 — it emits `apprise-log`.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Which Apprise tier each environment routes to. Stated here rather than read
#: from the manifests: an expectation sourced from the file under test passes for
#: any pair of values.
EXPECTED_RECEIVER = {"staging": "apprise-log", "prod": "apprise-page"}

REQUIRED_KEYS = {
    "contact-points.yaml",
    "templates.yaml",
    "policies.yaml",
    "rules.yaml",
    "quota-rules.yaml",
    "r2-backup-rules.yaml",
    "inhibit-rules.yaml",
    "sre-rules.yaml",
    "disk-rules.yaml",
    "slo-rules.yaml",
    "security-rules.yaml",
}


def _kustomize(path: str) -> list[dict]:
    """Render a Kustomize directory, or skip loudly if kubectl is unavailable.

    A skip here means CANNOT CHECK, which is not the same as OK and must never be
    reported as one.

    Note on where this actually runs: no CI workflow invokes pytest at all — CI
    runs `go test` for the API plus bandit/pip-audit over the toolkit, and the
    Python suite executes only on a workstation (there is no pre-commit pytest
    hook either). So this guard exists for the local case, not for CI, and the
    coverage question for this module is answered by whoever runs `make test`
    before deploying. Tracked separately; do not read a green PR as having run
    these assertions.
    """
    if shutil.which("kubectl") is None:
        pytest.skip(
            "CANNOT CHECK: kubectl is not installed, so the rendered output cannot be "
            "produced. This is not a pass — AC6 is unverified in this environment. "
            "Run `make test` on a workstation, or before `make deploy-k8s`."
        )

    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize {path} failed:\n{result.stderr}")

    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _alerting_configmap(env: str) -> dict:
    """The single grafana-alerting ConfigMap emitted by an overlay's render."""
    docs = _kustomize(f"infra/k8s/overlays/{env}")
    cms = [
        d
        for d in docs
        if d.get("kind") == "ConfigMap"
        and d.get("metadata", {}).get("name", "").startswith("grafana-alerting")
    ]
    assert len(cms) == 1, (
        f"Expected exactly one grafana-alerting ConfigMap in the {env} render, found "
        f"{[c['metadata']['name'] for c in cms]}. Two would mean the overlay generator "
        f"minted a second object instead of merging into the base one."
    )
    return cms[0]


def _rendered_receiver(cm: dict) -> str:
    """The root notification policy's receiver, as actually rendered."""
    policies = yaml.safe_load(cm["data"]["policies.yaml"])
    return policies["policies"][0]["receiver"]


class TestRenderedAlertTier:
    """Read the emitted manifest, never the patch."""

    @pytest.mark.parametrize("env", sorted(EXPECTED_RECEIVER))
    def test_rendered_receiver_matches_the_tier(self, env: str) -> None:
        """Each environment must render its own tier: prod pages, staging archives."""
        cm = _alerting_configmap(env)
        actual = _rendered_receiver(cm)

        assert actual == EXPECTED_RECEIVER[env], (
            f"{env} renders root receiver {actual!r}, expected "
            f"{EXPECTED_RECEIVER[env]!r}. Prod must page and staging must archive "
            f"(ADR-044 tiers). Check the configMapGenerator merge in "
            f"infra/k8s/overlays/{env}/kustomization.yaml."
        )

    @pytest.mark.parametrize("env", sorted(EXPECTED_RECEIVER))
    def test_merge_preserves_the_shared_keys(self, env: str) -> None:
        """`behavior: replace` would silently drop the contact points."""
        cm = _alerting_configmap(env)
        missing = REQUIRED_KEYS - set(cm["data"])

        assert not missing, (
            f"The {env} render is missing {sorted(missing)} from the grafana-alerting "
            f"ConfigMap. If the overlay uses `behavior: replace` instead of `merge`, "
            f"the base keys are dropped and the policy routes to a receiver that "
            f"does not exist — alerts are then discarded silently."
        )

    def test_policies_differ_only_in_the_receiver(self) -> None:
        """The receiver is the ONLY field the overlay is allowed to change.

        Design B keeps the per-environment surface to one file, but that file is
        still a full copy of the policy — so `group_wait`, `group_interval` and
        `repeat_interval` can drift apart between base and prod with nothing to
        notice. This is the only drift surface the design leaves open, and it
        costs one assertion to close.
        """
        staging = yaml.safe_load(_alerting_configmap("staging")["data"]["policies.yaml"])
        prod = yaml.safe_load(_alerting_configmap("prod")["data"]["policies.yaml"])

        s_policy = dict(staging["policies"][0])
        p_policy = dict(prod["policies"][0])
        s_policy.pop("receiver")
        p_policy.pop("receiver")

        assert s_policy == p_policy, (
            "The staging and prod notification policies differ in a field other than "
            "`receiver`. Only the tier may vary per environment; timing and grouping "
            f"must not drift.\n  staging: {s_policy}\n  prod:    {p_policy}"
        )

    def test_prod_and_staging_differ(self) -> None:
        """The whole point of the overlay. Guards against a no-op merge.

        If the prod merge stops taking effect, prod inherits the base value and
        this fails — which is the specific silent failure #927 taught.
        """
        staging = _rendered_receiver(_alerting_configmap("staging"))
        prod = _rendered_receiver(_alerting_configmap("prod"))

        assert staging != prod, (
            f"Both environments render the same receiver {staging!r}, so the prod "
            f"overlay changed nothing. The base default is the staging value, so "
            f"this is what a no-op merge looks like."
        )
