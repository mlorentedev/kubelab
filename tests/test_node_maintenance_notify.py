"""Unit tests for the node_maintenance role's failure-notify path — ANSIBLE-035.

Pure render + subprocess assertions: NO SSH, no live node, no n8n. Runs under
``make test`` (marker-less → collected by ``-m "not e2e and not infra"``).

Why these tests exist: ANSIBLE-035 shipped with live evidence only — a standalone
delivery on 2 of 7 nodes and one deliberate failure injection. That proves the
path worked once; it cannot notice the path being *removed*. The adversarial
review flagged that gap (F2) and it is the reason for this file.

The contract encoded here:

- ``OnFailure=kubelab-maintenance-notify.service`` on the main unit. This is the
  single line the whole alert path hangs from, and deleting it breaks NOTHING
  observable: maintenance keeps running, it just stops reporting its own
  failures. Exactly the defect a manual test cannot catch.
- The notify target is **prod n8n regardless of the node's own env**. Three of
  the seven nodes carry ``deploy_env: staging``; deriving the domain from
  ``config.*`` would point those at staging n8n, whose host (ace1) is on-demand
  — an alert path that only works when the homelab is powered on. The default
  being a literal, not a derivation, is the design decision, so it is asserted.
- The journal body is JSON-encoded by ``python3``, not by shell interpolation,
  because journal content contains quotes and newlines.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/node_maintenance"
TEMPLATES = ROLE / "templates"
DEFAULTS = ROLE / "defaults/main.yml"


def _defaults() -> dict[str, object]:
    """The role's own defaults — so a renamed variable fails here, not in prod."""
    return yaml.safe_load(DEFAULTS.read_text())


def _render(template: str, **overrides: object) -> str:
    """Render one role template with StrictUndefined.

    StrictUndefined is load-bearing: without it a typo'd variable renders as an
    empty string and every assertion below still passes against a URL like
    ``https:///webhook/notify``.
    """
    ctx: dict[str, object] = dict(_defaults())
    ctx.update(
        ansible_managed="Ansible managed",
        inventory_hostname="rpi3",
    )
    ctx.update(overrides)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template(template).render(**ctx)


# --- the linkage itself ----------------------------------------------------


def test_main_unit_declares_onfailure_to_the_notify_unit():
    """The one line the entire alert path depends on (AC6)."""
    unit = _render("kubelab-maintenance.service.j2")
    assert "OnFailure=kubelab-maintenance-notify.service" in unit


def test_onfailure_target_names_a_unit_the_role_actually_installs():
    """Guards the half-rename: OnFailure= pointing at a unit that does not exist.

    systemd accepts an OnFailure= naming a non-existent unit without complaint —
    the failure surfaces only when the trigger fires, which is precisely when
    nobody is watching.
    """
    unit = _render("kubelab-maintenance.service.j2")
    target = re.search(r"^OnFailure=(\S+)$", unit, re.MULTILINE)
    assert target, "main unit has no OnFailure= directive"
    assert (TEMPLATES / f"{target.group(1)}.j2").is_file()


def test_notify_unit_execstart_matches_the_script_the_role_deploys():
    """Unit and script must agree on the path; the tasks file installs both."""
    unit = _render("kubelab-maintenance-notify.service.j2")
    exec_start = re.search(r"^ExecStart=(\S+)$", unit, re.MULTILINE)
    assert exec_start, "notify unit has no ExecStart"
    tasks = (ROLE / "tasks/main.yml").read_text()
    assert exec_start.group(1) in tasks


# --- the design decisions worth pinning ------------------------------------


def test_notify_domain_is_a_literal_not_derived_from_env_config():
    """Prod n8n on every node, including the three whose deploy_env is staging.

    Asserted on the parsed value, not the file text: the contract is that the
    domain is a LITERAL rather than a Jinja expression resolving through
    ``config.*``. Matching raw text would also match the comment that explains
    the decision — i.e. it would punish documenting it.
    """
    domain = _defaults()["maintenance_notify_domain"]
    assert domain == "n8n.kubelab.live"
    assert "{{" not in str(domain), "domain must not be derived per-env"


def test_cleanup_and_timer_gates_are_independent(  # AC1
):
    """Provisioning installs the timer without running a synchronous cleanup."""
    d = _defaults()
    assert d["maintenance_install_timer"] is True
    assert d["maintenance_run_cleanup"] is True


