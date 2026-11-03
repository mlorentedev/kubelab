"""Traefik's liveness probe must not restart it for being busy (OPS-063, #3018).

The probe answers from the same process as the traffic. At 1,600/s in staging,
with Traefik at 3.6 cores, the chart default (2-second timeout, three failures 10
seconds apart) restarted it twice in a minute, dropping every open connection at
the moment of saturation. Liveness exists for a process that is stuck, which a
saturated one is not, so it now waits longer before deciding. A stuck Traefik is
still restarted, within the bound asserted below.
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
    window = probe["periodSeconds"] * probe["failureThreshold"]
    assert probe["timeoutSeconds"] >= MIN_TIMEOUT_SECONDS
    assert MIN_SECONDS_TO_RESTART <= window <= MAX_SECONDS_TO_RESTART
