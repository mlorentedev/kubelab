"""What the gateway role does, read from its task list (NET-005 AC1, AC4, AC6).

- The resolver is a template the role owns, not a `shell` task that reports
  `changed_when: false` whatever it did: that hid every rewrite from `changed=0`.
- ufw drops DHCP on `eth0` unless told otherwise, which is why the homelab LAN had
  no DHCP: delivered traffic must pass both ufw and `inet kubelab`.
- The ruleset is checked with `nft -c` before the handler loads it, since it loads
  over the LAN session that provisions the edge (ADR-075 D7).
- Strict `rp_filter` under a subnet router needs Tailscale 1.96.2 or later
  (tailscale/tailscale#18860), so the floor is asserted before the sysctls load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
HANDLERS: list[dict[str, Any]] = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())

TEMPLATE_MODULES = ("template", "ansible.builtin.template")


def _module(task: dict[str, Any], *names: str) -> dict[str, Any] | None:
    for name in names:
        if name in task:
            return task[name] if isinstance(task[name], dict) else {"_raw": task[name]}
    return None


def _template_task(dest: str) -> tuple[int, dict[str, Any]]:
    for index, task in enumerate(TASKS):
        args = _module(task, *TEMPLATE_MODULES)
        if args and args.get("dest") == dest:
            return index, task
    raise AssertionError(f"no template task writes {dest}")


def test_the_resolver_is_a_template_the_role_owns() -> None:
    _, task = _template_task("/etc/resolv.conf")
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True)
    rendered = env.get_template(task["template"]["src"]).render(gateway_dns_servers=DEFAULTS["gateway_dns_servers"])
    nameservers = [line.split()[1] for line in rendered.splitlines() if line.startswith("nameserver ")]
    assert nameservers == DEFAULTS["gateway_dns_servers"].split(",")


def test_no_shell_task_hides_its_changes() -> None:
    for task in TASKS:
        if _module(task, "shell", "ansible.builtin.shell") is not None:
            assert task.get("changed_when") is not False, task.get("name")


def test_ufw_lets_dhcp_in_on_the_homelab_lan() -> None:
    """`interface_in` implies inbound; the module refuses it next to `direction`."""
    rules = [_module(task, "community.general.ufw") or {} for task in TASKS]
    assert {
        "rule": "allow",
        "interface_in": "{{ gateway_interface }}",
        "proto": "udp",
        "port": "67",
    } in rules


def test_the_ruleset_is_checked_before_it_loads() -> None:
    _, task = _template_task("/etc/nftables.conf")
    assert task["template"].get("validate") == "nft -c -f %s"


def test_the_sysctls_reload_through_systemd_sysctl() -> None:
    _, task = _template_task("/etc/sysctl.d/99-kubelab-edge.conf")
    handler = next(h for h in HANDLERS if h["name"] == task["notify"])
    assert handler["systemd"] == {"name": "systemd-sysctl", "state": "restarted"}


def test_the_tailscale_floor_is_asserted_before_the_sysctls_load() -> None:
    assert DEFAULTS["gateway_tailscale_min_version"] == "1.96.2"
    sysctl_index, _ = _template_task("/etc/sysctl.d/99-kubelab-edge.conf")
    probe = next(i for i, task in enumerate(TASKS) if task.get("register") == "gateway_tailscale_version")
    check = next(i for i, task in enumerate(TASKS) if "gateway_tailscale_min_version" in str(task.get("assert")))
    assert probe < check < sysctl_index
    # A read-only probe: it must run under --check and must not fail on a node
    # where the tailscale role (later in the play) has not installed it yet.
    assert TASKS[probe]["check_mode"] is False
    assert TASKS[probe]["failed_when"] is False
    assert TASKS[probe]["changed_when"] is False


def test_the_ruleset_handler_reloads_and_never_restarts() -> None:
    """`nftables.service` stops with `flush ruleset`, which takes Docker's, ufw's and
    Tailscale's rules with it."""
    _, task = _template_task("/etc/nftables.conf")
    handler = next(h for h in HANDLERS if h["name"] == task["notify"])
    assert handler["systemd"] == {"name": "nftables", "state": "reloaded"}


