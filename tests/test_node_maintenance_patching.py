"""The maintenance timer patches security updates — SEC-010.

It cleaned disk and patched nothing. Eight nodes accumulated CVEs with no
automation and no report, the internet-facing VPS among them.

Three properties here are not obvious from reading the script, and each one is
a defect this fleet has already met in another form.
"""

from __future__ import annotations

import pathlib

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/node_maintenance"


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _render() -> str:
    """Render with Ansible's `bool` filter stubbed.

    Jinja has no `bool` filter; Ansible adds it. Rendering without the stub
    fails on the template rather than on anything under test.
    """
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1")
    tpl = (ROLE / "templates/kubelab-maintenance.sh.j2").read_text(encoding="utf-8")
    return env.from_string(tpl).render(
        {**_defaults(), "ansible_managed": "am", "inventory_hostname": "kubelab-vps"}
    )


def test_patching_runs_before_the_cleanup_that_wipes_the_package_lists() -> None:
    """Order is load-bearing, not tidiness.

    The cleanup deletes `/var/lib/apt/lists`. Patching afterwards would
    re-download every index it had just removed — on an RPi over a homelab
    link, every week, for nothing.
    """
    script = _render()
    patch = script.index("security updates")
    wipe = script.index("rm -rf /var/lib/apt/lists")
    assert patch < wipe, (
        "security patching runs after the cleanup that wipes the package lists, so "
        "every run re-downloads the indexes it just deleted"
    )


def test_the_runtime_packages_are_held_during_the_unattended_run() -> None:
    """Upgrading these RESTARTS the thing they belong to, on a node nobody watches.

    docker/containerd restarting stops every container — on ace1 that is K3s
    itself, on beelink it is Gitea and the CI runner. `tailscale` is worse
    still: it is the path this fleet is administered over, so a failed upgrade
    removes the way in to fix it.
    """
    blacklist = set(_defaults()["maintenance_patch_blacklist"])
    for essential in ("containerd.io", "docker-ce", "k3s", "tailscale"):
        assert essential in blacklist, (
            f"{essential} is not held during the unattended patch run; upgrading it "
            f"restarts the runtime under a live workload with no operator present"
        )
    script = _render()
    for pkg in blacklist:
        assert f"apt-mark hold {pkg}" in script, f"{pkg} declared but never held"
        assert f"apt-mark unhold {pkg}" in script, (
            f"{pkg} is held and never released — an operator running `apt upgrade` by "
            f"hand would be silently blocked by a hold this script placed"
        )


def test_it_patches_the_security_pocket_only() -> None:
    """A full dist-upgrade on an unattended timer is how a Tuesday becomes an outage.

    This fleet has no on-call, and the blacklist cannot anticipate every package
    a full upgrade would touch.
    """
    script = _render()
    assert "-security" in script, "the upgrade is not restricted to the security pocket"
    assert "dist-upgrade" not in script, (
        "an unattended dist-upgrade can pull in new packages and new kernel lines "
        "on a node with nobody watching"
    )


def test_a_node_that_cannot_patch_still_gets_cleaned() -> None:
    """The RPi4 is the standing proof, not a hypothetical.

    Its apt has been unable to resolve `bzip2` since #1198. A maintenance run
    that aborted on a failed patch would have stopped vacuuming journals on a
    node with 8GB of storage — trading a CVE for a full disk.
    """
    script = _render()
    assert "PATCH_STATUS" in script, "the patch outcome is not tracked"
    assert "apt-get update failed" in script, (
        "a failed `apt-get update` is not reported; on a node with a broken apt "
        "this run would silently patch nothing and say nothing"
    )


def test_a_pending_reboot_is_reported_because_nothing_reboots() -> None:
    """A kernel installed is not a kernel running.

    Nothing here reboots — the VPS carries Headscale, so an unattended reboot
    that does not come back removes the VPN used to reach it. Unreported, a
    patched-on-disk node reads as safe while running the old kernel, which is
    worse than not patching: it manufactures confidence.
    """
    script = _render()
    assert "/var/run/reboot-required" in script, "a pending reboot is never surfaced"
    assert "shutdown -r" not in script and "systemctl reboot" not in script, (
        "the maintenance timer reboots the node. The VPS is the Headscale bootstrap "
        "dependency: a reboot that does not come back removes the VPN used to fix it."
    )


def test_both_implementations_of_this_role_patch() -> None:
    """This role does the same work twice, and the two must not diverge.

    `make maintain` runs the Ansible tasks. The weekly timer runs
    `kubelab-maintenance.sh`. They are separate implementations of one
    behaviour, which is exactly how one of them ends up doing something the
    other does not.

    Found the hard way: the patch step was added to the script first, deployed,
    and `make maintain NODE=vps` then reported success having patched nothing —
    because the command an operator runs by hand never touches the script.
    """
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    names = [t.get("name", "") for t in tasks]
    assert any("security updates" in n.lower() for n in names), (
        "the Ansible path does not patch, so `make maintain` cleans disk and leaves "
        "the node unpatched while reporting success"
    )
    assert any("reboot" in n.lower() for n in names), (
        "the Ansible path never reports a pending reboot"
    )
    # And the two must agree on WHAT is held.
    script = _render()
    for pkg in _defaults()["maintenance_patch_blacklist"]:
        assert f"apt-mark hold {pkg}" in script, f"{pkg} not held on the timer path"
    holds = [t for t in tasks if "apt-mark hold" in str(t.get("command", ""))]
    assert holds, "the Ansible path holds nothing; a `make maintain` could restart K3s"


def test_neither_path_reboots_the_node() -> None:
    """The VPS is the Headscale bootstrap dependency.

    An unattended reboot that does not come back removes the VPN used to reach
    the host that would fix it. Asserted on BOTH paths, since either could
    acquire one independently.
    """
    script = _render()
    assert "systemctl reboot" not in script and "shutdown -r" not in script
    tasks_text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
    assert "reboot: " not in tasks_text and "ansible.builtin.reboot" not in tasks_text, (
        "the Ansible path reboots the node; on the VPS that removes the VPN used to "
        "reach it if it does not come back"
    )
