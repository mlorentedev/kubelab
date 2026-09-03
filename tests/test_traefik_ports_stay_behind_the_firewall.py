"""SEC-005 (#1538): a port Traefik publishes must be a port the firewall allows.

On 2026-09-02 `http://<vps>:9000/api/overview` returned 200 from the public
internet -- unauthenticated, cleartext, exposing prod's entire routing topology
(24 routers, 25 services, 10 middlewares). Three controls should have stopped
it and all three failed independently:

1. `--api.insecure=true` served the API with no authentication at all.
2. ufw opens 22/80/443/41641 and NOT 9000 -- but klipper-lb publishes every port
   of a LoadBalancer Service as a hostPort with SRC_RANGES=0.0.0.0/0, and a
   DNAT-published port is evaluated in PREROUTING, before ufw's INPUT chain ever
   sees the packet. ufw could not have covered it.
3. `hcloud_firewall.vps` in infra/terraform/compute/ declares 9000 closed and is
   attached to the server -- but that module has no state in any workspace and
   has never been applied. It reads as protection and is not.

The `base_system` role already carried a written note about mechanism 2, added
for #959 when the same thing happened with a Docker-published port. A written
lesson with no mechanism is a reminder, and a reminder fails exactly when the
situation arrives. This file is the mechanism.

What it asserts is the *rendered* HelmChartConfig, not the template text: the
port list is Jinja, and the question "which ports end up in the Service" is only
answerable after rendering. Reading the template with a regex would agree with
whatever the template says it does, which is the failure mode #927 taught.
"""

from __future__ import annotations

import pathlib

import jinja2
import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "infra/ansible/roles/k3s_server"
TEMPLATE = ROLE / "templates/traefik-helmconfig.yaml.j2"
BASE_SYSTEM_DEFAULTS = REPO_ROOT / "infra/ansible/roles/base_system/defaults/main.yml"
COMMON_VALUES = REPO_ROOT / "infra/config/values/common.yaml"


def _role_defaults() -> dict:
    """The k3s_server defaults, which supply every variable the template reads."""
    data = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8")) or {}
    # `ansible_managed` is injected by Ansible itself, not by the role.
    data["ansible_managed"] = "Ansible managed"
    return data


def _render(acme_enabled: bool) -> dict:
    """Render the template the way Ansible would, and parse the result.

    Both branches of `k3s_traefik_acme_enabled` are rendered by the callers: the
    `additionalArguments` block lives inside that conditional, so checking only
    one branch would leave the other free to reintroduce `--api.insecure`.
    """
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    # Ansible's `comment` filter, which the template's first line uses.
    env.filters["comment"] = lambda text: "\n".join(f"# {line}" for line in str(text).splitlines())

    variables = _role_defaults()
    variables["k3s_traefik_acme_enabled"] = acme_enabled
    rendered = env.from_string(TEMPLATE.read_text(encoding="utf-8")).render(**variables)

    doc = yaml.safe_load(rendered)
    # `valuesContent` is a YAML document embedded as a string. The ports live in
    # there, so it has to be parsed a second time -- and if the outer render ever
    # emits something that is not valid YAML, this is where it surfaces.
    return yaml.safe_load(doc["spec"]["valuesContent"])


def _firewall_allowed_tcp_ports() -> set[int]:
    """TCP ports the VPS accepts inbound, from the SSOT that now governs it.

    SEC-006 moved the VPS's allow-list to `networking.firewall.vps_inbound` in
    common.yaml, because it had been declared twice -- here in the role default
    and again in infra/terraform/compute/ -- and the two disagreed. Reading the
    role default now would answer for the *fleet*, not for the VPS this test is
    about, and would keep passing while the list that actually governs prod
    drifted. That is the failure this whole file exists to prevent, so the test
    follows the SSOT rather than the file it used to live in.

    The cloud firewall reads the same key, and it is the layer that holds: ufw
    cannot restrict a published port (#959), which is mechanism 2 above.
    """
    data = yaml.safe_load(COMMON_VALUES.read_text(encoding="utf-8")) or {}
    rules = data.get("networking", {}).get("firewall", {}).get("vps_inbound", [])
    assert rules, (
        "networking.firewall.vps_inbound is missing from common.yaml. It is the SSOT for "
        "what the VPS accepts from the internet (SEC-006); without it this test would "
        "silently compare against an empty set and pass for the wrong reason."
    )
    return {int(rule["port"]) for rule in rules if rule.get("proto") == "tcp"}


