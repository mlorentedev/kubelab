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

Those answers are about the SOPS value. What Traefik uses is the Secret in
`kube-system`, which changes only at provision, so `cluster_holds_token` compares
the two (#2928).
"""

from __future__ import annotations

import base64
import hmac
import subprocess
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
        # A rate limit or a server error says nothing about the token's scope.
        if exc.code == 429 or exc.code >= 500:
            raise ScopeUncheckableError(f"Cloudflare answered HTTP {exc.code} on {path}") from exc
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


#: `k3s_traefik_acme_secret_name` in the k3s_server role; a test holds them equal.
CLUSTER_SECRET = "cloudflare-api-token"


def cluster_holds_token(env: str, token: str, run: Callable[..., Any] = subprocess.run) -> bool:
    """Whether the Secret in `env`'s cluster holds `token`. The value never leaves here.

    Only kubectl's stderr reaches an error message: stdout is the credential.
    """
    from toolkit.features.k8s_kubeconfig import output_path

    command = ["kubectl", "--kubeconfig", str(output_path(env)), "--request-timeout=15s", "-n", "kube-system"]
    command += ["get", "secret", CLUSTER_SECRET, "-o", "jsonpath={.data.api-token}"]
    try:
        done = run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ScopeUncheckableError(f"kubectl could not run: {exc}") from exc
    if done.returncode != 0:
        raise ScopeUncheckableError(f"{env}: cannot read the Secret: {done.stderr.strip()[:200]}")
    if not done.stdout:
        raise ScopeUncheckableError(f"{env}: the Secret has no api-token key")
    return hmac.compare_digest(base64.b64decode(done.stdout), token.encode())
