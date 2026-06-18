"""Regression tests for K8sGenerator secret-mount wiring.

Guards the fix for the prod incident where `kubelab-api:1.1.0` CrashLoop'd with
`panic: SMTP credentials ... required in production`: the api Deployment never
referenced `api-secrets`, so `INFRA_SMTP_PASS` was provisioned but never injected.

Root cause: the old `_has_secret_vars` heuristic scanned `APPS_PLATFORM_<APP>_*`
env vars for secret patterns, so its result depended on whether SOPS happened to
be decrypted at generation time (a non-deterministic generator) and was blind to
*shared* `INFRA_*` secrets. The fix ties the mount to the secrets SSOT
(`SECRET_DEFINITIONS`): a Deployment mounts `<app>-secrets` iff that mapping
exists — deterministic, SOPS-independent, and impossible to silently diverge.
"""

from __future__ import annotations

from toolkit.config.constants import COMPONENTS
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS


class TestHasSecretVars:
    """`_has_secret_vars` is driven by the secrets SSOT, not env-var heuristics."""

    def test_api_mounts_its_secret(self) -> None:
        # api-secrets carries INFRA_SMTP_PASS (shared) + BEEHIIV/ZOHO keys. The
        # api workload requires them at boot, so the Deployment must envFrom it.
        assert K8sGenerator()._has_secret_vars("api") is True

    def test_web_has_no_secret_mount(self) -> None:
        # There is no `web-secrets` mapping; web sends no mail and owns no
        # secrets. Mounting a non-existent secret would CrashLoop web — this is
        # the regression the registry approach must never reintroduce.
        assert K8sGenerator()._has_secret_vars("web") is False
        assert not any(m.name == "web-secrets" for m in SECRET_DEFINITIONS)

    def test_mount_decision_matches_registry_for_every_platform_app(self) -> None:
        """The single invariant: mount iff `<app>-secrets` is defined in the SSOT."""
        registered = {m.name for m in SECRET_DEFINITIONS}
        gen = K8sGenerator()
        for app in COMPONENTS.PLATFORM_APPS:
            expected = f"{app}-secrets" in registered
            assert gen._has_secret_vars(app) is expected, (
                f"{app}: mount decision must equal presence of {app}-secrets in "
                "SECRET_DEFINITIONS (the secrets SSOT)"
            )

    def test_is_sops_independent(self) -> None:
        """No env_vars/SOPS input means the result cannot vary by decryption state.

        Repeated calls (and the absence of any env-var argument) make the
        generator deterministic: CI (no age key) and local (SOPS) now emit
        identical overlays, so the ADR-027 drift gate is meaningful again.
        """
        gen = K8sGenerator()
        assert gen._has_secret_vars("api") is gen._has_secret_vars("api")

    def test_api_secret_includes_shared_infra_key(self) -> None:
        """Documents the incident's trigger: api's secret is mostly a *shared*
        INFRA_ secret, which the old `APPS_PLATFORM_API_*` heuristic could miss."""
        api_secret = next(m for m in SECRET_DEFINITIONS if m.name == "api-secrets")
        assert "INFRA_SMTP_PASS" in api_secret.keys
