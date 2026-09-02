"""OBS-019: a service that declares a public `domain` must have a DNS record.

`apps.*.domain` in the values files means "the public name this service answers
on". It is not decoration: `toolkit/features/health_check.py` probes
`https://{domain}{health_path}` and reports a FAIL when nothing answers, and
`notify_smoke.py` reads it too.

Two services declared a name that nothing served, and both failures were silent
in exactly the way a config-only claim is:

- `observability.loki` declared `loki.kubelab.live`, but the prod overlay
  patches its route to `Host(loki.internal.kubelab.local)` — a non-public TLD,
  because ACME cannot issue a certificate for one. The declaration outlived the
  patch.
- `security.crowdsec` declared `crowdsec.kubelab.live` and has no IngressRoute
  in any overlay. It is reached in-cluster only, by the Traefik bouncer plugin.

Both produced a permanent FAIL in `services health`, and the Loki one was read
as a missing DNS record and filed as #1406 — a ticket to *publish* a service
that is deliberately internal. A wrong declaration does not stay a cosmetic
problem; it generates work in the wrong direction.

Why this invariant and not "the domain matches an IngressRoute host": there is
no kubectl on CI runners (see test_spoke_rbac_covers_manifests.py for the same
constraint), so the overlay patches that decide the real host cannot be
rendered here. A DNS record is the weaker claim but a strictly necessary one —
a public name with no record cannot be reached however the routing is written —
and it is declared in a file this test can read.
"""

from __future__ import annotations

import json
import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES_JSON = REPO_ROOT / "infra/terraform/dns/services.json"
VALUES = REPO_ROOT / "infra/config/values"

#: Zone apexes the DNS module manages, by its `zone` key.
ZONE_APEX = {"kubelab": "kubelab.live", "mlorente": "mlorente.dev"}

#: Domains served by something outside the Terraform DNS module. Keep this
#: explicit and small: an unrecognised domain must FAIL rather than be skipped,
#: because a guard that skips what it does not know reports success on the very
#: case it exists to catch.
EXTERNALLY_MANAGED: frozenset[str] = frozenset()


def _declared_dns_names() -> set[str]:
    records = json.loads(SERVICES_JSON.read_text())
    names = set()
    for r in records:
        apex = ZONE_APEX[r["zone"]]
        name = r["name"]
        names.add(apex if name in ("@", apex) else f"{name}.{apex}")
    # The apex itself and `www` are declared as their own resources in the
    # module rather than as entries in services.json.
    names.update({"kubelab.live", "www.kubelab.live", "mlorente.dev"})
    return names


def _declared_domains(env: str) -> dict[str, str]:
    """Every `<key>: <domain>` a service declares, merged common -> env."""
    found: dict[str, str] = {}
    for source in ("common", env):
        path = VALUES / f"{source}.yaml"
        if not path.exists():
            continue
        config = yaml.safe_load(path.read_text()) or {}
        _walk(config.get("apps", {}), found)
    return found


def _walk(node: object, found: dict[str, str], path: str = "apps") -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        here = f"{path}.{key}"
        if key.endswith("domain") and isinstance(value, str) and value:
            found[here] = value
        else:
            _walk(value, found, here)


def test_every_declared_public_domain_has_a_dns_record() -> None:
    """A declared `domain` with no DNS record can never answer a health probe.

    Prod only, and not as a first step toward covering staging: `*.staging.
    kubelab.live` resolves over the VPN through Headscale split DNS to RPi4
    CoreDNS and is deliberately absent from Cloudflare, so `services.json` is
    not the SSOT this invariant needs there and asserting it would fail on
    every staging name. Parametrising over one environment would imply an
    expansion that cannot exist.
    """
    env = "prod"
    dns = _declared_dns_names()
    undeclared = {
        key: domain
        for key, domain in _declared_domains(env).items()
        # Only names in a zone this module manages, and only public TLDs --
        # `*.local` is deliberately unroutable and never gets a record.
        if domain not in dns
        and domain not in EXTERNALLY_MANAGED
        and any(domain.endswith(apex) for apex in ZONE_APEX.values())
    }
    assert not undeclared, (
        f"{env}: these services declare a public domain that no Cloudflare "
        f"record serves, so `toolkit services health --env {env}` will report "
        f"a permanent FAIL for each:\n"
        + "\n".join(f"  {k} = {v}" for k, v in sorted(undeclared.items()))
        + f"\n\nEither add the record to {SERVICES_JSON.relative_to(REPO_ROOT)}, "
        "or delete the `domain` key if the service is not meant to be public "
        "(and say so in a comment, so nobody re-adds it)."
    )