def _exposed_ports(values: dict) -> dict[str, int]:
    """Ports the chart puts into the Service, by name.

    A port is in the Service when `expose.default` is true. Because the Service
    is type LoadBalancer, klipper-lb then publishes each one as a hostPort --
    so this set, not the container port list, is what reaches the internet.
    """
    exposed = {}
    for name, spec in (values.get("ports") or {}).items():
        if (spec.get("expose") or {}).get("default") is True:
            exposed[name] = int(spec.get("exposedPort", spec["port"]))
    return exposed


@pytest.mark.parametrize("acme_enabled", [False, True])
class TestPublishedPortsAreFirewalled:
    def test_every_exposed_port_is_allowed_by_ufw(self, acme_enabled: bool) -> None:
        """The invariant. A published port outside the allow-list is reachable by anyone."""
        exposed = _exposed_ports(_render(acme_enabled))
        allowed = _firewall_allowed_tcp_ports()

        unfirewalled = {name: port for name, port in exposed.items() if port not in allowed}

        assert not unfirewalled, (
            "These Traefik ports are published by the LoadBalancer Service but are not in "
            f"`firewall_allowed_ports`: {unfirewalled}.\n\n"
            "That combination is reachable from the public internet and ufw CANNOT restrict "
            "it -- klipper-lb publishes each Service port as a hostPort with "
            "SRC_RANGES=0.0.0.0/0, and DNAT is evaluated in PREROUTING, upstream of ufw's "
            "INPUT chain (#959, #1538).\n\n"
            "Either set `expose.default: false` for the port -- the chart's own default, and "
            "the right answer for an admin surface, which belongs behind an IngressRoute -- "
            "or add it to `firewall_allowed_ports` deliberately, knowing it is world-open."
        )

    def test_the_dashboard_port_is_not_in_the_service(self, acme_enabled: bool) -> None:
        """Named directly, because this is the specific port that was exposed.

        The assertion above is the general rule; if 9000 were ever added to
        `firewall_allowed_ports` it would pass while re-opening #1538. An admin
        API has no business on a published port whatever ufw says about it.
        """
        exposed = _exposed_ports(_render(acme_enabled))

        assert "traefik" not in exposed, (
            "The `traefik` port (9000, the dashboard/API entrypoint) is back in the "
            "LoadBalancer Service. That is what made the API publicly readable in #1538. "
            "The container still listens on 9000 and both probes target it directly, so "
            "`expose.default: false` costs nothing; the dashboard's supported path is the "
            "IngressRoute at traefik.<domain>, which routes to `api@internal` behind Authelia."
        )

    def test_the_unauthenticated_api_flag_is_not_set(self, acme_enabled: bool) -> None:
        """`--api.insecure=true` serves the whole API with no authentication."""
        args = _render(acme_enabled).get("additionalArguments") or []
        insecure = [a for a in args if a.startswith("--api.insecure")]

        assert not insecure, (
            f"{insecure} is set. This serves Traefik's full API on the `traefik` entrypoint "
            "with no authentication of any kind, and it is one `expose.default: true` away "
            "from being public again (#1538). Use `--api.dashboard=true` alone: it serves "
            "through `api@internal`, which is reachable only via an IngressRoute and so "
            "inherits that route's middlewares."
        )


def test_the_render_is_actually_exercised() -> None:
    """Guard the guard: if rendering silently produced nothing, every test above passes.

    `_exposed_ports({})` is empty, and empty satisfies all three assertions. So
    assert the render returns the ports it should, or a broken template would
    read as a clean bill of health.
    """
    values = _render(acme_enabled=True)
    ports = values.get("ports") or {}

    assert {"web", "websecure", "traefik"} <= set(ports), (
        f"The rendered HelmChartConfig defines ports {sorted(ports)}, which does not include "
        "the three expected. The assertions in this module are vacuous against an empty "
        "render, so this failing means they cannot be trusted -- fix the render first."
    )