def test_a_package_restart_only_replaces_the_edge_table() -> None:
    """The nftables postinst runs `try-restart` on upgrade (measured on the RPi4)."""
    _, task = _template_task("/etc/systemd/system/nftables.service.d/kubelab-stop.conf")
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True)
    lines = [
        line for line in env.get_template(task["template"]["src"]).render().splitlines() if not line.startswith("#")
    ]
    assert lines[lines.index("[Service]") + 1 :] == ["ExecStop=", "ExecStop=-/usr/sbin/nft delete table inet kubelab"]
    handler = next(h for h in HANDLERS if h["name"] == task["notify"])
    assert handler["systemd"] == {"daemon_reload": True}
    ruleset, _ = _template_task("/etc/nftables.conf")
    enable = next(i for i, t in enumerate(TASKS) if (t.get("systemd") or {}).get("name") == "nftables")
    drop_in, _ = _template_task("/etc/systemd/system/nftables.service.d/kubelab-stop.conf")
    assert drop_in < enable


def test_an_immutable_resolver_is_unlocked_before_the_template() -> None:
    """Older runbooks told the operator to `chattr +i` it, and `template` writes by rename."""
    resolver, _ = _template_task("/etc/resolv.conf")
    probe = next(i for i, t in enumerate(TASKS) if (t.get("stat") or {}).get("path") == "/etc/resolv.conf")
    unlock = next(i for i, t in enumerate(TASKS) if t.get("command") == "chattr -i /etc/resolv.conf")
    assert probe < unlock < resolver
    assert "immutable" in TASKS[unlock]["when"]
    assert TASKS[unlock]["changed_when"] is True


NETPLAN = "/etc/netplan/10-kubelab-edge.yaml"
LINK = "/etc/systemd/network/10-kubelab-uplink.link"


def _first(predicate: Any) -> int:
    return next(i for i, task in enumerate(TASKS) if predicate(task))


def test_the_drops_load_before_the_uplink_comes_up() -> None:
    """ADR-075 D7. A changed ruleset loads at handler time, so handlers flush between."""
    nftables, _ = _template_task("/etc/nftables.conf")
    netplan, _ = _template_task(NETPLAN)
    flushes = [i for i, task in enumerate(TASKS) if task.get("meta") == "flush_handlers"]
    assert any(nftables < i < netplan for i in flushes)


def test_the_profile_is_checked_before_anything_of_the_uplink_is_written() -> None:
    check = _first(lambda task: "gateway_uplink_kind" in str(task.get("assert")))
    link, _ = _template_task(LINK)
    netplan, _ = _template_task(NETPLAN)
    assert check < link < netplan


def test_the_netplan_file_is_private_and_checked_before_it_lands() -> None:
    """It holds the site SSID and PSK, and `--diff` would print it."""
    _, task = _template_task(NETPLAN)
    assert task["no_log"] is True
    assert task["template"]["mode"] == "0600"
    assert "netplan generate --root-dir" in task["template"]["validate"]


def test_the_link_file_is_private() -> None:
    """It holds the uplink adapter's MAC (ADR-075 C7)."""
    _, task = _template_task(LINK)
    assert task["no_log"] is True


def test_a_netplan_change_is_applied_and_the_session_awaited() -> None:
    """A profile that cuts the LAN fails the run visibly instead of passing."""
    _, task = _template_task(NETPLAN)
    notified = task["notify"] if isinstance(task["notify"], list) else [task["notify"]]
    apply = next(i for i, h in enumerate(HANDLERS) if h.get("command") == "netplan apply")
    wait = next(i for i, h in enumerate(HANDLERS) if "wait_for_connection" in h)
    assert apply < wait
    assert {HANDLERS[apply]["name"], HANDLERS[wait]["name"]} <= set(notified)


def test_hand_written_netplan_is_backed_up_then_removed() -> None:
    """The role owns /etc/netplan. The old file can hold a PSK, so its copy stays root-only."""
    find = _first(lambda task: (task.get("find") or {}).get("paths") == "/etc/netplan")
    assert NETPLAN.rsplit("/", 1)[1] in TASKS[find]["find"]["excludes"]
    backup = _first(lambda task: (task.get("copy") or {}).get("remote_src") is True)
    assert TASKS[backup]["copy"]["mode"] == "0600"
    assert TASKS[backup]["no_log"] is True
    remove = _first(lambda task: (task.get("file") or {}).get("state") == "absent" and "loop" in task)
    # Removed only once the role's own file has passed netplan's check and landed.
    netplan, _ = _template_task(NETPLAN)
    assert netplan < find < backup < remove


def test_cloud_init_never_writes_netplan() -> None:
    task = TASKS[_first(lambda task: (task.get("copy") or {}).get("dest", "").startswith("/etc/cloud/"))]
    assert yaml.safe_load(task["copy"]["content"]) == {"network": {"config": "disabled"}}
