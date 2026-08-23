"""`/etc/resolv.conf` belongs to systemd-resolved, declared rather than repaired.

Tailscale chooses its DNS-management mode by inspecting that file. When it is
systemd-resolved's stub symlink it drives resolved over D-Bus and leaves the
file alone; when it is a regular file it enters "direct" mode and overwrites the
file with MagicDNS as the only nameserver. On this fleet `override_local_dns` is
false by design, so MagicDNS answers SERVFAIL for anything outside the split
zones — and direct mode leaves glibc no second resolver to fall through to.

Measured on ace2 2026-08-23: no public name resolved, `make provision` aborted
in pre-flight, and the node's own pre-Tailscale backup showed the symlink had
been gone *before* Tailscale ever ran. Stopping tailscaled does not restore it,
so the state never heals on its own.

These are structure assertions over the parsed YAML, not text scans. A `grep`
for "resolv.conf" passes on the explanatory comment alone, which is the exact
false green this repo has hit repeatedly — the comment is not the mechanism.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
BASE_SYSTEM = REPO / "infra/ansible/roles/base_system"
PLAYBOOKS = REPO / "infra/ansible/playbooks"

RESOLV_LINK_TARGET = "../run/systemd/resolve/stub-resolv.conf"
HANDLER = "restart tailscaled"

# The three playbooks that provision an Ubuntu LAN node through this pre-flight.
SHARED_PREFLIGHT_PLAYBOOKS = ("provision-ace1", "provision-ace2", "provision-bee")


def _tasks() -> list[dict]:
    return yaml.safe_load((BASE_SYSTEM / "tasks/main.yml").read_text())


def _index_of(tasks: list[dict], predicate) -> int:
    for i, task in enumerate(tasks):
        if predicate(task):
            return i
    return -1


def _is_resolv_link(task: dict) -> bool:
    """A `file:` task making /etc/resolv.conf a link to resolved's stub."""
    spec = task.get("file") or task.get("ansible.builtin.file") or {}
    return (
        spec.get("dest") == "/etc/resolv.conf" and spec.get("state") == "link" and spec.get("src") == RESOLV_LINK_TARGET
    )


def test_base_system_declares_resolv_conf_as_the_resolved_stub() -> None:
    """Declared state, so a node that drifted into direct mode heals on provision.

    `force: true` is part of the contract: without it the task is a no-op on
    exactly the node that needs it, because a regular file already occupies the
    path and Ansible refuses to replace it with a link.
    """
    tasks = _tasks()
    idx = _index_of(tasks, _is_resolv_link)
    assert idx >= 0, (
        "base_system no longer declares /etc/resolv.conf as a link to "
        f"{RESOLV_LINK_TARGET}. Without it, a node whose file Tailscale took over "
        "in direct mode resolves nothing and never recovers."
    )
    spec = tasks[idx].get("file") or tasks[idx].get("ansible.builtin.file")
    assert spec.get("force") is True, (
        "the link task must set `force: true`; a regular file already occupies "
        "/etc/resolv.conf on precisely the broken node, and without force the "
        "task reports ok and changes nothing"
    )


def test_the_link_is_declared_before_anything_that_resolves_a_name() -> None:
    """Ordering is the whole point — apt cannot run on a node with no DNS.

    If this task drifts below the apt block, the run fails with a mirror error
    that never mentions DNS, on a node the very next task would have repaired.
    """
    tasks = _tasks()
    link_at = _index_of(tasks, _is_resolv_link)
    apt_at = _index_of(tasks, lambda t: "apt" in t and isinstance(t.get("apt"), dict))
    assert link_at >= 0 and apt_at >= 0, "expected both the link task and an apt task"
    assert link_at < apt_at, (
        f"the resolv.conf link is declared at position {link_at}, after the first "
        f"apt task at {apt_at}. apt resolves names; the repair must precede it."
    )


