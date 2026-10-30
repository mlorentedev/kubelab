"""The uplink lease check (NET-005 AC7, ADR-075 D3).

A site's DHCP server decides the uplink's address, its gateway and the routes it
offers. The check reports any of them that lands inside a network the lab owns:
the homelab LAN, the lab Wi-Fi or the tailnet. Routing survives an address
collision, because the longer internal prefix wins, but the address can clash
with a homelab host dnsmasq leased it to, so the operator is paged.

- An offered route counts when it overlaps an internal network in either
  direction. A route that contains one (a `/1`, or the RFC 1918 block that
  holds the LAN) is the TunnelVision shape. The default route is not a
  collision: option 121 carries it routinely, and every renewal would page.
- The site's prefix is not checked. The temporary site's `/23` contains the
  homelab LAN, which NET-006 (#2662) renumbers; an alert on every renewal until
  then would bury the cases that matter.
- networkd's lease file says it is private. Nothing else exposes the routes a
  site offered, since the uplink refuses them, so the check parses it and fails
  closed: a lease it cannot read exits non-zero, and a format change pages
  instead of passing.
- The lease values come from the site. The output reaches the page body, so it
  only ever repeats values that parsed as addresses.

Every case runs under dash with each awk available here (gawk, mawk, busybox),
because the RPi4 runs dash and gawk and a laptop may run neither.
"""

from __future__ import annotations

import ipaddress
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "infra" / "ansible" / "roles" / "gateway" / "files" / "edge-lease-check.sh"
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))[
    "networking"
]
UPLINK = NETWORKING["edge"]["uplink"]["interface"]
INTERNAL = {
    "lan": NETWORKING["lan_cidr"],
    "lab": NETWORKING["edge"]["lab_wifi"]["cidr"],
    "tailnet": NETWORKING["tailscale_cidr"],
}
LAN = ipaddress.ip_network(INTERNAL["lan"])
LAB = ipaddress.ip_network(INTERNAL["lab"])
TAILNET = ipaddress.ip_network(INTERNAL["tailnet"])
# The temporary site's shape (NET-006): a prefix one bit wider than the LAN, so it
# contains the LAN, with its gateway in the other half.
SITE = LAN.supernet()
SITE_HALF = next(half for half in SITE.subnets() if half != LAN)
IFINDEX = "7"
# Addresses outside every internal network, for the parts of a lease a case does not
# exercise. Documentation ranges (RFC 5737), so no real site is described.
OUTSIDE = "192.0.2.10"
OUTSIDE_ROUTER = "192.0.2.1"


def _available(names: tuple[str, ...]) -> list[str]:
    found = [name for name in names if shutil.which(name)]
    return found or ["system"]


# The RPi4 runs dash and gawk. Every case runs under dash with each awk available
# here, so a bash-only construct or a gawk extension fails here, not on the edge.
# Not busybox as the shell: its ash runs its own awk applet ahead of PATH.
SHELLS = _available(("dash",))
AWKS = _available(("gawk", "mawk", "busybox"))


def _host(network: str, offset: int) -> str:
    net = ipaddress.ip_network(network)
    return str(net.network_address + offset)


def _lease(**keys: str) -> str:
    """A lease in networkd v255's format (`dhcp_lease_save`): one `KEY=value` per line."""
    lines = ["# This is private data. Do not parse."]
    lines += [f"{key}={value}" for key, value in keys.items()]
    return "\n".join(lines) + "\n"


def _site_lease(**overrides: str) -> str:
    keys = {
        "ADDRESS": OUTSIDE,
        "NETMASK": "255.255.255.0",
        "ROUTER": OUTSIDE_ROUTER,
        "SERVER_ADDRESS": OUTSIDE_ROUTER,
        "T1": "30min",
        "T2": "52min 30s",
        "LIFETIME": "1h",
        "DNS": OUTSIDE_ROUTER,
        "CLIENTID": "ff00112233445566",
    }
    keys.update(overrides)
    return _lease(**{k: v for k, v in keys.items() if v is not None})