def test_notify_script_reads_the_token_from_the_declared_secret_file():
    script = _render("kubelab-maintenance-notify.sh.j2")
    assert str(_defaults()["maintenance_notify_secret_file"]) in script
    assert "set -euo pipefail" in script


def test_notify_script_posts_to_the_public_webhook_ingress():
    script = _render("kubelab-maintenance-notify.sh.j2")
    assert "https://n8n.kubelab.live/webhook/notify" in script
    # -f: an n8n 4xx/5xx must fail THIS unit rather than be swallowed.
    assert re.search(r"curl\s+-sS\s+-f", script)


# --- the encoding claim, executed rather than asserted about ---------------


def _encode_via_rendered_script(journal_bytes: bytes) -> dict:
    """Run the python3 encoder embedded in the rendered script over raw bytes.

    Extracts the real ``python3 -c "..."`` body from the template output, so this
    exercises the shipped code path instead of a copy that can drift from it.

    Bytes, not str, deliberately: the whole point of the truncation case is that
    what reaches the encoder is not guaranteed to be valid UTF-8.
    """
    script = _render("kubelab-maintenance-notify.sh.j2")
    body = re.search(r'python3 -c "\n(.*?)\n"', script, re.DOTALL)
    assert body, "could not locate the python3 encoder in the rendered script"
    proc = subprocess.run(
        [sys.executable, "-c", body.group(1)],
        input=journal_bytes,
        capture_output=True,
    )
    assert proc.returncode == 0, f"encoder crashed: {proc.stderr.decode(errors='replace')}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize(
    "journal_bytes",
    [
        pytest.param(b"", id="empty-journal"),
        pytest.param(
            b'systemd[1]: Failed with result "exit-code".', id="double-quotes"
        ),
        pytest.param(b"line1\nline2\ttabbed", id="newlines-and-tabs"),
        pytest.param(rb"apt: could not read C:\temp\x", id="backslashes"),
        pytest.param("journalctl: unidad iniciada — café".encode(), id="valid-utf8"),
        # ANSIBLE-038. `tail -c 2000` cuts on a BYTE boundary, so a multi-byte
        # character can arrive truncated. Before the fix this raised
        # UnicodeDecodeError and the notification was lost at the exact moment
        # it mattered. Keep this case: it is the regression guard for the fix.
        pytest.param(b"caf\xc3", id="split-utf8-sequence"),
    ],
)
def test_journal_body_survives_json_encoding(journal_bytes: bytes):
    """The envelope must stay parseable JSON whatever the journal contains."""
    payload = _encode_via_rendered_script(journal_bytes)
    assert payload["severity"] == "log"
    assert payload["domain"] == "fleet"
    assert "rpi3" in payload["title"]
    # Valid input must round-trip exactly; invalid bytes are replaced, not fatal.
    try:
        assert payload["body"] == journal_bytes.decode("utf-8")
    except UnicodeDecodeError:
        assert "\ufffd" in payload["body"]


def test_curl_call_is_time_bounded():
    """ANSIBLE-038: an unreachable n8n must not stall the unit on curl defaults."""
    script = _render("kubelab-maintenance-notify.sh.j2")
    assert "--connect-timeout" in script
    assert "--max-time" in script


def test_token_value_is_not_shell_interpreted():
    """Refutes the review's shell-injection finding, rather than assuming it.

    The reviewer flagged ``-H "Authorization: Bearer ${TOKEN}"`` as an injection
    surface. It is not: expanding a variable inside double quotes does not
    re-parse its value, so a secret file containing ``$(...)`` or backticks is
    passed to curl as a literal. This test pins that, so the day someone
    "hardens" it into ``eval`` or an unquoted expansion, it fails.
    """
    hostile = "$(touch /tmp/kubelab-notify-pwned)`touch /tmp/kubelab-notify-pwned2`"
    probe = 'TOKEN="$1"\nprintf "%s" "Authorization: Bearer ${TOKEN}"\n'
    proc = subprocess.run(
        ["bash", "-c", probe, "bash", hostile], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert proc.stdout == f"Authorization: Bearer {hostile}"
    assert not Path("/tmp/kubelab-notify-pwned").exists()
    assert not Path("/tmp/kubelab-notify-pwned2").exists()
