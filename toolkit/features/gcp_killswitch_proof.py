"""Fire the billing kill switch at a scratch project and prove it detached.

AC2b: *"The kill-switch function is invoked directly once against a scratch
condition and shown to detach billing. A budget rule that has never fired is not
evidence."*

The proof repoints the REAL function rather than deploying a copy, deliberately.
A copy would prove the code detaches billing; repointing proves that the
function as deployed -- its trigger, its identity, its permissions, its source --
does. Those are different claims, and only the second is what protects the hub.

The cost of that choice is a window in which the switch is aimed elsewhere, and
the runbook is blunt about it: *"a function left pointing at the scratch project
is a kill switch that will never fire on the hub -- and its failure mode is
silence."* So the restore here is not a step that follows the test. It is a
`finally` that runs whatever happens, and its success is asserted rather than
assumed -- the same shape as the tfvars cleanup, and for the same reason: a
cleanup reachable only on the happy path is not a cleanup.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass

from toolkit.core.logging import logger

# A budget notification, exactly as Google publishes one. NOTHING here names a
# project: the target is the function's own environment. A synthetic message
# carrying one would exercise a branch production never reaches.
_SCHEMA_KEYS = ("budgetDisplayName", "costAmount", "budgetAmount", "currencyCode")


class KillSwitchProofError(RuntimeError):
    """The proof could not be completed. Distinct from 'the switch did not fire'."""


@dataclass(frozen=True)
class ProofResult:
    scratch_project: str
    detached: bool
    seconds_waited: float
    restored_to: str


def _gcloud(*args: str, check: bool = True) -> str:
    result = subprocess.run(["gcloud", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise KillSwitchProofError(f"gcloud {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def current_target(function: str, region: str) -> str:
    """The project the deployed function would act on right now."""
    return _gcloud(
        "functions",
        "describe",
        function,
        "--region",
        region,
        "--format",
        "value(serviceConfig.environmentVariables.TARGET_PROJECT)",
    )


def _repoint(function: str, region: str, target: str) -> None:
    """Change the env var WITHOUT redeploying the code.

    `gcloud functions deploy --update-env-vars` looks like the way and is not:
    it re-runs a deployment, so it demands `--source` and fails with

        Invalid value for [--source]: Provided source directory does not have
        file  which is required for .

    -- measured, on the first real run. Pointing it at the local directory would
    rebuild from working-tree source, so the proof would exercise a DIFFERENT
    artifact from the one Terraform deployed, defeating the reason for
    repointing the real function rather than deploying a copy.

    A 2nd-gen function IS a Cloud Run service. Updating the service's
    environment leaves the deployed image untouched and swaps only the variable.
    """
    _gcloud(
        "run",
        "services",
        "update",
        function,
        "--region",
        region,
        "--update-env-vars",
        f"TARGET_PROJECT={target}",
        "--quiet",
    )


def _billing_enabled(project: str) -> bool:
    out = _gcloud("billing", "projects", "describe", project, "--format", "value(billingEnabled)")
    return out.strip().lower() == "true"


def _publish(topic: str, budget: float, cost: float, currency: str) -> None:
    """Publish a message shaped like the real thing, to the real topic.

    Through the topic rather than by invoking the function directly: the trigger
    wiring is part of what is being proven, and a direct invocation would skip
    it entirely.
    """
    payload = {
        "budgetDisplayName": "kubelab-hub HARD CAP (proof)",
        "costAmount": cost,
        "budgetAmount": budget,
        "currencyCode": currency,
    }
    assert set(payload) == set(_SCHEMA_KEYS), "the synthetic message drifted from the real schema"
    _gcloud("pubsub", "topics", "publish", topic, "--message", json.dumps(payload))


def run_proof(
    *,
    function: str,
    region: str,
    topic: str,
    scratch_project: str,
    expected_home: str,
    timeout_s: float = 180.0,
    poll_s: float = 10.0,
) -> ProofResult:
    """Repoint, fire, verify, and restore no matter what happened."""
    # NAMED FIRST, before anything else is judged. `make gcp-killswitch-prove`
    # feeds this from `terraform output -raw project_id`, which can succeed and
    # print nothing when the output exists but is empty -- and the empty string
    # then failed the billing check instead, reporting "already has billing
    # disabled" about a project that was never named. That sends the reader to
    # check billing on a project that does not exist. Raised by review on #1245.
    if not scratch_project.strip():
        raise KillSwitchProofError(
            "no scratch project named. `make gcp-killswitch-prove` derives it from "
            "`terraform output -raw project_id`; an empty value there means the "
            "scratch root was never applied, or its state is gone."
        )

    home = current_target(function, region)
    if home != expected_home:
        # Refuse rather than proceed: if the switch is already aimed somewhere
        # unexpected, restoring it "back" would cement a wrong value.
        raise KillSwitchProofError(
            f"{function} currently targets {home!r}, expected {expected_home!r}. "
            "Refusing to run: the restore would write the wrong target back."
        )

    if scratch_project == home:
        raise KillSwitchProofError(
            f"scratch project is {scratch_project!r}, the same as the live target. "
            "The proof would work and demonstrate it by taking the hub down."
        )

    if not _billing_enabled(scratch_project):
        raise KillSwitchProofError(
            f"{scratch_project} already has billing disabled; the proof would pass without the switch doing anything."
        )

    detached = False
    waited = 0.0
    try:
        logger.info(f"repointing {function}: {home} -> {scratch_project}")
        _repoint(function, region, scratch_project)

        logger.info(f"publishing a threshold notification to {topic}")
        _publish(topic, budget=15.0, cost=16.0, currency="USD")

        started = time.monotonic()
        while (waited := time.monotonic() - started) < timeout_s:
            if not _billing_enabled(scratch_project):
                detached = True
                break
            time.sleep(poll_s)
    finally:
        # UNCONDITIONAL. Every early return, every exception, every timeout
        # comes through here -- because the alternative is a disarmed kill
        # switch whose only symptom is that nothing ever happens.
        logger.info(f"restoring {function} -> {home}")
        _repoint(function, region, home)
        restored = current_target(function, region)
        if restored != home:
            raise KillSwitchProofError(
                f"RESTORE FAILED: {function} now targets {restored!r}, not {home!r}. "
                "The kill switch is aimed at the wrong project and will not protect "
                "the hub. Fix this before anything else."
            )

    return ProofResult(
        scratch_project=scratch_project,
        detached=detached,
        seconds_waited=round(waited, 1),
        restored_to=home,
    )