@pytest.fixture(params=[(sh, awk) for sh in SHELLS for awk in AWKS], ids=lambda p: f"{p[0]}-{p[1]}")
def awk_bin(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A PATH directory whose `sh` and `awk` are the pair under test."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, chosen in zip(("sh", "awk"), request.param, strict=True):
        if chosen == "system":
            continue
        target = shutil.which(chosen)
        assert target is not None
        # busybox picks the applet from the name it was called by.
        (bin_dir / name).symlink_to(target)
    return bin_dir


def _run(
    tmp_path: Path,
    awk_bin: Path,
    lease: str | None,
    *,
    interface: str = UPLINK,
    networks: dict[str, str] | None = None,
    with_interface: bool = True,
) -> subprocess.CompletedProcess[str]:
    sys_net = tmp_path / "sys-class-net"
    leases = tmp_path / "leases"
    leases.mkdir(exist_ok=True)
    if with_interface:
        (sys_net / interface).mkdir(parents=True, exist_ok=True)
        (sys_net / interface / "ifindex").write_text(f"{IFINDEX}\n", encoding="utf-8")
    if lease is not None:
        (leases / IFINDEX).write_text(lease, encoding="utf-8")
    nets = INTERNAL if networks is None else networks
    args = [f"{name}={cidr}" for name, cidr in nets.items()]
    env = {
        "PATH": f"{awk_bin}:/usr/bin:/bin",
        "EDGE_LEASES_DIR": str(leases),
        "EDGE_SYS_NET": str(sys_net),
    }
    return subprocess.run(
        [_sh(awk_bin), str(SCRIPT), interface, *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _sh(bin_dir: Path) -> str:
    shell = bin_dir / "sh"
    return str(shell) if shell.exists() else "/bin/sh"


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_the_internal_networks_come_from_the_ssot() -> None:
    for cidr in INTERNAL.values():
        ipaddress.ip_network(cidr)
    assert set(INTERNAL) == {"lan", "lab", "tailnet"}


def test_a_clean_lease_passes(tmp_path: Path, awk_bin: Path) -> None:
    result = _run(tmp_path, awk_bin, _site_lease())
    assert result.returncode == 0, _output(result)


def test_the_temporary_sites_prefix_alone_is_not_a_collision(tmp_path: Path, awk_bin: Path) -> None:
    """The site's prefix contains the homelab LAN (NET-006); its address and gateway do not."""
    lease = _site_lease(ADDRESS=_host(str(SITE_HALF), 123), NETMASK=str(SITE.netmask), ROUTER=_host(str(SITE_HALF), 1))
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 0, _output(result)


def test_the_same_prefix_with_an_address_in_the_lan_is_a_collision(tmp_path: Path, awk_bin: Path) -> None:
    address = _host(INTERNAL["lan"], 123)
    lease = _site_lease(ADDRESS=address, NETMASK=str(SITE.netmask), ROUTER=_host(str(SITE_HALF), 1))
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 1, _output(result)
    assert f"address {address}" in _output(result)
    assert f"lan {INTERNAL['lan']}" in _output(result)


@pytest.mark.parametrize("name", sorted(INTERNAL))
@pytest.mark.parametrize("offset", [1, -1])
def test_an_address_inside_an_internal_network_is_reported(
    tmp_path: Path, awk_bin: Path, name: str, offset: int
) -> None:
    """Both ends of each network, so the containment arithmetic is checked at its edges."""
    net = ipaddress.ip_network(INTERNAL[name])
    address = str(net.network_address + 1) if offset == 1 else str(net.broadcast_address - 1)
    result = _run(tmp_path, awk_bin, _site_lease(ADDRESS=address))
    assert result.returncode == 1, _output(result)
    assert f"address {address}" in _output(result)
    assert f"{name} {INTERNAL[name]}" in _output(result)


@pytest.mark.parametrize("name", sorted(INTERNAL))
def test_the_addresses_just_outside_a_network_pass(tmp_path: Path, awk_bin: Path, name: str) -> None:
    net = ipaddress.ip_network(INTERNAL[name])
    for address in (net.network_address - 1, net.broadcast_address + 1):
        result = _run(tmp_path, awk_bin, _site_lease(ADDRESS=str(address)))
        assert result.returncode == 0, f"{address}: {_output(result)}"


@pytest.mark.parametrize("name", sorted(INTERNAL))
def test_a_gateway_inside_an_internal_network_is_reported(tmp_path: Path, awk_bin: Path, name: str) -> None:
    router = _host(INTERNAL[name], 1)
    result = _run(tmp_path, awk_bin, _site_lease(ROUTER=router))
    assert result.returncode == 1, _output(result)
    assert f"gateway {router}" in _output(result)
    assert f"{name} {INTERNAL[name]}" in _output(result)


def test_every_router_the_lease_lists_is_checked(tmp_path: Path, awk_bin: Path) -> None:
    router = _host(INTERNAL["lab"], 1)
    result = _run(tmp_path, awk_bin, _site_lease(ROUTER=f"{OUTSIDE_ROUTER} {router}"))
    assert result.returncode == 1, _output(result)
    assert f"gateway {router}" in _output(result)


@pytest.mark.parametrize("key", ["CLASSLESS_ROUTES", "STATIC_ROUTES"])
@pytest.mark.parametrize(
    "route",
    [
        str(list(LAN.subnets())[1]),  # inside the LAN
        str(LAN.supernet(new_prefix=max(LAN.prefixlen - 12, 1))),  # contains the LAN
        str(TAILNET.supernet(new_prefix=1)),  # a /1, which contains the tailnet
        str(next(TAILNET.subnets(prefixlen_diff=6))),  # inside the tailnet
    ],
)
def test_an_offered_route_that_overlaps_an_internal_network_is_reported(
    tmp_path: Path, awk_bin: Path, key: str, route: str
) -> None:
    result = _run(tmp_path, awk_bin, _site_lease(**{key: f"{route},{OUTSIDE_ROUTER}"}))
    assert result.returncode == 1, _output(result)
    assert f"route {route}" in _output(result)


@pytest.mark.parametrize("key", ["CLASSLESS_ROUTES", "STATIC_ROUTES"])
def test_the_default_route_is_not_a_collision(tmp_path: Path, awk_bin: Path, key: str) -> None:
    """Option 121 routinely carries the default route; a page per renewal would be noise."""
    routes = f"0.0.0.0/0,{OUTSIDE_ROUTER} 198.51.100.0/24,{OUTSIDE_ROUTER}"
    result = _run(tmp_path, awk_bin, _site_lease(**{key: routes}))
    assert result.returncode == 0, _output(result)


def test_every_offered_route_is_checked(tmp_path: Path, awk_bin: Path) -> None:
    last = LAB.supernet(new_prefix=8)
    routes = f"0.0.0.0/0,{OUTSIDE_ROUTER} 198.51.100.0/24,{OUTSIDE_ROUTER} {last},{OUTSIDE_ROUTER}"
    result = _run(tmp_path, awk_bin, _site_lease(CLASSLESS_ROUTES=routes))
    assert result.returncode == 1, _output(result)
    assert f"route {last}" in _output(result)


def test_every_collision_is_reported_not_only_the_first(tmp_path: Path, awk_bin: Path) -> None:
    address = _host(INTERNAL["lan"], 50)
    router = _host(INTERNAL["lan"], 1)
    route = TAILNET.supernet(new_prefix=1)
    lease = _site_lease(ADDRESS=address, ROUTER=router, CLASSLESS_ROUTES=f"{route},{router}")
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 1, _output(result)
    for kind in (f"address {address}", f"gateway {router}", f"route {route}"):
        assert kind in _output(result)


def test_a_key_that_merely_ends_in_address_is_not_the_address(tmp_path: Path, awk_bin: Path) -> None:
    result = _run(tmp_path, awk_bin, _site_lease(SERVER_ADDRESS=_host(INTERNAL["lan"], 9)))
    assert result.returncode == 0, _output(result)


def test_no_lease_passes(tmp_path: Path, awk_bin: Path) -> None:
    """A deleted lease also fires the path unit, and that run closes an open incident."""
    result = _run(tmp_path, awk_bin, None)
    assert result.returncode == 0, _output(result)


def test_no_uplink_passes(tmp_path: Path, awk_bin: Path) -> None:
    result = _run(tmp_path, awk_bin, None, with_interface=False)
    assert result.returncode == 0, _output(result)


@pytest.mark.parametrize(
    "lease",
    [
        _lease(ROUTER=OUTSIDE_ROUTER),  # no address at all
        _site_lease(ADDRESS="192.0.2.256"),
        _site_lease(ADDRESS="192.0.2"),
        _site_lease(ADDRESS=""),
        _site_lease(ROUTER="not-an-address"),
        _site_lease(CLASSLESS_ROUTES=f"192.0.2.0/33,{OUTSIDE_ROUTER}"),
        _site_lease(CLASSLESS_ROUTES="192.0.2.0/24"),
        _site_lease(STATIC_ROUTES=f"garbage,{OUTSIDE_ROUTER}"),
    ],
    ids=["no-address", "octet", "short", "empty", "router", "prefix", "no-gateway", "static"],
)
def test_a_lease_the_check_cannot_read_fails_closed(tmp_path: Path, awk_bin: Path, lease: str) -> None:
    """A blind check must page, not pass. Exit 2 keeps it apart from a collision."""
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 2, _output(result)
    assert "cannot read" in _output(result)


@pytest.mark.parametrize("key", ["ADDRESS", "ROUTER", "CLASSLESS_ROUTES", "STATIC_ROUTES"])
def test_a_hostile_value_is_never_repeated(tmp_path: Path, awk_bin: Path, key: str) -> None:
    """The site writes the lease and the journal excerpt becomes the page body."""
    hostile = "$(touch /tmp/pwned)\x1b[31m<script>evil"
    result = _run(tmp_path, awk_bin, _site_lease(**{key: hostile}))
    assert result.returncode == 2, _output(result)
    for fragment in ("pwned", "\x1b", "<script>", "evil"):
        assert fragment not in _output(result)
    assert key in _output(result)


@pytest.mark.parametrize("spec", ["lan", "lan=", "lan=192.0.2.0", "lan=192.0.2.0/40", "lan=1.2.3/8"])
def test_a_malformed_network_is_a_usage_error(tmp_path: Path, awk_bin: Path, spec: str) -> None:
    result = subprocess.run(
        [_sh(awk_bin), str(SCRIPT), UPLINK, spec],
        capture_output=True,
        text=True,
        env={"PATH": f"{awk_bin}:/usr/bin:/bin", "EDGE_LEASES_DIR": str(tmp_path), "EDGE_SYS_NET": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 64, _output(result)


def test_no_network_is_a_usage_error(tmp_path: Path, awk_bin: Path) -> None:
    result = _run(tmp_path, awk_bin, _site_lease(), networks={})
    assert result.returncode == 64, _output(result)


def test_an_implausible_interface_name_is_refused(tmp_path: Path, awk_bin: Path) -> None:
    """The name becomes a path under sysfs: no traversal through it."""
    result = _run(tmp_path, awk_bin, _site_lease(), interface="../../etc")
    assert result.returncode == 64, _output(result)


# ------------------------------------------------------------------- the units

ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
SERVICE = "kubelab-edge-lease-check.service"
PATH_UNIT = "kubelab-edge-lease-check.path"
TIMER = "kubelab-edge-lease-check.timer"


def _render(unit: str, **overrides: Any) -> str:
    variables: dict[str, Any] = {
        "ansible_managed": "managed",
        "gateway_uplink_interface": UPLINK,
        "gateway_lease_check_networks": INTERNAL,
        "gateway_lease_check_path": DEFAULTS["gateway_lease_check_path"],
    }
    variables.update(overrides)
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True, lstrip_blocks=True)
    return env.get_template(f"{unit}.j2").render(**variables)


def _directives(text: str) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            keys.setdefault(key, []).append(value)
    return keys


def test_the_service_checks_the_uplink_against_every_internal_network() -> None:
    (command,) = _directives(_render(SERVICE))["ExecStart"]
    argv = shlex.split(command)
    assert argv[0] == DEFAULTS["gateway_lease_check_path"]
    assert argv[1] == UPLINK
    assert argv[2:] == [f"{name}={cidr}" for name, cidr in INTERNAL.items()]


def test_a_collision_pages_once_and_a_clean_run_closes_it() -> None:
    keys = _directives(_render(SERVICE))
    assert keys["OnFailure"] == ["kubelab-notify@%n.service"]
    assert keys["OnSuccess"] == ["kubelab-notify-recovered@%n.service"]
    assert keys["Type"] == ["oneshot"]


def test_a_burst_of_lease_events_never_reaches_the_start_limit() -> None:
    """One lease write is several inotify events and the check takes milliseconds: under the
    default limit (5 starts in 10 s) the unit lands in `failed` and pages for nothing."""
    assert _directives(_render(SERVICE))["StartLimitIntervalSec"] == ["0"]


def test_the_path_unit_watches_networkds_lease_directory() -> None:
    """networkd writes a temporary file and renames it into place; a directory watch sees
    both the write and the removal, and the removal's run closes an open incident."""
    keys = _directives(_render(PATH_UNIT))
    assert keys["PathChanged"] == ["/run/systemd/netif/leases"]
    assert keys["Unit"] == [SERVICE]
    assert keys["WantedBy"] == ["paths.target"]


def test_the_units_pass_systemd_analyze_verify(tmp_path: Path) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is not installed")
    (tmp_path / SERVICE).write_text(_render(SERVICE, gateway_lease_check_path="/bin/true"), encoding="utf-8")
    (tmp_path / PATH_UNIT).write_text(_render(PATH_UNIT), encoding="utf-8")
    (tmp_path / TIMER).write_text(_render(TIMER), encoding="utf-8")
    for stub in ("kubelab-notify@.service", "kubelab-notify-recovered@.service"):
        (tmp_path / stub).write_text("[Service]\nType=oneshot\nExecStart=/bin/true\n", encoding="utf-8")
    proc = subprocess.run(
        ["systemd-analyze", "verify", "--man=no", *(str(tmp_path / unit) for unit in (SERVICE, PATH_UNIT, TIMER))],
        capture_output=True,
        text=True,
        env={"SYSTEMD_UNIT_PATH": f"{tmp_path}:", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def _first(predicate: Any) -> int:
    return next(i for i, task in enumerate(TASKS) if predicate(task))


def _systemd(task: dict[str, Any]) -> dict[str, Any]:
    return task.get("systemd") or task.get("ansible.builtin.systemd") or {}


def test_the_role_installs_the_script_where_the_unit_runs_it() -> None:
    install = _first(lambda task: (task.get("copy") or {}).get("src") == "edge-lease-check.sh")
    args = TASKS[install]["copy"]
    assert args["dest"] == "{{ gateway_lease_check_path }}"
    assert args["mode"] == "0755"


def test_the_watch_starts_before_the_uplink_takes_its_first_lease() -> None:
    """A path unit does not fire for a lease written before it started watching."""
    watch = _first(lambda task: _systemd(task).get("name") == PATH_UNIT)
    args = _systemd(TASKS[watch])
    assert args["enabled"] is True
    assert args["state"] == "{{ 'restarted' if gateway_lease_check_units is changed else 'started' }}"
    apply_uplink = _first(lambda task: task.get("name") == "Apply the uplink before anything depends on it")
    assert watch < apply_uplink


def test_a_changed_unit_restarts_the_watch() -> None:
    units = _first(lambda task: PATH_UNIT in str(task.get("loop")))
    watch = _first(lambda task: _systemd(task).get("name") == PATH_UNIT)
    register = TASKS[units]["register"]
    state = _systemd(TASKS[watch])["state"]
    assert f"{register} is changed" in state
    assert "restarted" in state
    assert _systemd(TASKS[watch]).get("daemon_reload")


def test_a_timer_rechecks_what_no_lease_event_will() -> None:
    """The path unit fires only on a write. A lease already on disk when it starts (every
    re-provision restarts it) and a page a portal kept from leaving both wait for the
    next renewal without the timer; node_notify keeps its clean runs silent."""
    keys = _directives(_render(TIMER))
    assert keys["OnActiveSec"] == ["1min"]
    assert keys["OnUnitInactiveSec"] == ["10min"]
    assert keys["Unit"] == [SERVICE]
    assert keys["WantedBy"] == ["timers.target"]


def test_the_timer_is_installed_with_the_watch_and_started() -> None:
    units = _first(lambda task: PATH_UNIT in str(task.get("loop")))
    assert TIMER in TASKS[units]["loop"]
    timer = _first(lambda task: _systemd(task).get("name") == TIMER)
    args = _systemd(TASKS[timer])
    assert args["enabled"] is True
    assert args["state"] == "{{ 'restarted' if gateway_lease_check_units is changed else 'started' }}"
    assert units < timer


def _holds(condition: Any, **variables: Any) -> bool:
    env = ansible_env(str(ROLE / "templates"))
    conditions = condition if isinstance(condition, list) else [condition]
    return all(env.compile_expression(str(c))(**variables) for c in conditions)


@pytest.mark.parametrize("unit", [PATH_UNIT, TIMER])
def test_check_mode_skips_starting_a_unit_it_has_not_written(unit: str) -> None:
    """`--check` writes no unit file, and the systemd module fails on a unit that is not
    on disk, which would end the preview before the netplan and AP diffs."""
    when = TASKS[_first(lambda task: _systemd(task).get("name") == unit)]["when"]
    new, same = {"changed": True}, {"changed": False}
    assert not _holds(when, ansible_check_mode=True, gateway_lease_check_units=new)
    assert _holds(when, ansible_check_mode=True, gateway_lease_check_units=same)
    assert _holds(when, ansible_check_mode=False, gateway_lease_check_units=new)


def test_the_networks_are_checked_before_the_watch_is_armed() -> None:
    """With no network the unit exits 64 on every lease event."""
    check = _first(lambda task: "gateway_lease_check_networks" in str(task.get("assert")))
    units = _first(lambda task: PATH_UNIT in str(task.get("loop")))
    assert check < units


@pytest.mark.parametrize("ifindex", ["abc\n", None], ids=["not-a-number", "unreadable"])
def test_an_ifindex_the_check_cannot_read_is_blind_not_a_collision(
    tmp_path: Path, awk_bin: Path, ifindex: str | None
) -> None:
    """Exit 1 means a collision. An interface that vanished between the test and the
    read is unreadable, and pages as blind (2), never as a collision."""
    sys_net = tmp_path / "sys-class-net" / UPLINK
    sys_net.mkdir(parents=True)
    if ifindex is None:
        (sys_net / "ifindex").mkdir()
    else:
        (sys_net / "ifindex").write_text(ifindex, encoding="utf-8")
    result = _run(tmp_path, awk_bin, _site_lease(), with_interface=False)
    assert result.returncode == 2, _output(result)


def test_the_playbook_maps_the_internal_networks_from_the_ssot() -> None:
    plays = yaml.safe_load(
        (REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml").read_text(encoding="utf-8")
    )
    for play in plays:
        for role in play.get("roles", []):
            if isinstance(role, dict) and role.get("role", "").endswith("/gateway"):
                assert role["vars"]["gateway_lease_check_networks"] == {
                    "lan": "{{ config.networking.lan_cidr }}",
                    "lab": "{{ config.networking.edge.lab_wifi.cidr }}",
                    "tailnet": "{{ config.networking.tailscale_cidr }}",
                }
                return
    raise AssertionError("provision-rpi4.yml runs no gateway role")
