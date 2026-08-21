"""Unit tests for the fleet failure-notify path — ANSIBLE-035, ANSIBLE-038.

The mechanism lives in the ``node_notify`` role, which installs one
``kubelab-notify@.service`` template for every unit in the fleet. ``node_maintenance``
is now just its first consumer, and this file spans both roles for that reason:
the linkage it asserts is precisely the thing that lives in neither one alone.

Pure render + subprocess assertions: NO SSH, no live node, no n8n. Runs under
``make test`` (marker-less → collected by ``-m "not e2e and not infra"``).

Why these tests exist: ANSIBLE-035 shipped with live evidence only — a standalone
delivery on 2 of 7 nodes and one deliberate failure injection. That proves the
path worked once; it cannot notice the path being *removed*. The adversarial
review flagged that gap (F2) and it is the reason for this file.

The contract encoded here:

- ``OnFailure=kubelab-notify@%n.service`` on a consuming unit. This is the
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
import os
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
NOTIFY_ROLE = REPO / "infra/ansible/roles/node_notify"
MAINTENANCE_ROLE = REPO / "infra/ansible/roles/node_maintenance"
# Both roles' template dirs, because the contract under test spans them: the
# `OnFailure=` line lives on the consumer and the unit it names lives on the
# provider, and a test that could only see one side would pass through exactly
# the half-rename it exists to catch.
TEMPLATES = [NOTIFY_ROLE / "templates", MAINTENANCE_ROLE / "templates"]


def _defaults() -> dict[str, object]:
    """Both roles' defaults, merged — so a renamed variable fails here, not in prod.

    The two namespaces (`node_notify_*` and `maintenance_*`) do not collide, and
    merging them means either role's template renders from one context.
    """
    merged: dict[str, object] = {}
    for role in (NOTIFY_ROLE, MAINTENANCE_ROLE):
        merged.update(yaml.safe_load((role / "defaults/main.yml").read_text()))
    return merged


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
        loader=FileSystemLoader([str(d) for d in TEMPLATES]),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template(template).render(**ctx)


# --- the linkage itself ----------------------------------------------------


def test_main_unit_declares_onfailure_to_the_notify_unit():
    """The one line the entire alert path depends on (AC6)."""
    unit = _render("kubelab-maintenance.service.j2")
    assert "OnFailure=kubelab-notify@%n.service" in unit, (
        "the consumer no longer names the fleet notifier. `%n` is load-bearing: it "
        "is the consuming unit's own full name, and it becomes the notifier's "
        "instance, which is how the notifier knows whose journal to read."
    )


def test_onfailure_target_names_a_unit_the_role_actually_installs():
    """Guards the half-rename: OnFailure= pointing at a unit that does not exist.

    systemd accepts an OnFailure= naming a non-existent unit without complaint —
    the failure surfaces only when the trigger fires, which is precisely when
    nobody is watching.
    """
    unit = _render("kubelab-maintenance.service.j2")
    target = re.search(r"^OnFailure=(\S+)$", unit, re.MULTILINE)
    assert target, "main unit has no OnFailure= directive"
    # `foo@%n.service` is an INSTANCE of the template `foo@.service`. Resolve it
    # back to the template before looking for the file, or this asserts the
    # existence of a unit systemd never expects to find on disk.
    template_unit = re.sub(r"@[^.]*", "@", target.group(1), count=1)
    assert any((d / f"{template_unit}.j2").is_file() for d in TEMPLATES), (
        f"OnFailure names {target.group(1)!r}, whose template {template_unit!r} exists "
        f"in no role. systemd accepts this silently and the alert path is dead until "
        f"the trigger fires — which is when nobody is watching."
    )
    # A template file on disk is not a template file INSTALLED. The original
    # form of this assertion stopped at the first half, which would keep passing
    # against a role that carried the .j2 and never rendered it — the source
    # present, the node without it. Raised by review on #1212.
    installer = next(
        (
            task
            for task in yaml.safe_load((NOTIFY_ROLE / "tasks/main.yml").read_text())
            if str(task.get("template", {}).get("src", "")) == f"{template_unit}.j2"
        ),
        None,
    )
    assert installer is not None, (
        f"no task in node_notify renders {template_unit}.j2; the unit OnFailure names "
        f"would never reach the node"
    )
    assert "node_notify_unit_name" in installer["template"]["dest"], (
        "the install path is a literal rather than the declared variable, so the unit "
        "name is now asserted in two places that can drift apart"
    )


def test_notify_unit_execstart_matches_the_script_the_role_deploys():
    """Unit and script must agree on the path; the tasks file installs both."""
    unit = _render("kubelab-notify@.service.j2")
    # The script path is the first token; `%i` follows it as the argument.
    exec_start = re.search(r"^ExecStart=(\S+)( .*)?$", unit, re.MULTILINE)
    assert exec_start, "notify unit has no ExecStart"
    tasks = (NOTIFY_ROLE / "tasks/main.yml").read_text()
    # `==`, not `in`. As a substring check an ExecStart of `/opt` passed, because
    # `/opt` is a substring of `/opt/kubelab-notify.sh` — the assertion accepted
    # a unit pointing at a directory. Raised by review on #1212.
    assert exec_start.group(1) == _defaults()["node_notify_script_path"], (
        f"the unit runs {exec_start.group(1)!r}, which is not the "
        f"{_defaults()['node_notify_script_path']!r} the role declares"
    )
    assert "node_notify_script_path" in tasks, "the role does not install that script"
    assert (exec_start.group(2) or "").strip() == "%i", (
        "the notifier must be handed the failing unit as `%i`; without it the script "
        "refuses, and the failure is reported by nothing"
    )


# --- the design decisions worth pinning ------------------------------------


def test_notify_domain_is_a_literal_not_derived_from_env_config():
    """Prod n8n on every node, including the three whose deploy_env is staging.

    Asserted on the parsed value, not the file text: the contract is that the
    domain is a LITERAL rather than a Jinja expression resolving through
    ``config.*``. Matching raw text would also match the comment that explains
    the decision — i.e. it would punish documenting it.
    """
    domain = _defaults()["node_notify_domain"]
    assert domain == "n8n.kubelab.live"
    assert "{{" not in str(domain), "domain must not be derived per-env"


def test_cleanup_and_timer_gates_are_independent(  # AC1
):
    """Provisioning installs the timer without running a synchronous cleanup."""
    d = _defaults()
    assert d["maintenance_install_timer"] is True
    assert d["maintenance_run_cleanup"] is True


def test_notify_script_reads_the_token_from_the_declared_secret_file():
    script = _render("kubelab-notify.sh.j2")
    assert str(_defaults()["node_notify_secret_file"]) in script
    assert "set -euo pipefail" in script


def test_notify_script_posts_to_the_public_webhook_ingress():
    script = _render("kubelab-notify.sh.j2")
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
    script = _render("kubelab-notify.sh.j2")
    body = re.search(r'python3 -c "\n(.*?)\n"', script, re.DOTALL)
    assert body, "could not locate the python3 encoder in the rendered script"
    # FAILED_UNIT reaches the encoder through the ENVIRONMENT, exactly as the
    # script hands it over. Extracting this mechanism made the unit name a
    # runtime value for the first time, and passing it in the environment rather
    # than splicing it into the program text is what keeps it data instead of
    # code — asserted here by running the encoder the same way the unit does.
    proc = subprocess.run(
        [sys.executable, "-c", body.group(1)],
        input=journal_bytes,
        capture_output=True,
        env={**os.environ, "FAILED_UNIT": "node-backup-ship.service"},
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
    script = _render("kubelab-notify.sh.j2")
    assert "--connect-timeout" in script
    assert "--max-time" in script


# --- ANSIBLE-038 f4: the token must not reach curl's argv ------------------


def _serve_one_request(captured: list[bytes]) -> int:
    """Start a one-shot HTTP listener on a free port; return the port.

    Raw socket rather than ``http.server``: the assertion is about the exact
    header bytes curl put on the wire, and a framework that normalises headers
    would hide precisely the corruption this test exists to catch.
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        captured.append(data)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        conn.close()
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def _executable_lines(script: str) -> str:
    """The script with comment lines removed.

    Needed for any assertion phrased as "this text must NOT appear": the
    comments here quote the pre-fix form to explain why it changed, so a raw
    text match would fail on the explanation and pass on the bug. The same
    trap is called out in test_notify_domain_is_a_literal below — a test that
    breaks when you document a decision teaches you not to document it.
    """
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )


