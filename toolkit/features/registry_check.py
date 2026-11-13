"""Prove a Gitea registry pull token by CONSEQUENCE (IDP-053 S2c, AC4).

The pull token's grant is declared in `common.yaml` and pinned by equality, and that says what
it should hold. Whether it reaches a given product's package depends on the package owner's
visibility and on the units of the teams the reviewer's account sits in (D2), which no diff
shows. So this pulls a manifest with the token and reports the status the registry answers.

The negative half is the same pull aimed at a package the token must not reach, and it passes
only on a denial: a pull that succeeds proves the token reaches too much, and a 404, a 5xx or
an unreachable registry proves nothing, so none of them may read as a denial (lesson-408).

The token rides only in the request's `auth`, never in a URL, a parameter we print or a message
this module builds. A registry that challenges with a Bearer realm is answered there only when
the realm is the registry's own HTTPS host and port: the challenge is input from the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

from toolkit.features.product_contract import ContractError
from toolkit.features.product_registry import Product

#: Seconds a registry may take to answer one request: a hung registry must not hang the check.
TIMEOUT = 15

#: What a manifest GET accepts: the OCI and Docker v2 manifests and their indexes.
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

#: `<owner>/<name>` and any deeper path: segments of letters, digits, `.`, `_`, `-`, none empty or dot-led.
_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)+")
_CHALLENGE_PARAM = re.compile(r'(\w+)="([^"]*)"')

#: The statuses that mean "the registry refused this login for this package".
DENIED = (401, 403)


class _Response(Protocol):
    status_code: int
    headers: Any

    def json(self) -> Any: ...


class _Session(Protocol):
    def get(self, url: str, **kwargs: Any) -> _Response: ...


class NoVerdict(Exception):  # noqa: N818 - a verdict that could not be reached, not an error class
    """The handshake did not finish, so the token was never tested. The text is ours, never the network's."""


@dataclass(frozen=True)
class CheckResult:
    """The verdict: `ok` is the exit code, `status` the registry's answer (None when there was none)."""

    ok: bool
    status: int | None
    message: str


def _refused(error: str, why: str, fix: str) -> CheckResult:
    return CheckResult(False, None, str(ContractError(error, why, fix)))


def _authority(url: str) -> tuple[str, int] | None:
    """The (host, port) an https URL reaches, the default port made explicit; None when it names none."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return None
    return (parts.hostname, port or 443) if parts.hostname else None


def manifest_status(session: _Session, host: str, package: str, tag: str, username: str, token: str) -> int:
    """The status the registry at `host` answers to a manifest GET for `package:tag` with this login.

    Basic first, which Gitea's registry accepts with an access token as the password. A registry
    that answers 401 with a Bearer challenge is asked for a token at its realm and the pull is
    repeated once with it; the status of that second request is the answer. A challenge that cannot
    be answered (a realm that is not HTTPS or is on another host or port, a token endpoint with no
    token) raises `NoVerdict`: the 401 that carried it says nothing about the token, so it must not
    be returned as a denial.
    """
    url = f"https://{host}/v2/{package}/manifests/{tag}"
    first = session.get(url, auth=(username, token), headers={"Accept": ACCEPT}, timeout=TIMEOUT, allow_redirects=False)
    challenge = first.headers.get("WWW-Authenticate", "") if first.status_code == 401 else ""
    if not challenge.lower().startswith("bearer "):
        return first.status_code
    params = dict(_CHALLENGE_PARAM.findall(challenge))
    realm = params.get("realm", "")
    # Never send the login anywhere but the registry's own scheme, host and port, and never read
    # the 401 that carried the challenge as a denial: the token was not tested.
    if urlsplit(realm).scheme != "https":
        raise NoVerdict("the registry's challenge points at a realm that is not HTTPS, so the token was never tested")
    if _authority(realm) is None or _authority(realm) != _authority(url):
        raise NoVerdict("the registry's challenge points at another host or port, so the token was never tested")
    asked = session.get(
        realm,
        auth=(username, token),
        params={"service": params.get("service", ""), "scope": f"repository:{package}:pull"},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    if asked.status_code != 200:
        return asked.status_code
    body = asked.json()
    bearer = body.get("token") or body.get("access_token") if isinstance(body, dict) else None
    if not bearer:
        raise NoVerdict("the registry's token endpoint answered 200 with no token")
    second = session.get(
        url,
        headers={"Accept": ACCEPT, "Authorization": f"Bearer {bearer}"},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    return second.status_code


def default_package(entry: Product, app: str) -> str:
    """The app's own package: the owner path of its registry plus its image name (the derived image, Q7)."""
    owner = (entry.image_registry or "").split("/", 1)[1:]
    return "/".join([*owner, entry.image_name or app])


def refuse_unpullable(entry: Product, app: str) -> CheckResult | None:
    """A refusal when `app` has no private registry and pull login to check, else None."""
    if entry.private and entry.pull_credential is not None and entry.image_host is not None:
        return None
    return _refused(
        f"'{app}' has no private registry to pull from",
        "a pull is proven for a private product, whose entry names the registry and the login that reads it.",
        "run it for a product with `private: true`, `image_registry` and `pull_credential` in products.yaml.",
    )


def check_pull(
    entry: Product,
    app: str,
    *,
    package: str | None,
    expect_denied: bool,
    tag: str,
    token: str,
    session: _Session,
) -> CheckResult:
    """Pull `package:tag` (the app's own package when `package` is None) and judge the answer.

    Without `expect_denied` it passes only on 200; with it, only on 401 or 403. Everything else,
    an unreachable registry and an empty or malformed `package` included, fails.
    """
    unpullable = refuse_unpullable(entry, app)
    if unpullable is not None:
        return unpullable
    assert entry.pull_credential is not None and entry.image_host is not None  # noqa: S101 - narrowed above
    target = default_package(entry, app) if package is None else package
    if not _PACKAGE.fullmatch(target):
        return _refused(
            f"'{target}' is not a package path",
            "a package is named <owner>/<name>; an empty or malformed one pulls nothing and could read as a denial.",
            "pass --package <owner>/<name>, or omit it to pull the app's own package.",
        )
    host = entry.image_host
    try:
        status = manifest_status(session, host, target, tag, entry.pull_credential.username, token)
    except NoVerdict as exc:
        return CheckResult(False, None, f"{host} gave no verdict on {target}:{tag}: {exc}")
    except (requests.RequestException, ValueError) as exc:
        # The type, never the text: a library's message can carry the request it failed on.
        return CheckResult(
            False, None, f"{host} could not be asked about {target}:{tag} ({type(exc).__name__}): no verdict"
        )
    subject = f"{host}/{target}:{tag} answered {status} to the {entry.pull_credential.username} login"
    if expect_denied:
        if status in DENIED:
            return CheckResult(True, status, f"{subject}: denied, as expected")
        return CheckResult(
            False, status, f"{subject}: expected 401 or 403 (a 200 means the token reaches a package it must not)"
        )
    if status == 200:
        return CheckResult(True, status, f"{subject}: the manifest was served")
    hint = " (pass --expect-denied to assert a package the token must not reach)" if status in DENIED else ""
    return CheckResult(False, status, f"{subject}: expected 200{hint}")
