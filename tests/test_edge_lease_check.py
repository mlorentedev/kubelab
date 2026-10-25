"""The uplink lease check (NET-005 AC7, ADR-075 D3).

A site's DHCP server decides the uplink's address, its gateway and the routes it
offers. The check reports any of them that lands inside a network the lab owns:
the homelab LAN, the lab Wi-Fi or the tailnet. Routing survives an address
collision, because the longer internal prefix wins, but the address can clash
with a homelab host dnsmasq leased it to, so the operator is paged.

- An offered route counts when it overlaps an internal network in either
  direction. A route that contains one (a `/1`, or `172.16.0.0/12`) is the
  TunnelVision shape. The default route is not a collision: option 121 carries
  it routinely, and every renewal would page.
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
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "infra" / "ansible" / "roles" / "gateway" / "files" / "edge-lease-check.sh"
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
UPLINK = NETWORKING["edge"]["uplink"]["interface"]
INTERNAL = {
    "lan": NETWORKING["lan_cidr"],
    "lab": NETWORKING["edge"]["lab_wifi"]["cidr"],
    "tailnet": NETWORKING["tailscale_cidr"],
}
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
        (sys_net / interface / "ifindex").write_text(f"{IFINDEX}\n")
    if lease is not None:
        (leases / IFINDEX).write_text(lease)
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
    """The site's /23 contains the homelab LAN (NET-006); its address and gateway do not."""
    lease = _site_lease(ADDRESS="172.16.0.123", NETMASK="255.255.254.0", ROUTER="172.16.0.1")
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 0, _output(result)


def test_the_same_prefix_with_an_address_in_the_lan_is_a_collision(tmp_path: Path, awk_bin: Path) -> None:
    lease = _site_lease(ADDRESS="172.16.1.123", NETMASK="255.255.254.0", ROUTER="172.16.0.1")
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 1, _output(result)
    assert "address 172.16.1.123" in _output(result)
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
        "172.16.1.128/25",  # inside the LAN
        "172.16.0.0/12",  # contains the LAN
        "0.0.0.0/1",  # contains the LAN and the lab
        "100.64.0.0/16",  # inside the tailnet
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
    routes = f"0.0.0.0/0,{OUTSIDE_ROUTER} 198.51.100.0/24,{OUTSIDE_ROUTER} 10.0.0.0/8,{OUTSIDE_ROUTER}"
    result = _run(tmp_path, awk_bin, _site_lease(CLASSLESS_ROUTES=routes))
    assert result.returncode == 1, _output(result)
    assert "route 10.0.0.0/8" in _output(result)


def test_every_collision_is_reported_not_only_the_first(tmp_path: Path, awk_bin: Path) -> None:
    address = _host(INTERNAL["lan"], 50)
    router = _host(INTERNAL["lan"], 1)
    lease = _site_lease(ADDRESS=address, ROUTER=router, CLASSLESS_ROUTES=f"0.0.0.0/1,{router}")
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 1, _output(result)
    for kind in (f"address {address}", f"gateway {router}", "route 0.0.0.0/1"):
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
        _site_lease(ADDRESS="172.16.1.256"),
        _site_lease(ADDRESS="172.16.1"),
        _site_lease(ADDRESS=""),
        _site_lease(ROUTER="not-an-address"),
        _site_lease(CLASSLESS_ROUTES=f"172.16.1.0/33,{OUTSIDE_ROUTER}"),
        _site_lease(CLASSLESS_ROUTES="172.16.1.0/24"),
        _site_lease(STATIC_ROUTES=f"garbage,{OUTSIDE_ROUTER}"),
    ],
    ids=["no-address", "octet", "short", "empty", "router", "prefix", "no-gateway", "static"],
)
def test_a_lease_the_check_cannot_read_fails_closed(tmp_path: Path, awk_bin: Path, lease: str) -> None:
    """A blind check must page, not pass. Exit 2 keeps it apart from a collision."""
    result = _run(tmp_path, awk_bin, lease)
    assert result.returncode == 2, _output(result)
    assert "cannot read" in _output(result)


def test_a_hostile_value_is_never_repeated(tmp_path: Path, awk_bin: Path) -> None:
    """The site writes the lease and the journal excerpt becomes the page body."""
    hostile = "$(touch /tmp/pwned)\x1b[31m<script>evil"
    result = _run(tmp_path, awk_bin, _site_lease(ROUTER=hostile))
    assert result.returncode == 2, _output(result)
    for fragment in ("pwned", "\x1b", "<script>", "evil"):
        assert fragment not in _output(result)
    assert "ROUTER" in _output(result)


@pytest.mark.parametrize("spec", ["lan", "lan=", "lan=172.16.1.0", "lan=172.16.1.0/40", "lan=1.2.3/8"])
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