def test_the_stale_pre_tailscale_backup_is_removed() -> None:
    """`tailscale down` restores that file, reintroducing the fault post-repair."""
    tasks = _tasks()
    idx = _index_of(
        tasks,
        lambda t: (
            (t.get("file") or t.get("ansible.builtin.file") or {}).get("path")
            == "/etc/resolv.pre-tailscale-backup.conf"
        ),
    )
    assert idx >= 0, "the direct-mode backup file must be removed, not left as a latent revert"
    spec = tasks[idx].get("file") or tasks[idx].get("ansible.builtin.file")
    assert spec.get("state") == "absent"


def test_the_link_task_notifies_a_handler_that_exists() -> None:
    """Restoring the symlink fixes public DNS; the restart is what restores split DNS.

    Tailscale re-detects its management mode at takeover, not at start, so
    without the restart the node resolves the internet but not the split zones.
    A notify naming a handler that does not exist fails the play at runtime, and
    only on the node that triggers it.
    """
    tasks = _tasks()
    task = tasks[_index_of(tasks, _is_resolv_link)]
    notify = task.get("notify")
    notify = [notify] if isinstance(notify, str) else (notify or [])
    assert HANDLER in notify, f"the link task must notify {HANDLER!r}; it notifies {notify!r}"

    handlers = yaml.safe_load((BASE_SYSTEM / "handlers/main.yml").read_text())
    declared = {h.get("name") for h in handlers}
    assert HANDLER in declared, f"handler {HANDLER!r} is notified but not declared in {declared}"

    handler = next(h for h in handlers if h.get("name") == HANDLER)
    assert handler.get("when"), (
        "the handler must be conditioned on tailscaled existing — base_system also "
        "runs on a node being provisioned for the first time, where the tailscale "
        "role has not installed the unit yet"
    )


@pytest.mark.parametrize("playbook", SHARED_PREFLIGHT_PLAYBOOKS)
def test_the_connectivity_preflight_is_shared_not_copied(playbook: str) -> None:
    """One check, three consumers — and it must not collapse DNS into "no internet".

    The single `curl https://get.docker.com` this replaces reported a repairable
    DNS fault as a missing internet connection and aborted the run that would
    have repaired it. Measured on ace2: the IP probe returned OK in the same
    second the name probe returned curl rc=6.
    """
    text = (PLAYBOOKS / f"{playbook}.yml").read_text()
    assert "_includes/check-internet.yml" in text, (
        f"{playbook} must use the shared connectivity pre-flight; a private copy "
        "drifts, and the copy is what turned a self-healing fault into a hard stop"
    )
    assert "get.docker.com" not in text, (
        f"{playbook} still carries an inline name-resolution probe. That is the "
        "check that cannot tell 'no network' from 'no DNS', and they need "
        "opposite responses."
    )


def test_the_shared_preflight_separates_reachability_from_resolution() -> None:
    """Two questions, two remedies: only one of them is fatal in this play.

    IP connectivity is not repairable by anything in this repo, so it fails the
    run. Name resolution is repairable by base_system — but only where
    systemd-resolved is active, so that is the condition that decides between
    aborting and continuing.
    """
    tasks = yaml.safe_load((PLAYBOOKS / "_includes/check-internet.yml").read_text())

    fatal = [t for t in tasks if "fail" in t]
    assert fatal, "an unrepairable resolution fault must abort rather than proceed into apt"
    guarded = [t for t in fatal if "_preflight_resolved" in str(t.get("when", ""))]
    assert guarded, (
        "the abort must be conditioned on the repair being unavailable; aborting "
        "unconditionally is the behaviour this include exists to remove"
    )

    ip_probe = [t for t in tasks if "1.1.1.1" in str(t.get("command", ""))]
    assert ip_probe, "the include must probe reachability by IP, independently of DNS"
    assert not any(t.get("failed_when") is False for t in ip_probe), (
        "the IP probe is the fatal half — nothing in this repo repairs a node that cannot reach the internet at all"
    )
