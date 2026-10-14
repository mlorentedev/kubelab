"""The staging zone lists no host by name that nothing routes (#2219).

rpi4's CoreDNS answers `*.staging.kubelab.live` with a wildcard template, so an
explicit `hosts` line under it adds only a TTL: 3600s from the hosts plugin
against the template's 60s. For a retired name that is strictly worse, because
Pi-hole then holds the stale answer for an hour. The block listed `web`, `blog`
and `gitea` long after staging web moved to `staging.mlorente.dev`, the blog was
killed and Gitea left K3s. It now holds the apex only, which the template's
pattern does not match.

Routed means what `tests/test_runbook_hostnames_are_published.py` uses for the
docs: a name some IngressRoute under `infra/k8s/base` or the staging overlay
serves with a `Host()` rule.
"""

from __future__ import annotations

import re

import jinja2
import yaml

from tests.test_coredns_prod_zone_targets import COMMON, ROLE, _role_vars
from tests.test_runbook_hostnames_are_published import _routed_in_staging

# The role's own `staging_domain`, rendered against common.yaml as Ansible does.
APEX = jinja2.Template(yaml.safe_load((ROLE / "defaults/main.yml").read_text())["staging_domain"]).render(
    common=yaml.safe_load(COMMON.read_text())
)


def _render(section: str) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    variables = _role_vars()
    variables["staging_domain"] = APEX
    variables["staging_zones"] = yaml.safe_load(COMMON.read_text())["networking"]["staging_zones"]
    return env.from_string(section).render(**variables)


def _staging_zone() -> str:
    """The rendered first staging zone, the one whose apex is `staging_domain`."""
    text = (ROLE / "templates/Corefile.j2").read_text()
    return _render(text.split("{{ staging_domain }} {", 1)[1].split("{% for zone in staging_zones %}", 1)[0])


def _staging_section() -> str:
    """Every staging zone the template renders: the apex zone and the `staging_zones` loop."""
    text = (ROLE / "templates/Corefile.j2").read_text()
    return _render(text.split("# --- Staging zones", 1)[1].split("# --- Prod zone", 1)[0])


def _explicit_hosts(rendered: str) -> dict[str, list[str]]:
    """Each zone's `hosts` names. A line that is not `IP NAME...` fails rather than
    being skipped, so a parse that misses entries cannot read as an empty block."""
    zones: dict[str, list[str]] = {}
    for zone, body in re.findall(r"^(\S+) \{\n(.*?)^\}", rendered, flags=re.MULTILINE | re.DOTALL):
        block = re.search(r"^\s*hosts \{\n(.*?)^\s*\}", body, flags=re.MULTILINE | re.DOTALL)
        if not block:
            continue
        names = []
        for line in (raw.strip() for raw in block.group(1).splitlines()):
            if not line or line.startswith("#") or line == "fallthrough":
                continue
            fields = line.split()
            assert len(fields) >= 2, f"zone {zone}: unparsed hosts line {line!r}"
            names += fields[1:]
        zones[zone] = names
    return zones


def _unrouted(zone: str, hosts: list[str]) -> list[str]:
    routed = _routed_in_staging(zone)
    return [h for h in hosts if h != zone and h.removesuffix(f".{zone}") not in routed]


def test_every_staging_zone_is_read() -> None:
    zones = _explicit_hosts(_staging_section())
    assert set(zones) == set(yaml.safe_load(COMMON.read_text())["networking"]["staging_zones"]) | {APEX}


def test_every_explicit_staging_host_is_its_zone_apex_or_routed() -> None:
    zones = _explicit_hosts(_staging_section())
    assert APEX in zones[APEX], "the apex lost its explicit entry, and the template's pattern does not answer it"
    unrouted = {zone: _unrouted(zone, hosts) for zone, hosts in zones.items() if _unrouted(zone, hosts)}
    assert not unrouted, f"the staging zones pin names no manifest routes: {unrouted}"


def test_the_parse_reads_every_name_on_a_line() -> None:
    rendered = f"{APEX} {{\n    hosts {{\n        10.0.0.1 {APEX} gitea.{APEX}\n        fallthrough\n    }}\n}}\n"
    assert _explicit_hosts(rendered) == {APEX: [APEX, f"gitea.{APEX}"]}
    assert _unrouted(APEX, _explicit_hosts(rendered)[APEX]) == [f"gitea.{APEX}"]


def test_the_routed_check_accepts_a_routed_name_and_refuses_a_retired_one() -> None:
    """The zones hold only their apexes, so the check above compares nothing on master;
    this exercises its contract with `_routed_in_staging` on names that exist."""
    assert _unrouted(APEX, [APEX, f"grafana.{APEX}"]) == []
    # Gitea left K3s for the Beelink (ADR-061), so no manifest routes it. If it ever
    # returns, pick another retired name here.
    assert _unrouted(APEX, [f"gitea.{APEX}"]) == [f"gitea.{APEX}"]


def test_the_wildcard_answers_every_name_under_the_apex() -> None:
    pattern = re.search(r"^\s*match (\S+)$", _staging_zone(), flags=re.MULTILINE)
    assert pattern, "the staging zone has no template match"
    # Derived from the apex, dots escaped: an unescaped `.` would still pass the two matches below.
    assert pattern.group(1) == r".*\." + re.escape(APEX)
    assert re.fullmatch(pattern.group(1), f"grafana.{APEX}")
    assert not re.fullmatch(pattern.group(1), APEX)
