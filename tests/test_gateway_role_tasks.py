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

import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env, task_runs

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
HANDLERS: list[dict[str, Any]] = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
NODES = NETWORKING["nodes"]
EDGE = {name for name, node in NODES.items() if "gateway" in ((node or {}).get("ansible_groups") or [])}
ANSIBLE = REPO / "infra" / "ansible"

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


def _netplan_keys(node: Any) -> set[str]:
    """Every `netplan_*` key at any depth: keys, so a comment that names one is not a hit."""
    if isinstance(node, dict):
        own = {str(key) for key in node if str(key).startswith("netplan_")}
        return own.union(*(_netplan_keys(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_netplan_keys(item) for item in node))
    return set()


def test_no_other_role_writes_the_edges_netplan() -> None:
    """base_system writes /etc/netplan/50-cloud-init.yaml when netplan_address is set.
    On the edge, this role would then back it up and remove it on every run, and the
    two would apply netplan against each other. So only a play aimed at named nodes
    other than the edge may set a `netplan_` variable, and no source that every host
    reads may: a role's defaults or vars, an inventory, group_vars, host_vars."""
    base_system = yaml.safe_load((ANSIBLE / "roles" / "base_system" / "tasks" / "main.yml").read_text())
    (gate,) = [task["when"] for task in base_system if "/etc/netplan/" in str(task)]
    assert gate == "netplan_address is defined"
    others = set(NODES) - EDGE
    for playbook in sorted((ANSIBLE / "playbooks").glob("*.yml")):
        for play in yaml.safe_load(playbook.read_text()) or []:
            if isinstance(play, dict) and (keys := _netplan_keys(play)):
                hosts = set(re.split(r"[,:]", str(play.get("hosts", ""))))
                assert hosts <= others, f"{playbook.name}: the play on {play.get('hosts')!r} sets {sorted(keys)}"
    shared = [
        path
        for pattern in (
            "roles/*/defaults/*",
            "roles/*/vars/*",
            "inventories/**/*",
            "**/group_vars/**/*",
            "**/host_vars/**/*",
        )
        for path in ANSIBLE.glob(pattern)
        if path.suffix in (".yml", ".yaml")
    ]
    assert shared, "no shared variable source found: the glob is wrong, not the edge clean"
    for source in shared:
        for document in yaml.safe_load_all(source.read_text()):
            assert not _netplan_keys(document), f"{source.relative_to(REPO)} sets {sorted(_netplan_keys(document))}"


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


EDGE_PLAY_FILE = ANSIBLE / "playbooks" / "provision-rpi4.yml"
CONTROLLER_SIDE = ("include_vars", "set_fact")


def _edge_play() -> dict[str, Any]:
    plays = yaml.safe_load(EDGE_PLAY_FILE.read_text())
    return next(p for p in plays if any(str(r.get("role", "")).endswith("/gateway") for r in p.get("roles", [])))


def _lan_guard() -> tuple[int, dict[str, Any]]:
    tasks = _edge_play().get("pre_tasks", [])
    return next((i, t) for i, t in enumerate(tasks) if "ansible_host" in str(t.get("assert")))


def _guard_holds(ansible_host: str) -> bool:
    _, guard = _lan_guard()
    that = guard["assert"]["that"]
    env = ansible_env(".")
    config = {"networking": {"nodes": {"rpi4": NODES["rpi4"]}}}
    return all(
        env.compile_expression(check)(ansible_host=ansible_host, config=config)
        for check in (that if isinstance(that, list) else [that])
    )


def test_edge_changes_run_over_the_homelab_lan() -> None:
    """ADR-075 D7. Over the tailnet, applying the uplink can cut the session that applies it."""
    assert _guard_holds(NODES["rpi4"]["lan_ip"])
    assert not _guard_holds(NODES["rpi4"]["tailscale_ip"])


def test_a_run_over_the_tailnet_is_refused_before_anything_changes() -> None:
    """#2775. In the role, the guard refused only after earlier roles had changed the edge.
    A pre_task runs before every role, and each one before it runs on the controller."""
    index, guard = _lan_guard()
    assert "always" in guard.get("tags", []), guard
    before = _edge_play()["pre_tasks"][:index]
    assert all(
        any(module in task for module in CONTROLLER_SIDE) or task.get("delegate_to") == "localhost" for task in before
    ), [task.get("name") for task in before]


@pytest.mark.parametrize(
    ("run", "skip", "guarded"),
    [
        (["all"], [], True),
        (["gateway"], [], True),
        (["tagged"], [], True),
        (["all"], ["gateway"], False),
        (["ssh"], [], False),
    ],
)
def test_the_guard_covers_every_run_that_applies_the_gateway(run: list[str], skip: list[str], guarded: bool) -> None:
    """The scope the role's own assert had: a run that leaves the gateway role out changes no uplink."""
    _, guard = _lan_guard()
    assert task_runs(guard, {"ansible_run_tags": run, "ansible_skip_tags": skip}) is guarded


ROUTE_SOURCE = ANSIBLE / "playbooks" / "files" / "route-source.py"


def _route_source(destination: str, tailnet: str) -> dict[str, Any]:
    out = subprocess.run([sys.executable, str(ROUTE_SOURCE), destination, tailnet], capture_output=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize(("tailnet", "on_it"), [(NETWORKING["tailscale_cidr"], False), ("127.0.0.0/8", True)])
def test_the_path_is_read_from_the_source_address_the_kernel_picks(tailnet: str, on_it: bool) -> None:
    assert _route_source("127.0.0.1", tailnet) == {"source": "127.0.0.1", "tailnet": on_it}


def _route_guard() -> tuple[int, dict[str, Any], int, dict[str, Any]]:
    tasks = _edge_play().get("pre_tasks", [])
    read = next(i for i, t in enumerate(tasks) if "route-source.py" in str(t))
    check = next(i for i, t in enumerate(tasks) if "_edge_route" in str(t.get("assert")))
    return read, tasks[read], check, tasks[check]


def _route_holds(tailnet: bool) -> bool:
    _, _, _, guard = _route_guard()
    that = guard["assert"]["that"]
    env = ansible_env(".")
    route = {"stdout": json.dumps({"source": "192.0.2.10", "tailnet": tailnet})}
    return all(
        env.compile_expression(check)(_edge_route=route) for check in (that if isinstance(that, list) else [that])
    )


def test_a_run_whose_packets_ride_the_tailnet_is_refused() -> None:
    """#2801. The address check passed while the session rode the tailnet: the
    controller accepted the edge's subnet route, which Tailscale looks up first."""
    assert _route_holds(tailnet=False)
    assert not _route_holds(tailnet=True)


def test_the_path_is_read_on_the_controller_before_any_role() -> None:
    address, _ = _lan_guard()
    read, read_task, check, check_task = _route_guard()
    assert address < read < check, (address, read, check)
    assert read_task.get("delegate_to") == "localhost"
    assert read_task.get("become") is False
    assert read_task.get("check_mode") is False, "a dry run must refuse the same path"
    _, address_task = _lan_guard()
    for task in (read_task, check_task):
        assert "always" in task.get("tags", []), task.get("name")
        assert task.get("when") == address_task.get("when"), task.get("name")


def test_the_refusal_names_the_way_out() -> None:
    _, _, _, guard = _route_guard()
    message = guard["assert"]["fail_msg"]
    assert all(part in message for part in ("ERROR:", "WHY:", "FIX:", "make edge-lan-link", "--accept-routes=false"))


def test_the_role_keeps_no_second_copy_of_the_guard() -> None:
    assert not [task.get("name") for task in TASKS if "ansible_host" in str(task.get("assert"))]


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


NAMED = (
    "5: uplink0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000"
    "\\    link/ether 02:00:5e:10:00:01 brd ff:ff:ff:ff:ff:ff\n"
)


@pytest.mark.parametrize(
    ("exists", "named", "ok"),
    [
        (True, NAMED, True),
        (True, NAMED.replace("02:00:5e:10:00:01", "02:00:5e:10:00:02"), False),
        (False, "", True),
    ],
    ids=["the-uplink", "another-adapter", "no-name-yet-in-check-mode"],
)
def test_the_uplink_name_must_be_on_the_uplink_adapter(exists: bool, named: str, ok: bool) -> None:
    """An adapter an earlier profile named keeps the name while it stays plugged in, and
    the rename is skipped because the name is taken: netplan would configure it."""
    verify = _first(lambda task: "gateway_uplink_sysfs" in str(task.get("assert")))
    read = _first(lambda task: str(task.get("command")).startswith("ip -o link show"))
    owner = _first(lambda task: "gateway_uplink_named" in str(task.get("assert")))
    netplan, _ = _template_task(NETPLAN)
    assert verify < read < owner < netplan
    task = TASKS[read]
    assert task["command"] == "ip -o link show {{ gateway_uplink_interface }}"
    assert (task["changed_when"], task["check_mode"], task["no_log"]) == (False, False, True)
    assert task["when"] == "gateway_uplink_sysfs.stat.exists"
    variables = {"gateway_uplink_mac": UPLINK_MAC.upper(), "gateway_uplink_sysfs": {"stat": {"exists": exists}}}
    named_result = {"stdout": named} if exists else {"skipped": True}
    assert _holds(owner, gateway_uplink_named=named_result, **variables) is ok
    assert TASKS[owner]["assert"]["fail_msg"].startswith("ERROR:")


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


# --- the lab Wi-Fi AP (NET-005 AC2, ADR-075 D2) ------------------------------------

HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
PSK_FILE = "/etc/hostapd/hostapd.wpa_psk"
AP_UNIT = "/etc/systemd/network/10-kubelab-ap.network"
AP_SUPPLICANTS = ["netplan-wpa-{{ gateway_ap_interface }}.service", "wpa_supplicant.service"]


def _ap_install() -> int:
    return _first(lambda task: "hostapd" in str((task.get("block") or [{}])[0].get("apt")))


def _hostapd_start() -> int:
    return _first(lambda task: (task.get("systemd") or {}).get("name") == "hostapd")


def test_the_ap_packages_install_once_the_uplink_is_applied() -> None:
    """At a portal site the archive answers only after the login, so this is where a run
    before the login stops, and nothing of the AP lands half-done."""
    remove = _first(lambda task: (task.get("file") or {}).get("state") == "absent" and "loop" in task)
    applied = next(i for i, task in enumerate(TASKS) if i > remove and task.get("meta") == "flush_handlers")
    install = _ap_install()
    assert applied < install
    assert TASKS[install]["block"][0]["apt"]["name"] == ["hostapd", "iw"]
    dnsmasq, _ = _template_task("/etc/dnsmasq.d/kubelab-dhcp.conf")
    assert install < dnsmasq


def test_a_failed_install_says_what_to_do_and_quotes_apt() -> None:
    rescue = TASKS[_ap_install()]["rescue"][0]["rescue"]
    message = " ".join(task["fail"]["msg"] for task in rescue if "fail" in task)
    assert all(word in message for word in ("ERROR:", "WHY:", "FIX:", "B4"))
    assert "ansible_failed_result.msg" in message


def test_the_lab_secrets_are_checked_before_anything_of_the_ap_is_installed() -> None:
    check = _first(lambda task: "gateway_ap_psks" in str(task.get("assert")))
    assert check < _ap_install()


def test_the_regdomain_is_checked_after_the_install_and_before_hostapd_starts() -> None:
    """After the install, so a run before the portal login stops at the install (B2)."""
    check = _first(lambda task: "ieee80211_regdom" in str(task.get("assert")))
    assert _ap_install() < check < _hostapd_start()


def test_the_parameter_the_gateway_refuses_is_the_one_the_edge_play_removes() -> None:
    """rpi_boot runs first in the same play and removes it (#2668). Two spellings would
    leave the gateway refusing a command line that nothing ever cleans."""
    check = TASKS[_first(lambda task: "ieee80211_regdom" in str(task.get("assert")))]
    (pattern,) = re.findall(r"select\('match', '([^']+)'\)", check["assert"]["that"])
    plays = yaml.safe_load((ANSIBLE / "playbooks" / "provision-rpi4.yml").read_text())
    (boot,) = [r for p in plays for r in p.get("roles") or [] if str(r.get("role", "")).endswith("/rpi_boot")]
    assert [name for name in boot["vars"]["rpi_boot_absent_params"] if re.match(pattern, f"{name}=US")]


def test_the_supplicants_are_masked_and_stopped_by_exact_name_before_hostapd_starts() -> None:
    """A glob would also match the uplink's supplicant, `netplan-wpa-uplink0`."""
    mask = _first(lambda task: task.get("loop") == AP_SUPPLICANTS and task["systemd"].get("masked") is True)
    stop = _first(lambda task: task.get("loop") == AP_SUPPLICANTS and task["systemd"].get("state") == "stopped")
    assert TASKS[stop]["systemd"]["enabled"] is False
    assert not any("*" in name for name in AP_SUPPLICANTS)
    assert mask < stop < _hostapd_start()


def test_stopping_a_supplicant_is_gated_on_it_existing() -> None:
    """The systemd module fails on a stop of a unit that does not exist; it can mask one."""
    facts = _first(lambda task: "service_facts" in task)
    stop = _first(lambda task: task.get("loop") == AP_SUPPLICANTS and task["systemd"].get("state") == "stopped")
    assert facts < stop
    assert TASKS[stop]["when"] == "item in ansible_facts.services"


def test_hostapd_is_unmasked_enabled_and_started() -> None:
    """The package masks it when it installs without a config."""
    task = TASKS[_hostapd_start()]["systemd"]
    assert (task["masked"], task["enabled"], task["state"]) == (False, True, "started")
    for dest in (HOSTAPD_CONF, PSK_FILE, AP_UNIT):
        index, _ = _template_task(dest)
        assert index < _hostapd_start()


@pytest.mark.parametrize("dest", [HOSTAPD_CONF, PSK_FILE])
def test_the_ap_files_are_private(dest: str) -> None:
    """The config holds the lab SSID and the PSK file the passphrases; `--diff` would print both."""
    _, task = _template_task(dest)
    assert task["no_log"] is True
    assert task["template"]["mode"] == "0600"


def test_a_psk_change_reloads_and_a_config_change_restarts() -> None:
    """A reload keeps every station associated (D8). After a restart, the reload is skipped:
    the restart already read the file, and its control socket may not be up yet."""
    _, psks = _template_task(PSK_FILE)
    _, conf = _template_task(HOSTAPD_CONF)
    reload = next(h for h in HANDLERS if "reload_wpa_psk" in str(h.get("command")))
    restart = next(h for h in HANDLERS if (h.get("systemd") or {}).get("name") == "hostapd")
    assert psks["notify"] == reload["name"]
    assert conf["notify"] == restart["name"]
    assert restart["systemd"]["state"] == "restarted"
    assert reload["when"] == f"{conf['register']} is not changed"
    assert HANDLERS.index(restart) < HANDLERS.index(reload)


def _address_apply() -> int:
    return _first(lambda task: "networkctl reconfigure" in str(task.get("loop") or task.get("command")))


def test_the_ap_address_is_applied_before_hostapd_starts() -> None:
    """Applied by a task, not a handler: a handler deferred to the end of the play is lost
    when a later role fails, and the re-run then reports `changed=0` with no address."""
    unit, task = _template_task(AP_UNIT)
    assert "notify" not in task
    read = _first(lambda t: "ip -4 -br addr show dev {{ gateway_ap_interface }}" in str(t.get("command")))
    assert unit < _address_apply() < _hostapd_start()
    assert read < _address_apply()
    assert TASKS[read]["changed_when"] is False
    assert TASKS[read]["failed_when"] is False
    assert TASKS[read]["check_mode"] is False
    assert TASKS[_address_apply()]["loop"] == ["networkctl reload", "networkctl reconfigure {{ gateway_ap_interface }}"]
    assert not any(h["name"] == "reload networkd" for h in HANDLERS)


LAB_NET = ipaddress.ip_network(NETWORKING["edge"]["lab_wifi"]["cidr"])
LAB_GATEWAY = NETWORKING["edge"]["lab_wifi"]["gateway"]
LAB_OTHER = str(ipaddress.ip_address(LAB_GATEWAY) + 9)


@pytest.mark.parametrize(
    ("changed", "stdout", "applies"),
    [
        (True, f"wlan0 UP {LAB_GATEWAY}/{LAB_NET.prefixlen}", True),
        (False, "", True),
        (False, "wlan0 DOWN ", True),
        (False, f"wlan0 UP {LAB_OTHER}/{LAB_NET.prefixlen}", True),
        (False, f"wlan0 UP {LAB_GATEWAY}/{LAB_NET.prefixlen}", False),
    ],
    ids=["unit-changed", "no-interface", "no-address", "another-address", "in-place"],
)
def test_the_ap_address_is_applied_whenever_it_is_not_in_place(changed: bool, stdout: str, applies: bool) -> None:
    task = TASKS[_address_apply()]
    unit_register = _template_task(AP_UNIT)[1]["register"]
    read_register = TASKS[_first(lambda t: "ip -4 -br addr" in str(t.get("command")))]["register"]
    env = ansible_env(str(ROLE / "templates"))
    variables = {
        unit_register: {"changed": changed},
        read_register: {"stdout": stdout},
        "gateway_ap_address": LAB_GATEWAY,
        "gateway_ap_cidr": str(LAB_NET),
    }
    # Ansible's `is changed` reads the result's `changed` key.
    env.tests["changed"] = lambda result: bool(result.get("changed"))
    assert bool(env.compile_expression(task["when"])(**variables)) is applies


def test_the_ap_handlers_run_inside_the_role() -> None:
    """A play-level `force_handlers` would reorder the uplink's netplan handlers, so the
    role flushes its own after the last task that notifies one."""
    flush = [i for i, task in enumerate(TASKS) if task.get("meta") == "flush_handlers"]
    last_notify = max(i for i, task in enumerate(TASKS) if "notify" in task)
    assert any(i > last_notify for i in flush)
    plays = yaml.safe_load((REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml").read_text())
    assert not any("force_handlers" in play for play in plays)


def _in_order(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for task in tasks:
        flat.append(task)
        for section in ("block", "rescue", "always"):
            flat.extend(_in_order(task.get(section) or []))
    return flat


def test_no_check_runs_between_a_notify_and_its_flush() -> None:
    """A failed check ends the play and drops the handlers already notified, and on the
    re-run the unchanged files notify nothing, so the change is never applied
    (lesson-620). Any task can fail; a check that reads only inputs and facts is the
    one that can always run before the first file it guards is written."""
    pending: list[str] = []
    for task in _in_order(TASKS):
        if task.get("meta") == "flush_handlers":
            pending = []
        elif "assert" in task or "fail" in task:
            assert not pending, f"{task['name']!r} can fail after {pending} notified a handler"
        elif "notify" in task:
            pending.append(task["name"])


def test_the_ap_starts_in_check_mode_only_where_the_package_is_installed() -> None:
    assert TASKS[_hostapd_start()]["when"] == "not ansible_check_mode or 'hostapd.service' in ansible_facts.services"


def _regdomain_set() -> int:
    return _first(lambda task: "iw reg set" in str(task.get("command")))


def test_the_regulatory_domain_is_persisted_and_set_before_hostapd_starts() -> None:
    """modprobe.d reaches cfg80211 only when the module loads, which is boot here: the
    module is built into no initramfs and is loaded already."""
    persist = _first(lambda task: (task.get("copy") or {}).get("dest", "").startswith("/etc/modprobe.d/"))
    read = _first(lambda task: str(task.get("command")) == "iw reg get")
    assert persist < _hostapd_start()
    assert read < _regdomain_set() < _hostapd_start()
    assert TASKS[read]["changed_when"] is False
    assert TASKS[read]["check_mode"] is False
    assert TASKS[_regdomain_set()]["command"] == "iw reg set {{ gateway_uplink_regdomain }}"


@pytest.mark.parametrize(
    ("stdout", "sets"),
    [
        ("global\ncountry US: DFS-FCC\n\t(2402 - 2472 @ 40), (N/A, 30), (N/A)", False),
        ("global\ncountry ES: DFS-ETSI\n\t(2400 - 2483 @ 40), (N/A, 20), (N/A)", True),
        ("global\ncountry 00: DFS-UNSET\n", True),
        ("phy#0\ncountry US: DFS-FCC\n", True),
        ("", True),
    ],
    ids=["in-force", "another-country", "world", "only-a-phy", "unreadable"],
)
def test_the_regulatory_domain_is_set_whenever_it_is_not_in_force(stdout: str, sets: bool) -> None:
    task = TASKS[_regdomain_set()]
    read = TASKS[_first(lambda t: str(t.get("command")) == "iw reg get")]["register"]
    env = ansible_env(str(ROLE / "templates"))
    variables = {read: {"stdout": stdout, "stdout_lines": stdout.splitlines()}, "gateway_uplink_regdomain": "US"}
    assert "\\n" not in task["when"]
    assert bool(env.compile_expression(task["when"])(**variables)) is sets


@pytest.mark.parametrize(
    ("rc", "lines", "fails"),
    [
        (0, ["OK"], False),
        (0, ["Selected interface 'wlan0'", "OK"], False),
        (0, ["FAIL"], True),
        (0, [], True),
        (255, ["Failed to connect to hostapd - wpa_ctrl_open: No such file or directory"], True),
    ],
    ids=["ok", "ok-after-banner", "fail-reply", "no-reply", "no-socket"],
)
def test_a_psk_reload_that_hostapd_refuses_fails_the_run(rc: int, lines: list[str], fails: bool) -> None:
    """hostapd_cli exits 0 on a FAIL reply, so the rc alone would pass a refused reload."""
    handler = next(h for h in HANDLERS if "reload_wpa_psk" in str(h.get("command")))
    env = ansible_env(str(ROLE / "templates"))
    result = {"rc": rc, "stdout_lines": lines}
    assert bool(env.compile_expression(handler["failed_when"])(**{handler["register"]: result})) is fails


def test_installed_packages_need_no_package_archive() -> None:
    """A re-run after the portal's login expired must not stop on an index refresh it does not need."""
    apt = TASKS[_ap_install()]["block"][0]["apt"]
    assert not apt.get("update_cache")


def test_a_stale_index_is_refreshed_before_the_run_gives_up() -> None:
    """The image's index is as old as the image; a stale one asks for files the mirror dropped."""
    install = TASKS[_ap_install()]
    retry = install["rescue"][0]["block"][0]["apt"]
    assert retry["update_cache"] is True
    assert retry["name"] == install["block"][0]["apt"]["name"]


def test_ufw_lets_dhcp_in_on_the_lab_wifi() -> None:
    rules = [_module(task, "community.general.ufw") or {} for task in TASKS]
    assert {
        "rule": "allow",
        "interface_in": "{{ gateway_ap_interface }}",
        "proto": "udp",
        "port": "67",
    } in rules


def _units() -> dict[str, str]:
    """Every unit the role writes under /etc/systemd/system, by name, with its template's text."""
    units: dict[str, str] = {}
    for task in _in_order(TASKS):
        args = _module(task, *TEMPLATE_MODULES)
        if not args or not str(args.get("dest", "")).startswith("/etc/systemd/system/"):
            continue
        for item in task.get("loop") or [""]:
            name = str(args["dest"]).replace("{{ item }}", item).rsplit("/", 1)[1]
            units[name] = (ROLE / "templates" / str(args["src"]).replace("{{ item }}", item)).read_text()
    return units


def _section(unit: str, name: str) -> list[str]:
    """The lines of one section of a unit file."""
    lines: list[str] = []
    current = None
    for line in unit.splitlines():
        if line.startswith("["):
            current = line.strip()
        elif current == f"[{name}]":
            lines.append(line.strip())
    return lines


NOTIFY = "kubelab-notify@%n.service"
PAGE = "KUBELAB_NOTIFY_SEVERITY=page"


def test_only_the_lease_check_and_the_liveness_units_page() -> None:
    """A lease inside a lab network (ADR-075 D6) and a radio the edge's own reboot did not
    bring back need a person now. The shaper logs: without it the uplink is unshaped, not
    down (#2684).

    systemd reads `Environment=` only in [Service] and ignores it elsewhere, so the
    declaration is looked for there and nowhere else.
    """
    units = _units()
    notifying = {name for name, unit in units.items() if f"OnFailure={NOTIFY}" in _section(unit, "Unit")}
    paging = {name for name, unit in units.items() if f"Environment={PAGE}" in _section(unit, "Service")}
    assert "kubelab-edge-shaper.service" in notifying, "the shaper no longer notifies: the derivation is wrong"
    assert paging == {"kubelab-edge-lease-check.service", "kubelab-edge-liveness.service"}
    assert paging <= notifying, "a unit declares page but nothing notifies on its failure"


def _task(name: str) -> dict[str, Any]:
    return next(task for task in TASKS if task.get("name") == name)


@pytest.mark.parametrize(
    ("check_mode", "exists", "copies"),
    [
        (False, True, True),
        (False, False, True),
        # A dry run never creates the directory, so a copy into it fails (#2696).
        (True, False, False),
        # Once it exists, whatever its mode, a dry run still reports the backup it would take.
        (True, True, True),
    ],
)
def test_a_dry_run_reaches_past_the_netplan_backup(check_mode: bool, exists: bool, copies: bool) -> None:
    directory = _task("Create the netplan backup directory")
    probe = _task("Check whether the netplan backup directory exists")
    backup = _task("Back up hand-written netplan files")
    assert "check_mode" not in directory, "a dry run must not create the directory on the host"
    assert probe["stat"]["path"] == directory["file"]["path"], "the probe reads another path than the one created"
    assert TASKS.index(probe) < TASKS.index(directory), "the probe must read the host before the directory task"

    variables = {"ansible_check_mode": check_mode, probe["register"]: {"stat": {"exists": exists}}}

    assert task_runs(backup, variables) is copies
