"""What the ACME DNS-01 token can do in Cloudflare, asked of Cloudflare (#2459).

The ACME resolvers hold their own token so that reading the in-cluster Secret
gives DNS records on the issuing zones and nothing else. A token's scope is set
in the Cloudflare dashboard and is not in this repository, so the only way to
know it is to use the token and see what Cloudflare answers. Every probe is a
GET: nothing here writes a record or a setting.

Per zone, three answers are expected:

- the zone is found by name. Traefik's ACME client looks the zone up this way
  before it writes a challenge record, so a token that cannot see its zone
  cannot issue a certificate, whatever else it is allowed;
- DNS records can be read (200);
- zone settings are refused (403). A 200 means the token is broader than DNS.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

API = "https://api.cloudflare.com/client/v4"

Get = Callable[[str, str], tuple[int, dict[str, Any]]]


class ScopeUncheckableError(RuntimeError):
    """Cloudflare could not be asked, or refused the token outright.

    Distinct from a wrong scope: a check that could not run must never read as
    a clean one, so the CLI exits 2 on it, not 0 or 1.
    """


@dataclass(frozen=True)
class Probe:
    zone: str
    action: str
    expected: int
    got: int

    @property
    def ok(self) -> bool:
        return self.got == self.expected


def http_get(path: str, token: str, timeout: float = 15.0) -> tuple[int, dict[str, Any]]:
    """Status and JSON body of a GET. The token is sent, never returned or logged."""
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception as exc:  # noqa: BLE001 - any other failure is "cannot check"
        raise ScopeUncheckableError(f"Cloudflare could not be reached: {exc}") from exc


def probe_acme_token(token: str, zones: Iterable[str], get: Get = http_get) -> list[Probe]:
    """One Probe per question, in the order Traefik would need the answers."""
    status, body = get("/user/tokens/verify", token)
    if status != 200 or (body.get("result") or {}).get("status") != "active":
        raise ScopeUncheckableError(f"Cloudflare does not accept the token as active (HTTP {status})")

    probes: list[Probe] = []
    for zone in zones:
        status, body = get(f"/zones?name={zone}", token)
        found = body.get("result") or []
        # A zone the token cannot see may come back as 200 with no result, not 403.
        got = 404 if status == 200 and len(found) != 1 else status
        probes.append(Probe(zone, "find the zone by name", 200, got))
        if len(found) != 1:
            continue
        zone_id = found[0]["id"]
        status, _ = get(f"/zones/{zone_id}/dns_records?per_page=1", token)
        probes.append(Probe(zone, "read DNS records", 200, status))
        status, _ = get(f"/zones/{zone_id}/settings", token)
        probes.append(Probe(zone, "read zone settings", 403, status))
    return probes