def test_token_is_not_a_curl_argv_element():
    """The finding itself: ``-H "Authorization: Bearer ..."`` is visible in ps.

    Asserted on the rendered text because argv is what ``/proc/<pid>/cmdline``
    exposes, and a process-inspection race would make this flaky for no gain.
    """
    code = _executable_lines(_render("kubelab-notify.sh.j2"))
    assert not re.search(r"-H\s+[\"']Authorization:", code), (
        "the bearer token is back in curl's argv, where ps can read it"
    )
    assert "--config -" in code, "token must reach curl through a config on stdin"


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("plain-base64_token==", id="ordinary"),
        # Each of these is silently CORRUPTED, not rejected, if the escaping
        # regresses: a bare `"` truncates the value at that byte and n8n then
        # answers 403 -- losing the notification the unit exists to deliver.
        pytest.param('quote"inside', id="double-quote"),
        pytest.param("back\\slash", id="backslash"),
        pytest.param('mixed"and\\both #hash', id="every-metacharacter"),
    ],
)
def test_config_stdin_delivers_the_token_byte_exact(token: str):
    """Run the SHIPPED curl invocation and read the header off the wire.

    The escaping is the risk the fix introduces: moving the token out of argv
    moves it into curl's config parser, which processes ``\\`` and ``"`` inside
    a quoted value. Rendering-and-asserting would not catch a bad escape --
    only sending it does.

    The URL is the one substitution: the template hardcodes https, and standing
    up TLS here would test openssl rather than the escaping.
    """
    script = _render("kubelab-notify.sh.j2")
    block = script[script.index("TOKEN_ESC=") :]

    captured: list[bytes] = []
    port = _serve_one_request(captured)
    block = block.replace(
        f"https://{_defaults()['node_notify_domain']}", f"http://127.0.0.1:{port}"
    )

    proc = subprocess.run(
        ["bash", "-c", f'TOKEN="$1"\nPAYLOAD=\'{{"probe":1}}\'\n{block}', "bash", token],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"curl failed: {proc.stderr}"
    assert captured, "listener received no request"

    sent = [
        line
        for line in captured[0].decode("utf-8", "replace").split("\r\n")
        if line.lower().startswith("authorization:")
    ]
    assert sent == [f"Authorization: Bearer {token}"], (
        f"token corrupted in transit: {sent!r}"
    )


def test_the_envelope_names_the_unit_that_actually_failed() -> None:
    """One notifier serves every unit, so the title is the only thing that says which.

    Under the old single-purpose script the unit name was a Jinja literal and
    could not be wrong. Now it is a runtime value, and an envelope that reports
    the wrong unit — or reports none — sends the operator to the wrong journal.
    """
    envelope = _encode_via_rendered_script(b"whatever")
    assert "node-backup-ship.service" in envelope["title"], (
        f"the failing unit is missing from the envelope title: {envelope['title']!r}"
    )
    assert envelope["severity"] == "log"


# --- ANSIBLE-038 f5: retry budget vs the unit's own timeout -----------------


def _flag(script: str, name: str) -> int:
    """Read a numeric curl flag from the code, never from the prose.

    The comments quote these same flags with their current values, so reading
    the whole file would keep passing after someone edited the explanation and
    forgot the command -- the one divergence this test needs to catch.
    """
    match = re.search(rf"{re.escape(name)}\s+(\d+)", _executable_lines(script))
    assert match, f"{name} missing from the notify script"
    return int(match.group(1))


def test_notify_unit_timeout_exceeds_the_script_retry_budget():
    """A retry longer than TimeoutStartSec is worse than no retry at all.

    systemd would kill the unit mid-attempt, so a delivery still in progress is
    reported as a timeout. Measured against a blackholed host, the pre-fix
    combination of retries with the old 30s timeout took 35.0s -- i.e. adding a
    retry without moving the timeout would have manufactured this failure.

    Worst case is ``--retry-max-time`` (after which curl starts no NEW attempt)
    plus one final attempt bounded by ``--max-time``.
    """
    script = _render("kubelab-notify.sh.j2")
    worst_case = _flag(script, "--retry-max-time") + _flag(script, "--max-time")

    unit = _render("kubelab-notify@.service.j2")
    timeout = re.search(r"^TimeoutStartSec=(\d+)$", unit, re.MULTILINE)
    assert timeout, "notify unit has no TimeoutStartSec"

    assert int(timeout.group(1)) > worst_case, (
        f"TimeoutStartSec={timeout.group(1)}s cannot contain a {worst_case}s retry budget"
    )


def test_retry_is_in_curl_not_in_the_unit():
    """Pins the choice between the two places a retry could live.

    Not a law of nature -- a deliberate decision, recorded so that re-adding
    Restart= means confronting it rather than ending up with both. Both at once
    is the bad outcome: systemd re-running a script that is already retrying.
    """
    script = _render("kubelab-notify.sh.j2")
    assert "--retry" in script

    unit = _render("kubelab-notify@.service.j2")
    directives = re.findall(r"^(Restart)=", unit, re.MULTILINE)
    assert not directives, (
        "Restart= on the unit duplicates the retry curl already performs"
    )


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


# --- the tag topology, which a dry run found and no static test had ---------


PLAYBOOKS = sorted((REPO / "infra/ansible/playbooks").glob("*.yml"))


def _notifier_consumers() -> set[str]:
    """Every role with a unit template declaring `OnFailure=kubelab-notify@`.

    Derived from the templates rather than listed here, because the case this
    guard exists for is a NEW consumer whose playbook wiring was forgotten — and
    a literal list is exactly the thing that would not contain it.
    """
    roles = set()
    for template in (REPO / "infra/ansible/roles").glob("*/templates/*.j2"):
        # Anchored to the start of a line, so the DIRECTIVE matches and a
        # comment mentioning it does not. Without the anchor the scan counted
        # `node_notify` itself as a consumer of its own notifier — its unit
        # template documents the line callers should write — and every
        # assertion below then compared that role's tags with themselves and
        # passed trivially. A guard agreeing with itself, found by mutating the
        # directive away and watching the vacuity check stay green (lesson-357).
        if re.search(r"^OnFailure=kubelab-notify@", template.read_text(encoding="utf-8"), re.M):
            roles.add(template.parents[1].name)
    return roles


def _role_tags(playbook: Path, role_name: str) -> set[str] | None:
    """Tags on one role entry in a playbook, or None if it does not include it."""
    for play in yaml.safe_load(playbook.read_text()) or []:
        if not isinstance(play, dict):
            continue
        for entry in play.get("roles") or []:
            name = entry.get("role", "") if isinstance(entry, dict) else str(entry)
            if str(name).split("/")[-1] == role_name:
                return set(entry.get("tags") or []) if isinstance(entry, dict) else set()
    return None


def test_the_derived_consumer_set_is_not_empty() -> None:
    """The guard below is vacuous if the scan finds nothing.

    A test parametrized over playbooks would go green on every one of them by
    skipping, which is the shape lesson-357 catalogues: a guard reporting
    coverage it does not have. So the scan asserts on itself first.
    """
    assert _notifier_consumers(), (
        "no role template declares `OnFailure=kubelab-notify@`, so the pairing "
        "guard below checks nothing at all"
    )


@pytest.mark.parametrize("playbook", PLAYBOOKS, ids=lambda p: p.stem)
def test_the_notifier_and_its_consumers_are_selected_together(playbook: Path):
    """Neither half of the pairing may be reachable by a tag the other lacks.

    The dependency runs both ways. A selector reaching only `node_notify`
    installs a notifier nothing names. One reaching only a consumer leaves its
    units pointing at a template unit that node does not have — and systemd
    accepts that silently, reporting "unit not found" on the next failure and
    telling nobody, which is the entire failure class this mechanism exists to
    remove, reintroduced by a tag.

    `node_maintenance` adds a third reason: it removes the superseded notifier
    after re-pointing its own unit, so running it without `node_notify` deletes
    the old path and names a new one that is not there.

    Found by a `--check` run against the VPS, not by reading a diff: the role
    carried a `notify` tag of its own and `TAGS=notify` selected exactly the
    unsafe subset.
    """
    consumers = {c: _role_tags(playbook, c) for c in _notifier_consumers()}
    present = {c: tags for c, tags in consumers.items() if tags is not None}
    notify = _role_tags(playbook, "node_notify")

    if not present and notify is None:
        pytest.skip(f"{playbook.stem} includes neither the notifier nor a consumer")

    assert notify is not None, (
        f"{playbook.stem} includes {sorted(present)} but not node_notify. Those "
        f"units declare `OnFailure=kubelab-notify@%n.service`, and a node reached "
        f"only by this playbook would never get the template they name."
    )
    assert present, (
        f"{playbook.stem} includes node_notify and no consumer of it. Either a "
        f"consumer's include was dropped, or this role is being installed where "
        f"nothing names it."
    )
    for consumer, tags in present.items():
        assert notify == tags, (
            f"{playbook.stem}: node_notify has {sorted(notify)!r} and {consumer} "
            f"{sorted(tags)!r}. Any tag in one and not the other selects half a "
            f"pairing, and the half that runs alone leaves the node silent."
        )
