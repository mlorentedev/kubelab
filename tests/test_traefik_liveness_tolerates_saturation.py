"""Traefik's liveness probe must not restart it for being busy (OPS-063, #3018).

The probe answers from the same process as the traffic. At 1,600/s in staging,
with Traefik at 3.6 cores, the chart default (2-second timeout, three failures 10
seconds apart) restarted it twice in a minute, dropping every open connection at
the moment of saturation. Liveness exists for a process that is stuck, which a
saturated one is not, so it now waits longer before deciding. A stuck Traefik is
still restarted, within the bound asserted below. Readiness had the same default
timeout and a threshold of 1, so one slow answer took the only replica out of the
Service.
"""

from __future__ import annotations

import pathlib

import jinja2
import yaml

from tests.ansible_jinja import ansible_env

ROLE = pathlib.Path(__file__).resolve().parents[1] / "infra/ansible/roles/k3s_server"
# The default gave up after 30 s of answers slower than 2 s, which saturation alone produced.
MIN_TIMEOUT_SECONDS = 5
MIN_SECONDS_TO_RESTART = 60
# Stuck must still be caught.
MAX_SECONDS_TO_RESTART = 180


def _values() -> dict:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    env = ansible_env(str(ROLE / "templates"), undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    rendered = env.get_template("traefik-helmconfig.yaml.j2").render(**defaults, ansible_managed="Ansible managed")
    return yaml.safe_load(yaml.safe_load(rendered)["spec"]["valuesContent"])


def test_liveness_waits_out_saturation_and_still_catches_a_stuck_process() -> None:
    probe = _values()["livenessProbe"]
    # The kubelet probes on a ticker and restarts on the threshold-th consecutive
    # failure: from the first failure that is at least one period per further
    # failure, and a probe that runs to its timeout delays the next one, so a hang
    # is caught within one period plus one timeout per failure.
    fastest = probe["periodSeconds"] * (probe["failureThreshold"] - 1)
    slowest = (probe["periodSeconds"] + probe["timeoutSeconds"]) * probe["failureThreshold"]
    assert probe["timeoutSeconds"] >= MIN_TIMEOUT_SECONDS
    assert MIN_SECONDS_TO_RESTART <= fastest, f"restarts after {fastest}s of failures"
    assert slowest <= MAX_SECONDS_TO_RESTART, f"a stuck edge waits up to {slowest}s"


def test_readiness_does_not_drop_the_only_replica_for_one_slow_answer() -> None:
    """One replica: unready removes the only endpoint, an outage, for one probe over 2 s by default."""
    probe = _values()["readinessProbe"]
    assert probe["timeoutSeconds"] >= MIN_TIMEOUT_SECONDS
    assert probe["failureThreshold"] >= 3
