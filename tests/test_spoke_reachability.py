"""`check-spokes` must ask the question it claims to answer.

It printed `OK (registered + reachable)` for a hub that could not authenticate
to its spoke at all, every time it ran, for the entire life of that hub.

The reason is one line:

    KC=~/.kube/kubelab-$$env-config
    elif kubectl --kubeconfig $$KC get ns kubelab; then echo "OK (registered + reachable)"

It measures whether **the operator** can reach the spoke, using the operator's
own unrestricted kubeconfig. The hub's credential is never exercised. So the
check is green whenever the person running it has working access -- which is
always, because they just ran `kubectl` to read the secret two lines earlier.

WHAT IT MISSED, measured 2026-08-22. The token in the hub's `cluster-staging`
secret was base64-encoded one layer too many (#1277). Every sync answered `the
server has asked for the client to provide credentials`, the staging Application
sat at `Unknown`, and Argo CD fired a Slack card every minute. `check-spokes`
said OK throughout. The outage was found by a human noticing Slack noise, not by
the check built to find it.

THE DISTINCTION THAT MATTERS, and that the old check could not express at all:

    unreachable                  the spoke is down / the network is broken
    reachable, credential refused the spoke is FINE and the hub cannot talk to it

Only the second was happening, and it is the one a hub migration produces. A
check that collapses them into "not OK" would still have been an improvement; a
check that reports neither is what shipped.

Verified BY CONSEQUENCE: the credential is used against the live apiserver and
the HTTP status is the verdict. It is never printed, never written to disk and
never placed in argv -- asking the issuer proves the value works without
revealing it, which is the same rule the transcript doctrine states.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from unittest.mock import patch

from toolkit.features import spoke_reachability as sr

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

TOKEN = "header.payload.signature-that-must-never-be-printed"
CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def _cluster_secret(server: str = "https://100.64.0.11:6443") -> dict:
    """The shape Argo CD stores, base64 exactly where Kubernetes does."""
    config = json.dumps({"bearerToken": TOKEN, "tlsClientConfig": {"caData": base64.b64encode(CA_PEM.encode()).decode()}})
    return {
        "data": {
            "server": base64.b64encode(server.encode()).decode(),
            "config": base64.b64encode(config.encode()).decode(),
        }
    }


class TestTheVerdictComesFromTheHubsOwnCredential:
    def test_a_rejected_token_is_not_reported_as_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The exact case that was invisible: spoke healthy, hub unauthorised."""
        monkeypatch.setattr(sr, "_read_cluster_secret", lambda env, kc: _cluster_secret())
        monkeypatch.setattr(sr, "_probe", lambda server, token, ca_pem: (401, "Unauthorized"))

        result = sr.check_spoke("staging", Path("/dev/null"))

        assert result.registered is True
        assert result.ok is False, "a 401 from the spoke was reported as OK"
        assert result.status == sr.Status.CREDENTIAL_REFUSED
        assert "credential" in result.detail.lower()

    def test_a_working_token_is_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sr, "_read_cluster_secret", lambda env, kc: _cluster_secret())
        monkeypatch.setattr(sr, "_probe", lambda server, token, ca_pem: (200, '{"gitVersion":"v1.34.4+k3s1"}'))

        result = sr.check_spoke("staging", Path("/dev/null"))

        assert result.ok is True
        assert result.status == sr.Status.OK

    def test_an_unreachable_spoke_is_distinct_from_a_refused_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collapsing these two loses the only information a migration needs."""
        monkeypatch.setattr(sr, "_read_cluster_secret", lambda env, kc: _cluster_secret())

        def unreachable(server, token, ca_pem):  # noqa: ANN001, ANN202
            raise OSError("connection refused")

        monkeypatch.setattr(sr, "_probe", unreachable)
        result = sr.check_spoke("staging", Path("/dev/null"))

        assert result.ok is False
        assert result.status == sr.Status.UNREACHABLE
        assert result.status != sr.Status.CREDENTIAL_REFUSED

    def test_an_unregistered_spoke_is_not_probed_at_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sr, "_read_cluster_secret", lambda env, kc: None)

        def must_not_run(*a, **k):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("probed a spoke that is not registered")

        monkeypatch.setattr(sr, "_probe", must_not_run)
        result = sr.check_spoke("staging", Path("/dev/null"))

        assert result.registered is False
        assert result.status == sr.Status.NOT_REGISTERED


class TestTheCredentialNeverLeaves:
    def test_the_result_does_not_carry_or_print_the_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A dataclass prints every field it holds; the safest field is the absent one."""
        monkeypatch.setattr(sr, "_read_cluster_secret", lambda env, kc: _cluster_secret())
        monkeypatch.setattr(sr, "_probe", lambda server, token, ca_pem: (200, "{}"))

        result = sr.check_spoke("staging", Path("/dev/null"))

        assert TOKEN not in repr(result)
        assert TOKEN not in str(result)
        assert TOKEN not in result.detail


