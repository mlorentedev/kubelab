"""The coverage heartbeat: who pages, who only shows, and what cannot fail.

BACKUP-044 AC9 — a run that never *started* is reported. Every other control in
this repository asserts something about the runs that do exist; none can see the
absence of one, which is the shape the 2026-08-14 PVC incident took.

The mechanism is a push monitor per node: the ship script posts as its last step,
Uptime Kuma on the RPi3 marks the monitor DOWN when the heartbeat stops. The
watcher is deliberately outside the failure domain it watches.

Two properties here are not obvious from reading either file alone.

**Muting is entirely tag-driven.** `monitoring_diff.wants_notifications` is
`not (tags & muted_tags)`, and the seed's own `notificationIDList` is ignored by
the apply path. So an on-demand node stays silent because it carries a muted
tag — nothing else does it — and removing that tag from the SSOT starts paging
at 3 AM the first night the homelab sleeps.

**The heartbeat must not fail the ship unit.** A 5xx from Kuma, or CrowdSec
banning the node's IP — which is in this very request path — would fire
`OnFailure=` and page "backup failed" about a backup that succeeded. And nothing
is lost by not failing: a heartbeat that does not arrive is precisely what the
monitor exists to notice. The failure mode of the call is the signal.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
MONITORS = json.loads((REPO / "infra/config/uptime-kuma/monitors.json").read_text())
TAGS_SEED = json.loads((REPO / "infra/config/uptime-kuma/tags.json").read_text())
SHIP = REPO / "infra/ansible/roles/node_backup/templates/node-backup-ship.sh.j2"

MUTED = frozenset(
    COMMON["apps"]["services"]["observability"]["uptime_kuma"]["muted_notification_tags"]
)
BACKUP_NODES = sorted(COMMON["backup"]["sources"])


def _location(node: str) -> str:
    nodes = COMMON["networking"]["nodes"]
    return (nodes.get(node) or COMMON["networking"][node])["location"]


def _heartbeat_monitors() -> dict[str, dict]:
    return {
        m["key"]: m for m in MONITORS if str(m.get("key", "")).startswith("ops-backup-node-")
    }


def test_every_backed_up_node_has_a_coverage_monitor() -> None:
    """The seed and `backup.sources` are one list, or a node is silently uncovered.

    A node whose backup runs but whose absence nobody watches is the exact gap
    AC9 names, and it arrives by adding a node to one file and not the other.
    """
    seeded = {k.removeprefix("ops-backup-node-") for k in _heartbeat_monitors()}
    assert seeded == set(BACKUP_NODES), (
        f"backup.sources covers {sorted(BACKUP_NODES)} and the monitor seed covers "
        f"{sorted(seeded)}. A node in the first and not the second backs up with "
        f"nobody watching for its silence."
    )


def test_every_coverage_monitor_has_a_registered_token() -> None:
    """`hydrate_push_tokens` raises for a declared monitor with no token.

    That is the right behaviour and a poor way to find out: it fails the whole
    `monitors apply`, at the operator's terminal, after the seed was committed.
    """
    from toolkit.features.secrets_manager import SECRET_CATALOG

    registered = {
        spec.key_path.rsplit(".", 1)[-1].removeprefix("ops_backup_node_")
        for spec in SECRET_CATALOG
        if "uptime_kuma.push_tokens" in spec.key_path
    }
    assert registered == set(BACKUP_NODES), (
        f"push tokens registered for {sorted(registered)}, monitors seeded for "
        f"{sorted(BACKUP_NODES)}. A monitor with no token fails `monitors apply` closed."
    )


def test_the_seed_never_carries_a_push_token() -> None:
    """`monitors.json` is committed to a PUBLIC repository.

    The push endpoint is publicly routed and the token is its only credential, so
    a token here lets anyone post "still alive" to the monitor whose entire
    purpose is to notice silence.
    """
    leaked = [m["key"] for m in MONITORS if m.get("pushToken")]
    assert not leaked, f"these monitors carry an inline pushToken in a public file: {leaked}"


@pytest.mark.parametrize("node", BACKUP_NODES)
def test_the_monitor_pages_exactly_when_the_node_is_always_on(node: str) -> None:
    """Both directions, and the second is the one that bites.

    An always-on monitor that inherits a muted tag is a control that cannot fire
    — the failure class this spec exists to remove, reintroduced by a tag. An
    on-demand monitor that loses its muted tag pages at 3 AM the first night the
    homelab sleeps, and being woken by a correct DOWN is how a channel stops
    being read.
    """
    monitor = _heartbeat_monitors()[f"ops-backup-node-{node}"]
    tags = set(monitor.get("tags") or [])
    # The apply path's own rule, restated rather than imported: this must hold
    # even if that function is refactored, because it is a claim about the
    # configuration, not about the code that reads it.
    pages = not (tags & MUTED)

    if _location(node) == "always-on":
        assert pages, (
            f"{node} is always-on, but its coverage monitor carries the muted tag(s) "
            f"{sorted(tags & MUTED)}. It would watch and never speak."
        )
    else:
        assert not pages, (
            f"{node} is on-demand and its coverage monitor would PAGE. It is powered "
            f"off most of the week, so DOWN is the coverage view working — waking "
            f"someone for it is how the channel stops being read. Give it a tag from "
            f"muted_notification_tags ({sorted(MUTED)})."
        )


def test_every_tag_the_monitors_use_exists_in_the_tag_seed() -> None:
    """A tag absent from `tags.json` is skipped silently by the apply path.

    `add_monitor_tag` failures are caught and ignored as cosmetic — which they
    are for grouping, and are not for a reader trying to see at a glance which
    monitors page.
    """
    declared = {t["name"] for t in TAGS_SEED}
    used = {t for m in _heartbeat_monitors().values() for t in (m.get("tags") or [])}
    assert used <= declared, (
        f"these tags are used by a coverage monitor and declared in no tag seed: "
        f"{sorted(used - declared)}"
    )


def test_the_alerting_window_is_the_ratified_rpo_not_a_margin() -> None:
    """6h is #452's Tier 1 RPO, so the alert fires when the GUARANTEE is at risk.

    Pinned because the alternative — a margin over the 4h schedule — silently
    stops meaning anything the moment the schedule changes, while this forces
    whoever changes it to confront the RPO.
    """
    for key, monitor in _heartbeat_monitors().items():
        assert monitor["interval"] == 21600, f"{key} window is {monitor['interval']}s, not 6h"
        assert monitor["maxretries"] == 0, (
            f"{key} retries before going DOWN, which delays the verdict past the "
            f"boundary the interval was chosen to mark"
        )
        assert monitor["type"] == "push", f"{key} is not a push monitor"


# --- the heartbeat call itself, executed rather than read -------------------

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the block is bash")


def _heartbeat_block() -> str:
    """The rendered heartbeat, lifted out of the ship script.

    Rendered with the real defaults rather than invented ones, so a variable
    renamed in the role fails here.
    """
    import jinja2

    defaults = yaml.safe_load(
        (REPO / "infra/ansible/roles/node_backup/defaults/main.yml").read_text()
    )
    ctx = {
        **defaults,
        "ansible_managed": "Ansible managed",
        "inventory_hostname": "rpi3",
        "node_backup_heartbeat_domain": "status.kubelab.live",
        "node_backup_r2_repository": "s3:x",
    }
    rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
        SHIP.read_text()
    ).render(**ctx)
    marker = "# --- coverage heartbeat"
    assert marker in rendered, "the heartbeat block is gone from the ship script"
    return rendered[rendered.index(marker) :]


@_needs_bash
@pytest.mark.parametrize("curl_exit", [0, 22, 7], ids=["delivered", "http-error", "unreachable"])
def test_a_failed_heartbeat_never_fails_the_ship(tmp_path: pathlib.Path, curl_exit: int) -> None:
    """The backup succeeded. Nothing here may claim otherwise.

    `set -euo pipefail` is active in the ship script, so an unguarded curl turns
    a healthy backup into a failed unit, `OnFailure=` fires, and the operator is
    paged about a backup that worked — the inverse of the title defect fixed in
    #1216.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "curl"
    stub.write_text(f"#!/usr/bin/env bash\ncat > /dev/null\nexit {curl_exit}\n")
    stub.chmod(0o755)
    token = tmp_path / "token"
    token.write_text("Abc-123_xyz")

    block = _heartbeat_block().replace(
        "/opt/node-backup-heartbeat-token", str(token)
    )
    proc = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + block],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"curl exiting {curl_exit} failed the ship script (rc={proc.returncode}). The "
        f"backup had already succeeded; a deaf watchdog must not be reported as a "
        f"failed backup.\n{proc.stdout}\n{proc.stderr}"
    )


