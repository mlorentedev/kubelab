"""`make maintain NODE=all` can exit 0, and its recap carries no expected noise (#2407).

Two things made every `NODE=all` run read red or noisy on 2026-10-17:

- The Jetson Nano runs Python 3.6, which cannot run Ansible's `setup` module, so
  fact gathering failed there and the run exited 2 on every invocation. The
  host is already declared `legacy_python: true` in `common.yaml`; the play now
  ends that host before gathering facts, so the exclusion follows the
  declaration rather than a hostname.
- `snap get/set system refresh.retain` ran on nodes without snapd (kubelab-vps,
  rpi3) and failed with "No such file or directory", an `ignored=1` per task in
  every recap. A reader taught that the ignored column is noise stops reading it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
PLAYBOOK = REPO / "infra/ansible/playbooks/maintain.yml"
ROLE_TASKS = REPO / "infra/ansible/roles/node_maintenance/tasks/main.yml"
COMMON = REPO / "infra/config/values/common.yaml"


def _play() -> dict:
    return yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]


def test_the_jetson_is_declared_legacy_python() -> None:
    """The exclusion below keys on this declaration, so it must exist."""
    nodes = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]["nodes"]
    assert nodes["jetson"].get("legacy_python") is True


def test_the_generated_inventory_carries_legacy_python_as_a_host_var() -> None:
    """The play reads `legacy_python` as a host var. It reaches the play only
    through the generated inventory, so the declaration alone proves nothing."""
    from toolkit.features.generator_ansible import AnsibleGenerator

    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    # Built as if the Jetson were back: while it is `retired` no host carries
    # the var, and this asks whether the generator passes it through.
    common["networking"]["nodes"]["jetson"].pop("retired", None)
    inventory = AnsibleGenerator()._build_inventory(
        common["networking"], backup_sources=common.get("backup", {}).get("sources")
    )
    host_vars = {
        host: hvars
        for group in inventory["all"]["children"].values()
        for host, hvars in (group.get("hosts") or {}).items()
    }
    jetson = common["networking"]["nodes"]["jetson"]
    hostname = jetson.get("hostname", "jetson")

    assert host_vars[hostname].get("legacy_python") is True, (
        "the inventory drops legacy_python, so the play gathers facts there"
    )
    flagged = {h for h, v in host_vars.items() if v.get("legacy_python")}
    assert flagged == {hostname}, f"legacy_python reaches hosts that never declared it: {flagged - {hostname}}"


def test_a_legacy_python_host_ends_before_any_module_runs() -> None:
    play = _play()
    assert play.get("gather_facts") is False, (
        "facts are gathered before any task can skip the host, so a legacy_python host fails the run"
    )
    first = play["pre_tasks"][0]
    assert first.get("meta") == "end_host", "the first pre_task must end the host before any module runs on it"
    assert "legacy_python" in str(first.get("when", "")), "the exclusion must follow the inventory declaration"


def test_facts_are_gathered_explicitly_before_the_roles() -> None:
    """The roles read `ansible_facts` (pkg_mgr, distribution_release); turning off
    the play-level gathering must not leave them without facts."""
    names = [next(iter(k for k in t if k not in ("name", "when", "tags"))) for t in _play()["pre_tasks"]]
    assert any(m in ("setup", "ansible.builtin.setup") for m in names), "no explicit setup after the legacy exit"


def test_the_exclusion_names_no_host() -> None:
    # Parsed, so comments (which may name the host to explain it) are not code.
    text = str(_play()).lower()
    assert "jetson" not in text and "jet1" not in text, "the exclusion names a host instead of reading its declaration"


def test_every_snap_command_is_gated_on_snapd_being_present() -> None:
    tasks = yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8"))
    snap_tasks = [t for t in tasks if "snap " in str(t.get("command", "")) + str(t.get("shell", ""))]
    assert snap_tasks, "the role no longer runs snap at all; update this guard"
    probe = next((t for t in tasks if "stat" in t and "snap" in str(t["stat"].get("path", ""))), None)
    assert probe is not None, "nothing checks whether snapd is installed"
    register = probe["register"]
    ungated = [t["name"] for t in snap_tasks if f"{register}.stat.exists" not in str(t.get("when", ""))]
    assert not ungated, f"these snap tasks run on nodes without snapd: {ungated}"
