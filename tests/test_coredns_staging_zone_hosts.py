"""The staging zone lists no host by name that nothing routes (#2219).

rpi4's CoreDNS answers `*.staging.kubelab.live` with a wildcard template, so an
explicit `hosts` line under it adds only a TTL: 3600s from the hosts plugin
against the template's 60s. For a retired name that is strictly worse, because
Pi-hole then holds the stale answer for an hour. The block listed `web`, `blog`
and `gitea` long after staging web moved to `staging.mlorente.dev`, the blog was
killed and Gitea left K3s. It now holds the apex only, which the template's
pattern does not match.

Routed means what `tests/test_runbook_hostnames_are_published.py` uses for the
docs: a name some manifest under `infra/k8s/base` or the staging overlay
mentions.
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


def _staging_zone() -> str:
    """The rendered first staging zone, the one whose apex is `staging_domain`."""
    text = (ROLE / "templates/Corefile.j2").read_text()
    zone = text.split("{{ staging_domain }} {", 1)[1].split("{% for zone in staging_zones %}", 1)[0]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    variables = _role_vars()
    variables["staging_domain"] = APEX
    return env.from_string(zone).render(**variables)


def _explicit_hosts(rendered: str) -> list[str]:
    block = rendered.split("hosts {", 1)[1].split("fallthrough", 1)[0]
    lines = [line.strip() for line in block.splitlines()]
    return [line.split()[1] for line in lines if line and not line.startswith("#")]


def test_every_explicit_staging_host_is_the_apex_or_routed() -> None:
    hosts = _explicit_hosts(_staging_zone())
    assert APEX in hosts, "the apex lost its explicit entry, and the template's pattern does not answer it"
    routed = _routed_in_staging()
    unrouted = [h for h in hosts if h != APEX and h.removesuffix(f".{APEX}") not in routed]
    assert not unrouted, f"the staging zone pins names no manifest routes: {unrouted}"


def test_the_wildcard_answers_every_name_under_the_apex() -> None:
    pattern = re.search(r"^\s*match (\S+)$", _staging_zone(), flags=re.MULTILINE)
    assert pattern, "the staging zone has no template match"
    # Derived from the apex, dots escaped: an unescaped `.` would still pass the two matches below.
    assert pattern.group(1) == r".*\." + re.escape(APEX)
    assert re.fullmatch(pattern.group(1), f"grafana.{APEX}")
    assert not re.fullmatch(pattern.group(1), APEX)