@_needs_bash
def test_the_token_never_reaches_curls_argv(tmp_path: pathlib.Path) -> None:
    """ANSIBLE-038 f4, in the one place the endpoint forces the token into a URL.

    Kuma takes the token in the URL PATH, so the naive form puts a live
    credential in `ps` / /proc/<pid>/cmdline for the life of the call. It has to
    ride curl's config on stdin instead.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    seen = tmp_path / "argv"
    stub = bindir / "curl"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > {seen}\ncat > /dev/null\n')
    stub.chmod(0o755)
    token = tmp_path / "token"
    token.write_text("SECRETTOKENVALUE")

    block = _heartbeat_block().replace("/opt/node-backup-heartbeat-token", str(token))
    subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + block],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    argv = seen.read_text()
    assert "SECRETTOKENVALUE" not in argv, (
        f"the push token is in curl's argv, readable via ps for the life of the "
        f"call:\n{argv}"
    )
    assert "--config" in argv, "the token must reach curl through a config on stdin"


@_needs_bash
def test_an_implausible_token_is_refused_rather_than_posted(tmp_path: pathlib.Path) -> None:
    """The token is interpolated into a URL path.

    A stray character does not fail — it addresses a different URL, which
    silently reports a heartbeat for something else or nothing at all.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "called"
    stub = bindir / "curl"
    stub.write_text(f'#!/usr/bin/env bash\ntouch {called}\ncat > /dev/null\n')
    stub.chmod(0o755)
    token = tmp_path / "token"
    token.write_text("../../evil?x=")

    block = _heartbeat_block().replace("/opt/node-backup-heartbeat-token", str(token))
    proc = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + block],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, "a bad token must skip the heartbeat, not fail the ship"
    assert not called.exists(), (
        "curl was invoked with a token that is not a plausible push token; the URL it "
        "built addresses something other than this node's monitor"
    )
