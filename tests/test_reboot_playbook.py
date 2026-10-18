"""`make reboot` reboots only what needs it, one host at a time, and never the VPS by default.

`make maintain` reports a pending reboot and never acts on it. The reboot is a
separate, operator-run playbook. These tests pin the properties that make it
safe to point at prod: skip hosts with nothing pending (a re-run is changed=0),
serialise, stop at the first failure, refuse the Headscale host without an
explicit opt-in, and fail if the boot did not clear the flag.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
PLAYBOOK = REPO / "infra/ansible/playbooks/reboot.yml"
MAKEFILE = REPO / "Makefile"
PROD = REPO / "infra/config/values/prod.yaml"
COMMON = REPO / "infra/config/values/common.yaml"


def _play() -> dict:
    return yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]


def _tasks() -> list[dict]:
    return _play()["tasks"]


def _index(predicate) -> int:
    for i, task in enumerate(_tasks()):
        if predicate(task):
            return i
    raise AssertionError("task not found")


def _whens(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


def test_one_host_at_a_time_and_stop_on_first_failure() -> None:
    play = _play()
    assert play["serial"] == 1
    assert play["any_errors_fatal"] is True


def test_legacy_python_hosts_end_before_any_module_runs() -> None:
    play = _play()
    assert play["gather_facts"] is False
    first = _tasks()[0]
    assert first.get("meta") == "end_host"
    assert any("legacy_python" in w for w in _whens(first))


def test_hosts_with_nothing_pending_are_left_alone_unless_forced() -> None:
    stat = _index(lambda t: t.get("stat", {}).get("path") == "/var/run/reboot-required")
    skip = _index(lambda t: t.get("meta") == "end_host" and any("_reboot_required" in w for w in _whens(t)))
    reboot = _index(lambda t: "reboot" in t)
    assert stat < skip < reboot
    assert any("reboot_force" in w for w in _whens(_tasks()[skip]))
    assert _play()["vars"]["reboot_force"] is False


def test_the_vps_is_refused_before_the_reboot_without_an_opt_in() -> None:
    guard = _index(lambda t: "fail" in t and any("'vps' in group_names" in w for w in _whens(t)))
    reboot = _index(lambda t: "reboot" in t)
    assert guard < reboot
    assert any("reboot_allow_vps" in w for w in _whens(_tasks()[guard]))
    assert _play()["vars"]["reboot_allow_vps"] is False


def test_the_guard_keys_on_a_group_the_generated_inventory_emits() -> None:
    """The guard reads `group_names`, which comes from the GENERATED inventory,
    not from the values file. A generator that renamed or dropped the group
    would make the Headscale refusal skip silently, so read what it emits."""
    from toolkit.features.generator_ansible import AnsibleGenerator

    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    prod = yaml.safe_load(PROD.read_text(encoding="utf-8"))
    for networking in (
        common["networking"],
        {**common["networking"], "vps": {**common["networking"]["vps"], **prod["networking"]["vps"]}},
    ):
        inventory = AnsibleGenerator()._build_inventory(
            networking, backup_sources=common.get("backup", {}).get("sources")
        )
        vps_group = inventory["all"]["children"].get("vps", {}).get("hosts") or {}
        hostname = networking["vps"].get("hostname", "kubelab-vps")
        assert set(vps_group) == {hostname}, (
            f"the `vps` group holds {sorted(vps_group)}, the guard needs exactly the VPS"
        )


def test_a_forced_reboot_takes_exactly_one_host() -> None:
    """`reboot_force` with a multi-host pattern (NODE=all) would reboot the fleet
    regardless of need. The refusal must run before the reboot."""
    guard = _index(lambda t: "fail" in t and any("ansible_play_hosts_all" in w for w in _whens(t)))
    reboot = _index(lambda t: "reboot" in t)
    assert guard < reboot
    assert any("reboot_force" in w for w in _whens(_tasks()[guard]))


def test_a_boot_that_leaves_the_flag_fails_the_run() -> None:
    reboot = _index(lambda t: "reboot" in t)
    after = _tasks()[reboot + 1 :]
    assert any(t.get("stat", {}).get("path") == "/var/run/reboot-required" for t in after)
    assert any("assert" in t for t in after)


def test_the_make_target_runs_this_playbook_with_a_limit() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "\nreboot:\n" in text
    recipe = text.split("\nreboot:\n", 1)[1].split("\n\n", 1)[0]
    assert "-p reboot" in recipe
    assert "-l $(NODE)" in recipe


def test_a_dry_run_does_not_fail_on_the_flag_it_could_not_clear() -> None:
    """CHECK=1 reboots nothing, so the post-boot check must not run there.
    Caught by the first dry run against the fleet: every host failed the assert."""
    reboot = _index(lambda t: "reboot" in t)
    for task in _tasks()[reboot + 1 :]:
        assert "not ansible_check_mode" in _whens(task), task["name"]
