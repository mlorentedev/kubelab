"""Does the HUB reach its spokes -- asked with the hub's own credential.

`make check-spokes` used to answer a different question than the one it printed:

    KC=~/.kube/kubelab-$env-config
    elif kubectl --kubeconfig $KC get ns kubelab; then echo "OK (registered + reachable)"

That measures whether the OPERATOR can reach the spoke, with the operator's
unrestricted kubeconfig. It is true whenever the person running the command has
working access -- which is always, since reading the cluster secret two lines
earlier already required it. The hub's credential was never exercised.

Measured cost, 2026-08-22: the token in the hub's `cluster-staging` secret was
base64-encoded one layer too many (#1277). Every Argo CD sync answered `the
server has asked for the client to provide credentials`, the staging Application
sat at `Unknown`, and a Slack card fired every minute. `check-spokes` reported
`OK (registered + reachable)` throughout. The outage was found by a human
noticing Slack noise, not by the check built to find it.

FOUR OUTCOMES, not two. The distinction the old check could not express is the
one a hub migration actually produces:

    NOT_REGISTERED       no cluster secret on the hub
    UNREACHABLE          the spoke is down, or the network is
    CREDENTIAL_REFUSED   the spoke is FINE and the hub cannot talk to it
    OK                   the hub's credential works against the live apiserver

VERIFIED BY CONSEQUENCE. The credential is used against the spoke's `/version`
and the HTTP status is the verdict. It is never printed, never written to disk
and never placed in argv -- the CA travels as an in-memory PEM string through
`ssl.create_default_context(cadata=...)` and the token as a request header, so
no temp file and no `ps`-visible argument exists. Asking the issuer proves the
value works without revealing it.
"""

from __future__ import annotations

import base64
import json
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Status(str, Enum):
    OK = "ok"
    NOT_REGISTERED = "not-registered"
    UNREACHABLE = "unreachable"
    CREDENTIAL_REFUSED = "credential-refused"
    # The probe itself could not run. Deliberately distinct from every verdict
    # above: "we could not find out" must never render as "fine", which is the
    # entire failure this module exists to correct.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SpokeResult:
    env: str
    status: Status
    server: str | None = None
    # `detail` is built from status text and HTTP codes only. The token is
    # deliberately NOT a field: a dataclass prints every field it holds, so the
    # safest place for a credential is nowhere in the object.
    detail: str = ""

    @property
    def registered(self) -> bool:
        return self.status is not Status.NOT_REGISTERED

    @property
    def ok(self) -> bool:
        return self.status is Status.OK


def _read_cluster_secret(env: str, hub_kubeconfig: Path) -> dict[str, Any] | None:
    """The `cluster-<env>` secret as Argo CD stores it, or None if absent."""
    proc = subprocess.run(  # noqa: S603 - argv list, no shell
        [
            "kubectl",
            "--kubeconfig",
            str(hub_kubeconfig),
            "-n",
            "argocd",
            "get",
            "secret",
            f"cluster-{env}",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        result: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return result


def _probe(server: str, token: str, ca_pem: str) -> tuple[int, str]:
    """GET `<server>/version` with the hub's credential. Returns (status, body).

    `/version` is the same endpoint Argo CD itself calls first -- "failed to get
    server version" is the error the broken hub produced -- and K3s requires
    authentication for it. Probing what the consumer probes keeps the verdict
    aligned with the consumer's experience.
    """
    ctx = ssl.create_default_context(cadata=ca_pem)
    request = urllib.request.Request(  # noqa: S310 - https, CA pinned above
        f"{server.rstrip('/')}/version",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=ctx) as response:  # noqa: S310
            body: str = response.read().decode(errors="replace")[:200]
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        # An HTTP error is an ANSWER: the spoke is up and said no. That is the
        # case the old check could not distinguish from success.
        return int(exc.code), str(exc.reason or "")


def check_spoke(env: str, hub_kubeconfig: Path) -> SpokeResult:
    secret = _read_cluster_secret(env, hub_kubeconfig)
    if not secret:
        return SpokeResult(env, Status.NOT_REGISTERED, detail="no cluster secret on the hub")

    try:
        data = secret["data"]
        server = base64.b64decode(data["server"]).decode()
        config = json.loads(base64.b64decode(data["config"]).decode())
        token = config["bearerToken"]
        ca_pem = base64.b64decode(config["tlsClientConfig"]["caData"]).decode()
    except (KeyError, ValueError, TypeError) as exc:
        return SpokeResult(
            env,
            Status.UNKNOWN,
            detail=f"the cluster secret is not in the expected shape: {type(exc).__name__}",
        )

    try:
        status, _body = _probe(server, token, ca_pem)
    except OSError as exc:
        return SpokeResult(env, Status.UNREACHABLE, server, f"{type(exc).__name__}: {exc}")

    if status in (401, 403):
        return SpokeResult(
            env,
            Status.CREDENTIAL_REFUSED,
            server,
            f"the spoke answered HTTP {status}: it is up, and it refuses the hub's "
            f"credential. Re-run `make register-spoke ENV={env}`.",
        )
    if 200 <= status < 300:
        return SpokeResult(env, Status.OK, server, f"HTTP {status} from the apiserver")
    return SpokeResult(env, Status.UNKNOWN, server, f"unexpected HTTP {status}")


def check_all(envs: list[str], hub_kubeconfig: Path) -> list[SpokeResult]:
    return [check_spoke(env, hub_kubeconfig) for env in envs]