class TestTheMakefileNoLongerAsksTheWrongQuestion:
    def test_check_spokes_does_not_decide_from_the_operator_kubeconfig(self) -> None:
        """The defect was structural, so the guard is too.

        A behavioural test cannot see this: the Makefile recipe is shell, and the
        old one produced a correct-looking green on a broken hub.
        """
        recipe = _recipe("check-spokes")
        assert "kubelab-$$env-config" not in recipe, (
            "check-spokes still reads the operator's per-env kubeconfig. That "
            "measures whether YOU can reach the spoke, which is true whenever you "
            "are running the command, and says nothing about the hub's credential."
        )

    def test_check_spokes_delegates_to_the_toolkit(self) -> None:
        """No inline scripts in Makefiles, and this one needs TLS and base64."""
        recipe = _recipe("check-spokes")
        assert "infra argo check-spokes" in recipe, (
            "check-spokes should call the toolkit command that probes with the "
            "hub's stored credential."
        )


def _recipe(target: str) -> str:
    """The recipe lines of one Makefile target."""
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


class TestAnAbsentRegistrationIsAStateNotAFault:
    """`NOT_REGISTERED` must be reported and must not fail the run.

    It is the NORMAL condition during the AWS->GCP migration whenever
    `networking.gcp.managed_spokes` is narrower than `argocd.spokes`: a hub
    legitimately holds no cluster secret for a spoke it does not reconcile. A
    command that is red for months trains everyone to ignore it -- which is how
    the false green this replaces survived so long.

    The list's current value is deliberately not restated here. This docstring
    said `["staging"]` and went stale the day prod was handed over.

    Behavioural, not a text scan. The first version of these two asserted that
    `Status.NOT_REGISTERED` APPEARED in the function body, and a mutation that
    deleted the condition kept them green: the string still occurs in the loop
    that prints. Same shape as lesson-363 -- a scan matching a different
    occurrence than the one that matters. The exit code is the behaviour, so the
    exit code is what is asserted.
    """

    @staticmethod
    def _run(results):  # noqa: ANN001, ANN205
        from typer.testing import CliRunner

        from toolkit.features import spoke_reachability
        from toolkit.main import app

        with patch.object(spoke_reachability, "check_all", return_value=results), patch(
            "toolkit.features.argocd_spokes.spoke_envs", return_value=[r.env for r in results]
        ):
            return CliRunner().invoke(app, ["infra", "argo", "check-spokes"])

    def test_an_unregistered_spoke_alone_exits_zero(self) -> None:
        result = self._run(
            [
                sr.SpokeResult("staging", sr.Status.OK, "https://x:6443", "HTTP 200"),
                sr.SpokeResult("prod", sr.Status.NOT_REGISTERED, None, "no cluster secret"),
            ]
        )
        assert result.exit_code == 0, (
            "an unregistered spoke failed the run. During the migration gcp1 holds "
            "no prod secret by design, so this would be red every time it runs."
        )
        assert "prod" in result.stdout, "the unregistered spoke was not even reported"

    def test_a_refused_credential_still_exits_nonzero(self) -> None:
        """The exemption must stay narrow: only the absent case, never a real fault."""
        result = self._run(
            [
                sr.SpokeResult("staging", sr.Status.CREDENTIAL_REFUSED, "https://x:6443", "HTTP 401"),
                sr.SpokeResult("prod", sr.Status.NOT_REGISTERED, None, "no cluster secret"),
            ]
        )
        assert result.exit_code != 0, (
            "a spoke that refuses the hub's credential did not fail the run -- the "
            "NOT_REGISTERED exemption has widened into ignoring everything"
        )

    def test_an_unreachable_spoke_still_exits_nonzero(self) -> None:
        result = self._run([sr.SpokeResult("staging", sr.Status.UNREACHABLE, "https://x:6443", "refused")])
        assert result.exit_code != 0
