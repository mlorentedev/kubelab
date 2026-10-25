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

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
HANDLERS: list[dict[str, Any]] = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
NODES = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]["nodes"]

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


def _tailscale_check() -> tuple[int, int, str]:
    facts = next(
        i for i, task in enumerate(TASKS) if "package_facts" in task or "ansible.builtin.package_facts" in task
    )
    check = next(i for i, task in enumerate(TASKS) if "gateway_tailscale_min_version" in str(task.get("assert")))
    return facts, check, TASKS[check]["assert"]["that"]


def test_the_tailscale_floor_is_asserted_before_the_sysctls_load() -> None:
    """The version comes from dpkg, not from running the binary: a binary that fails
    to run would read as absent, and absent is the one case let through."""
    assert DEFAULTS["gateway_tailscale_min_version"] == "1.96.2"
    sysctl_index, _ = _template_task("/etc/sysctl.d/99-kubelab-edge.conf")
    facts, check, _ = _tailscale_check()
    assert facts < check < sysctl_index
    assert not any(task.get("register") == "gateway_tailscale_version" for task in TASKS)


@pytest.mark.parametrize(
    ("packages", "passes"),
    [
        ({}, True),
        ({"tailscale": [{"version": "1.96.1"}]}, False),
        ({"tailscale": [{"version": "1.96.2"}]}, True),
        ({"tailscale": [{"version": "1.102.4"}]}, True),
    ],
    ids=["absent", "below-the-floor", "at-the-floor", "installed-on-the-edge"],
)
def test_the_tailscale_floor_lets_only_an_absent_or_current_package_through(packages, passes) -> None:
    """Absent passes: the tailscale role installs a current one later in the play."""
    _, _, condition = _tailscale_check()
    env = ansible_env(str(ROLE / "templates"))
    result = env.compile_expression(condition)(
        ansible_facts={"packages": packages}, gateway_tailscale_min_version=DEFAULTS["gateway_tailscale_min_version"]
    )
    assert bool(result) is passes


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


def test_no_other_role_writes_the_edges_netplan() -> None:
    """base_system writes /etc/netplan/50-cloud-init.yaml when netplan_address is set.
    On the edge, this role would then back it up and remove it on every run, and the
    two would apply netplan against each other."""
    playbook = REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml"
    assert "netplan_" not in playbook.read_text()


def _that(index: int) -> list[str]:
    that = TASKS[index]["assert"]["that"]
    return that if isinstance(that, list) else [that]


def _holds(index: int, **variables: Any) -> bool:
    env = ansible_env(str(ROLE / "templates"))
    return all(env.compile_expression(check)(**variables) for check in _that(index))


def test_the_profile_check_names_every_key_it_checks() -> None:
    """A bad kind or regdomain is a common.yaml edit, not a missing secret."""
    check = _first(lambda task: "gateway_uplink_kind" in str(task.get("assert")))
    message = TASKS[check]["assert"]["fail_msg"]
    assert all(key in message for key in ("kind", "regdomain", ".mac", ".ssid", ".psk", "common.yaml"))


def test_edge_changes_run_over_the_homelab_lan() -> None:
    """ADR-075 D7. Over the tailnet, applying the uplink can cut the session that applies it."""
    check = _first(lambda task: "ansible_host" in str(task.get("assert")))
    link, _ = _template_task(LINK)
    assert check < link
    lan = {"gateway_lan_cidr": f"{NODES['rpi4']['lan_ip']}/24"}
    assert _holds(check, ansible_host=NODES["rpi4"]["lan_ip"], **lan)
    assert not _holds(check, ansible_host=NODES["rpi4"]["tailscale_ip"], **lan)


UPLINK_MAC = "02:00:5e:10:00:01"
LINKS = "lo UNKNOWN 00:00:00:00:00:00\neth0 UP 02:00:5e:10:00:09\nwlx02005e100001 DOWN 02:00:5e:10:00:01\n"


@pytest.mark.parametrize(
    ("mac", "links", "eth0", "ok"),
    [
        (UPLINK_MAC, LINKS, "02:00:5e:10:00:09", True),
        (UPLINK_MAC.upper(), LINKS, "02:00:5e:10:00:09", True),
        (UPLINK_MAC, LINKS.replace("02:00:5e:10:00:01", "02:00:5e:10:00:02"), "02:00:5e:10:00:09", False),
        ("02:00:5e:10:00:09", LINKS, "02:00:5e:10:00:09", False),
    ],
    ids=["present", "upper-case-in-sops", "unplugged", "is-the-lan-port"],
)
def test_the_uplink_adapter_must_be_present_and_not_the_lan_port(mac: str, links: str, eth0: str, ok: bool) -> None:
    """Without it, netplan waits on a device that never appears and fails without a cause.
    On the LAN port, the next boot would rename the recovery path."""
    read = _first(lambda task: task.get("command") == "ip -br link")
    check = _first(lambda task: "gateway_uplink_links" in str(task.get("assert")))
    link, _ = _template_task(LINK)
    assert read < check < link
    assert (TASKS[read]["changed_when"], TASKS[read]["check_mode"], TASKS[read]["no_log"]) == (False, False, True)
    facts = {"eth0": {"macaddress": eth0}}
    variables = {"gateway_uplink_mac": mac, "gateway_interface": "eth0", "ansible_facts": facts}
    assert _holds(check, gateway_uplink_links={"stdout": links}, **variables) is ok


def test_the_rename_runs_whenever_the_name_is_missing_and_is_checked() -> None:
    """A handler would fire only when the .link file changes, so a run that failed after
    writing it would never rename. udevadm exits 0 when nothing matched, and the kernel
    refuses to rename an interface that is up, so the name itself is checked."""
    link, _ = _template_task(LINK)
    reload = _first(lambda task: task.get("command") == "udevadm control --reload")
    rename = _first(lambda task: "udevadm trigger" in str(task.get("command")))
    verify = _first(lambda task: "gateway_uplink_sysfs" in str(task.get("assert")))
    netplan, _ = _template_task(NETPLAN)
    assert link < reload < rename < verify < netplan
    missing = "gateway_uplink_interface not in ansible_facts.interfaces"
    assert missing in str(TASKS[reload]["when"])
    assert TASKS[rename]["when"] == missing
    assert "--settle" in TASKS[rename]["command"]
    assert "address={{ gateway_uplink_mac | lower }}" in TASKS[rename]["command"]
    assert TASKS[rename]["no_log"] is True
    assert not any("udevadm" in str(handler) for handler in HANDLERS)


def test_old_and_new_netplan_are_never_applied_together() -> None:
    netplan, _ = _template_task(NETPLAN)
    remove = _first(lambda task: (task.get("file") or {}).get("state") == "absent" and "loop" in task)
    flushes = [i for i, task in enumerate(TASKS) if task.get("meta") == "flush_handlers"]
    assert not any(netplan < i < remove for i in flushes)
    assert any(i > remove for i in flushes)
    notified = TASKS[remove]["notify"]
    assert {"apply netplan", "wait for the session"} <= set(notified)


def test_the_netplan_backups_stay_private_and_are_never_overwritten() -> None:
    directory = _first(lambda task: (task.get("file") or {}).get("path") == "/var/backups/kubelab-netplan")
    assert TASKS[directory]["file"]["mode"] == "0700"
    backup = _first(lambda task: (task.get("copy") or {}).get("remote_src") is True)
    assert "date_time" in TASKS[backup]["copy"]["dest"]
