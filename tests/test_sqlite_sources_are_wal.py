"""Every SQLite source node-backup captures must be readable WHILE it is written.

`node-backup-capture.sh.j2` says `.backup` is "WAL-aware". That is true of
`.backup` and was never checked against the DATABASE. In the default
rollback-journal mode a writer's commit takes an EXCLUSIVE lock that refuses
readers, so the capture aborts, no sentinel is written, and the ship step
correctly declines to send a partial backup.

Measured 2026-09-04 across all six sources declared under `backup.sources` in
common.yaml:

    beelink / gitea        delete   <- failed at 06:23:58, "database is locked"
    prod / authelia        delete
    rpi3 / uptime_kuma     WAL
    rpi4 / pihole          WAL
    vps / headscale        WAL
    prod / n8n             WAL

The four in WAL are there by each application's own default. Nobody chose it and
nothing recorded it, which is why the failure looked random: it depends on which
default an image ships and whether that database happens to be under sustained
write during the capture minute. Gitea failed because act_runner posts
UpdateTask every second for a running job; Authelia has not failed yet because
few people log in at 06:00, which makes it unmeasured rather than safe.

Scope of THIS file, stated so its silence is not read as coverage: it asserts
only the declarations this repository controls. A live check of the other four
belongs to a runtime guard, not a static test — the repo cannot see a journal
mode that lives inside a database file on a node.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import ChainableUndefined
from tests.ansible_jinja import ansible_env

REPO_ROOT = Path(__file__).resolve().parents[1]
BEELINK_ROLE = REPO_ROOT / "infra" / "ansible" / "roles" / "beelink_services"
COMMON = REPO_ROOT / "infra" / "config" / "values" / "common.yaml"


def _beelink_compose() -> dict:
    env = ansible_env(str(BEELINK_ROLE / "templates"), undefined=ChainableUndefined)
    return yaml.safe_load(
        env.get_template("compose.yml.j2").render(
            ansible_managed="Ansible managed",
            beelink_deploy_dir="/opt/kubelab",
            tailscale_ip="100.64.0.3",
        )
    )


def test_gitea_declares_wal() -> None:
    """The one source that has already failed, and the one with a setting for it."""
    env = (_beelink_compose().get("services") or {}).get("gitea", {}).get("environment") or {}
    assert env.get("GITEA__database__SQLITE_JOURNAL_MODE") == "WAL", (
        "gitea does not declare WAL. Its database is read by node-backup while "
        "act_runner writes to it every second during a job; in rollback-journal "
        "mode the commit's EXCLUSIVE lock refuses the reader and the capture "
        "aborts. Measured failing 2026-09-04 06:23:58."
    )


def test_the_declaration_is_read_from_a_real_render() -> None:
    """Anti-vacuity on the DERIVED object, not on the template text.

    A ChainableUndefined render that silently produced no services would make
    the assertion above pass against an empty dict. The floor is on the parsed
    services, one step before the assertion consumes them.
    """
    services = _beelink_compose().get("services") or {}
    assert len(services) >= 3, (
        f"only {len(services)} services parsed from the beelink compose render; "
        f"the render is broken and the WAL assertion above proves nothing"
    )
    assert "gitea" in services


def test_every_declared_sqlite_source_is_accounted_for() -> None:
    """A seventh source must not join silently without someone deciding its mode.

    Not "every source is in WAL" — this repository cannot see a journal mode
    that lives inside a database file on a node, and a static test that claimed
    to would be asserting something it never checked. What it CAN assert is that
    the set of sources is the one this decision was taken over. A new entry
    fails here and the failure says what to do about it.
    """
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    sources = (common.get("backup") or {}).get("sources") or {}
    found = {
        f"{node}/{service}"
        for node, services in sources.items()
        for service, spec in (services or {}).items()
        if isinstance(spec, dict) and spec.get("sqlite")
    }

    # Measured 2026-09-04, each read from the live database rather than assumed.
    known = {
        "beelink/gitea",  # was `delete`; now declares WAL (see test above)
        "vps/authelia",  # `delete`; Authelia's storage.local exposes no
        #                  journal-mode setting, so it is covered by the capture
        #                  script's timeout+retry rather than by a declaration.
        #                  Open: give it one via an initContainer.
        "rpi3/uptime_kuma",  # WAL by the application's default
        "rpi4/pihole",  # WAL by the application's default
        "vps/headscale",  # WAL by the application's default
        "vps/n8n",  # WAL by the application's default
    }
    # n8n and authelia are Kubernetes PVCs, declared under `vps` because that is
    # the host whose backup unit captures them — the key is the node, not the
    # runtime. Named as common.yaml names them so the diff of a new source reads
    # against the file it came from.

    assert found == known, (
        f"the set of SQLite backup sources changed: added {sorted(found - known)}, "
        f"removed {sorted(known - found)}. A new source inherits this problem — "
        f"`.backup` competes with the writer unless the database is in WAL. "
        f"Measure it (`PRAGMA journal_mode`), declare WAL if the application "
        f"allows it, and add it here with what you measured."
    )
