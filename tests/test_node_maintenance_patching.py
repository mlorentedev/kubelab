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
        # Quoted in the rendered script, and held only when NOT ALREADY held —
        # see test_an_operators_existing_hold_survives_the_run for why the
        # blanket form was a defect rather than a simplification.
        assert f"apt-mark hold '{pkg}'" in script, f"{pkg} declared but never held"
    assert "apt-mark unhold" in script, (
        "nothing is released, so a hold this script placed outlives the run and "
        "silently blocks an operator's own `apt upgrade`"
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
        assert f"apt-mark hold '{pkg}'" in script, f"{pkg} not held on the timer path"
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


def test_the_patch_tasks_report_change_only_when_they_change_something() -> None:
    """Idempotence, asserted where it is decided rather than measured after.

    Verified on the live VPS: two consecutive `make maintain NODE=vps ENV=prod`
    runs both reported `ok=31` with `security patching: already current`, and
    the only tasks reporting `changed` were the four pre-existing cleanup ones
    (`Remove APT package lists`, `Recreate APT lists directory`, and the two
    image prunes). Those are non-idempotent BY DESIGN — deleting and recreating
    a directory changes something every time, which is the job.

    None of the patch tasks may join them. `apt-mark hold/unhold` runs on every
    pass and reports nothing; only the upgrade itself may claim a change, and
    only when it applied one.
    """
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    by_name = {t.get("name", ""): t for t in tasks}

    for name in (
        "Hold packages whose upgrade would restart a live workload",
        "Release only the holds THIS RUN created",
    ):
        task = by_name[name]
        assert task.get("changed_when") is False, (
            f"{name!r} would report `changed` on every run. A hold placed and released "
            f"within one run changed nothing that outlives it, and a permanently noisy "
            f"task is one whose output stops being read."
        )
        assert task.get("failed_when") is False, (
            f"{name!r} can fail the run. Holding a package that is not installed is "
            f"normal on a fleet where not every node runs docker or k3s."
        )

    upgrade = by_name["Apply security updates"]
    assert upgrade.get("failed_when") is False, (
        "a node that cannot patch must still get its disk cleaned — the RPi4's apt "
        "has been broken since #1198 and it needs journal vacuuming more, not less"
    )


def test_an_operators_existing_hold_survives_the_run() -> None:
    """Raised in review of #1258, and it was a real defect.

    Both paths held every blacklist package and then unheld every one. Pinning a
    package is how an operator stops an upgrade they already know breaks
    something — and this role would have silently undone that pin on the next
    weekly tick.

    So the run records the prior hold state, adds only what was missing, and
    releases only what it added.
    """
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    by_name = {t.get("name", ""): t for t in tasks}

    assert any("ALREADY held" in n for n in by_name), (
        "the run never reads the prior hold state, so it cannot tell its own holds "
        "from an operator's and will release both"
    )
    release = next(t for n, t in by_name.items() if n.startswith("Release only"))
    assert "difference" in str(release["loop"]), (
        "the release loops over the whole blacklist rather than over what this run "
        "added; a deliberate pin does not survive it"
    )

    script = _render()
    assert "HELD_BEFORE" in script and "HELD_BY_US" in script, (
        "the timer path still blanket-holds and blanket-unholds. The two "
        "implementations must not diverge — that divergence is how the Ansible path "
        "shipped without patching at all."
    )
    assert "apt-mark unhold" in script
    assert "for pkg in $HELD_BY_US" in script, (
        "the timer path releases more than it took"
    )


def test_a_hold_that_fails_on_an_installed_package_stops_the_upgrade() -> None:
    """The distinction a blanket `failed_when: false` was hiding.

    A hold failing because the package is not installed is normal — not every
    node runs docker or k3s. A hold failing on a package apt DOES know about
    means the protection is not in place, and upgrading anyway restarts the
    workload the hold exists to protect.

    Told apart by apt's own output rather than package facts: this role never
    runs `package_facts`, so a filter on `ansible_facts.packages` would match
    nothing on every node — a guard that can never fire. Measured on beelink:
    `apt-mark hold docker-ce` (installed) -> rc=0; `apt-mark hold k3s` (absent)
    -> rc=100, "Unable to locate package".
    """
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    by_name = {t.get("name", ""): t for t in tasks}

    detect = by_name["Determine whether any hold failed on an INSTALLED package"]
    expr = str(detect["set_fact"]["_unprotected"])
    assert "Unable to locate package" in expr, (
        "the check does not distinguish `not installed` from `could not hold`, so "
        "either it stops on every node missing docker or it never stops at all"
    )
    assert "ansible_facts.packages" not in expr, (
        "this role never gathers package_facts, so a filter on it matches nothing "
        "and produces a guard that cannot fire"
    )

    upgrade = by_name["Apply security updates"]
    assert "_unprotected" in str(upgrade["when"]), (
        "the upgrade runs even when a runtime package could not be held. Leaving a "
        "node unpatched is recoverable; restarting every container on it is not."
    )

    script = _render()
    assert "Unable to locate package" in script, "the timer path lacks the distinction"
    assert "PATCH_STATUS=\"unprotected\"" in script, (
        "the timer path does not report the skip, so the node looks patched"
    )


def test_the_gating_conditionals_yield_booleans() -> None:
    """Ansible rejects a conditional whose result is a list, and it is fatal.

    Measured on beelink: `and not (_unprotected | default([]))` produced

        Conditional result (False) was derived from value of type 'list'
        Conditionals must have a boolean result.

    The run aborted at that task — AFTER placing the holds and BEFORE releasing
    them, so the node was left with docker, containerd and tailscale held by a
    run that never came back to unhold them. A crash between hold and release
    is the one failure mode this pair of tasks must not have.
    """
    # Parsed, not grepped. The first version of this guard walked lines with a
    # `continue` that skipped every line it was meant to inspect — it passed
    # against the exact mutation it exists to catch, which is a guard reporting
    # coverage it does not have (lesson-357).
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    offenders = [
        (task.get("name", "?"), str(task["when"]))
        for task in tasks
        if "_unprotected" in str(task.get("when", "")) and "length" not in str(task["when"])
    ]
    assert not offenders, (
        f"these conditionals test a bare list, which Ansible refuses at run time and "
        f"which strands the holds between placing and releasing them: {offenders}"
    )
