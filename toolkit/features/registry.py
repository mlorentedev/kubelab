"""Docker Hub registry client + ephemeral-tag pruning (ADR-046).

The one place the project performs *authenticated* registry operations. The
read-only tag-existence check used by promotion lives in ``promotion.py``; this
module adds login/list/delete so the CI janitor can prune ephemeral tags.

Staging runs immutable ``sha-<short>`` tags (one per app per merge to master),
so they accumulate forever. ``prune`` keeps the N most recent per app (rollback
headroom) and deletes the rest, plus any leftover ``-rc.*`` (the RC scheme was
dropped — release-please is the sole semver authority). Prod runs immutable
semver and is never touched here.

The decision of *what* to delete is the pure ``select_stale_tags``; everything
else is I/O. That split keeps the policy unit-testable without a network.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx
import yaml

from toolkit.config.settings import PROJECT_ROOT
from toolkit.core.logging import logger
from toolkit.features import product_registry

_HUB = "https://hub.docker.com/v2"
_ANONYMOUS_HOST = "docker.io/"  # Docker Hub: read through its own API, anonymously
SHA_TAG_PREFIX = "sha-"  # immutable per-commit staging tag scheme (ADR-046)
#: The hex lengths a ``sha-`` tag may carry: what the product image receiver admits (``sha-[0-9a-f]{7,}``).
SHA_TAG_HEX_LENGTHS = range(7, 41)
_RC_MARKER = "-rc."  # dropped scheme; any remaining are dead


def is_docker_hub(registry: str) -> bool:
    """Whether ``registry`` is Docker Hub, the one registry read through its own API rather than OCI."""
    return registry.startswith(_ANONYMOUS_HOST)


@dataclass(frozen=True)
class RegistryCredential:
    """A registry login for an authenticated read; the token never appears in a repr or a message."""

    username: str
    token: str = field(repr=False)


class BearerCache:
    """The pull bearers one proof has been issued, per ``(host, repository)``; a token never appears in its repr.

    A bearer is scoped to one repository and valid for all its tags, so a caller reading many tags of
    one image hands the same cache to every ``tag_digest`` call and trades for a bearer once (#3287).
    Make one per proof: nothing is kept between proofs, and a long-lived credential never enters it.
    """

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}

    def __repr__(self) -> str:
        return f"BearerCache({len(self._tokens)} bearers)"

    def get(self, host: str, repository: str) -> str | None:
        return self._tokens.get((host, repository))

    def put(self, host: str, repository: str, token: str) -> None:
        self._tokens[(host, repository)] = token

    def drop(self, host: str, repository: str) -> None:
        self._tokens.pop((host, repository), None)


def catalog_secret_variable(key: str) -> str:
    """The environment variable for catalog ``key``: its flattened form (``ghcr.pull_token`` is ``GHCR_PULL_TOKEN``)."""
    return re.sub(r"[^A-Za-z0-9]", "_", key).upper()


def catalog_secret(key: str) -> str | None:
    """The value for the catalog ``key`` (a product's ``pull_credential.secret``), or ``None``.

    The environment variable the key flattens to wins when it holds a value: a hosted runner has
    the pull token as an Actions secret and no age key, and the token never needs decrypting there
    (#3286). An empty variable is unset, since an Actions secret nobody created arrives as ``""``.
    Otherwise the catalog is SOPS, so this resolves only where the age key is: a runner with
    neither gets ``None`` and the caller refuses by name. Tests inject a lookup instead.
    """
    variable = catalog_secret_variable(key)
    from_env = os.environ.get(variable, "").strip()
    if from_env:
        # The source, never the value: a stale exported variable shadows a rotated SOPS entry,
        # and a 401 alone would not say which one was used.
        logger.info(f"catalog secret {key}: using {variable} from the environment, not SOPS")
        return from_env
    from toolkit.features.configuration import ConfigurationManager

    return ConfigurationManager("prod").get_secret_by_path(key)


@dataclass(frozen=True)
class TagInfo:
    """A registry tag and its last-push time (ISO8601 sorts chronologically)."""

    name: str
    last_updated: str


def select_stale_tags(
    tags: list[TagInfo],
    retention: int,
    protected: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Pure policy: which tag names to delete.

    Keep the ``retention`` most recent ``sha-*`` tags (newest first by
    ``last_updated``); the rest are stale. Every ``-rc.*`` tag is stale. Returns
    stale sha (oldest first) followed by rc tags.

    ``protected`` names are never returned — a sha pinned by a committed overlay
    (``values/<env>.yaml``) must survive even if it falls outside the retention
    window, or a pending build-once prod re-tag would lose its source (ADR-056).
    """
    if retention < 0:
        raise ValueError(f"retention must be >= 0, got {retention}")
    sha = sorted(
        (t for t in tags if t.name.startswith(SHA_TAG_PREFIX)),
        key=lambda t: t.last_updated,
        reverse=True,
    )
    stale_sha = [t.name for t in sha[retention:]]
    rc = [t.name for t in tags if _RC_MARKER in t.name]
    return [name for name in stale_sha + rc if name not in protected]


# What an OCI registry may answer a manifest read with; asking for none returns 404 on some.
_MANIFEST_TYPES = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def tag_exists(
    registry: str, image_name: str, tag: str, http: Callable[..., httpx.Response] | None = None
) -> bool | None:
    """Whether ``tag`` exists for an image. ``None`` (unverified) when the registry will not say.

    Anonymous read, used by promotion to refuse promoting a tag that does not
    exist (it would ``ImagePullBackOff``). Lives here so all registry access has
    one home. Docker Hub is read through its own API; any other registry through
    an OCI ``HEAD /v2/<name>/manifests/<tag>`` (``http`` replaces ``httpx.head``
    for tests). Both answer the same way: 200 is ``True``, 404 ``False``, and a
    private registry (401/403), a rate limit or 5xx, any other answer or an
    unreachable host is ``None`` with a warning naming the registry (IDP-053 D3,
    #3272). The receiver holds no registry credential (ADR-067 C2), so a private
    image stays unverified here; ``promote`` proceeds on ``None``.
    """
    if not registry.startswith(_ANONYMOUS_HOST):
        return _oci_tag_exists(registry, image_name, tag, http or httpx.head)
    namespace = registry.split("/", 1)[1]
    url = f"{_HUB}/repositories/{namespace}/{image_name}/tags/{tag}"
    try:
        resp = httpx.get(url, timeout=15.0)
    except httpx.HTTPError as exc:
        logger.warning(f"docker.io: {image_name}:{tag} unverified, the registry is unreachable ({exc})")
        return None
    return _tag_answer("docker.io", image_name, tag, resp.status_code)


def _tag_answer(host: str, image_name: str, tag: str, status: int) -> bool | None:
    """The tri-state a tag lookup's HTTP status means: 200 present, 404 absent, anything else unverified."""
    if status in (200, 404):
        return status == 200
    logger.warning(f"{host}: {image_name}:{tag} unverified, the registry answered HTTP {status}")
    return None


def _oci_tag_exists(registry: str, image_name: str, tag: str, http: Callable[..., httpx.Response]) -> bool | None:
    host, _, owner = registry.partition("/")
    repository = "/".join(part for part in (owner, image_name) if part)
    url = f"https://{host}/v2/{repository}/manifests/{tag}"
    try:
        resp = http(url, headers={"Accept": _MANIFEST_TYPES}, timeout=15.0)
    except httpx.HTTPError as exc:
        logger.warning(f"{host}: {image_name}:{tag} unverified, the registry is unreachable ({exc})")
        return None
    return _tag_answer(host, image_name, tag, resp.status_code)


def tag_digest(
    registry: str,
    image_name: str,
    tag: str,
    credential: RegistryCredential | None = None,
    http: Callable[..., httpx.Response] | None = None,
    bearers: BearerCache | None = None,
) -> str | None:
    """The manifest digest a tag names, or ``None`` when it cannot be read (absent tag, refused login, no digest).

    Unlike ``tag_exists`` this never answers "skip": a caller proving two tags are
    one image treats ``None`` as no proof. Docker Hub is read anonymously through its
    API; any other registry through an OCI manifest ``HEAD``, trading ``credential``
    (or nothing, for a public package) for a bearer token when the registry asks
    (IDP-053 D3, the authenticated half). ``http`` replaces ``httpx.request`` (``httpx.get`` on Docker Hub) for tests.
    ``bearers`` keeps the bearer between calls: a read that finds the repository's bearer there sends it
    first, and on a 401 (it expired) trades for a new one once. Without it each call trades for its own.
    """
    if not is_docker_hub(registry):
        cache = bearers if bearers is not None else BearerCache()
        return _oci_tag_digest(registry, image_name, tag, credential, http or httpx.request, cache)
    namespace = registry.split("/", 1)[1]
    try:
        url = f"{_HUB}/repositories/{namespace}/{image_name}/tags/{tag}"
        resp = httpx.get(url, timeout=15.0) if http is None else http("GET", url, timeout=15.0)
    except httpx.HTTPError as exc:
        logger.warning(f"Could not reach registry to read the digest of {image_name}:{tag} ({exc})")
        return None
    if resp.status_code != 200:
        return None
    return _digest_or_none(resp.json().get("digest"))


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _digest_or_none(value: object) -> str | None:
    """``value`` when it is a whole ``sha256:<64 lowercase hex>`` digest: a prefix match would let ``sha256:`` pass."""
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else None


_HTTPS_PORT = 443
_CHALLENGE_PARAM = re.compile(r'(\w+)="([^"]*)"')


def _oci_tag_digest(
    registry: str,
    image_name: str,
    tag: str,
    credential: RegistryCredential | None,
    http: Callable[..., httpx.Response],
    bearers: BearerCache,
) -> str | None:
    host, _, owner = registry.partition("/")
    repository = "/".join(part for part in (owner, image_name) if part)
    subject = f"{host}: the digest of {image_name}:{tag}"
    url = f"https://{host}/v2/{repository}/manifests/{tag}"
    try:
        resp = _manifest_head(host, repository, url, credential, http, bearers)
    except httpx.HTTPError as exc:
        logger.warning(f"{subject} is unread, the registry is unreachable ({exc})")
        return None
    if resp is None:
        return None
    digest = _digest_or_none(resp.headers.get("docker-content-digest")) if resp.status_code == 200 else None
    if digest is None:
        logger.warning(f"{subject} is unread, the registry answered HTTP {resp.status_code} with no sha256 digest")
    return digest


def _manifest_head(
    host: str,
    repository: str,
    url: str,
    credential: RegistryCredential | None,
    http: Callable[..., httpx.Response],
    bearers: BearerCache,
) -> httpx.Response | None:
    """HEAD a manifest with the repository's cached bearer (none yet: anonymously); ``None`` when no bearer can be had.

    A 401 means the registry wants a bearer, or the cached one expired: trade the credential for a fresh one,
    keep it, and read once more. A 401 to that fresh bearer is final and is not kept, so a refusal never loops.
    """
    headers = {"Accept": _MANIFEST_TYPES}
    cached = bearers.get(host, repository)
    if cached is not None:
        headers["Authorization"] = f"Bearer {cached}"
    resp = http("HEAD", url, headers=headers, timeout=15.0)
    if resp.status_code != 401:
        return resp
    bearers.drop(host, repository)
    token = _bearer_token(host, repository, resp.headers.get("www-authenticate", ""), credential, http)
    if token is None:
        return None
    resp = http("HEAD", url, headers={**headers, "Authorization": f"Bearer {token}"}, timeout=15.0)
    if resp.status_code != 401:
        bearers.put(host, repository, token)
    return resp


def _token_of(resp: httpx.Response) -> str | None:
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    token = body.get("token") or body.get("access_token") if isinstance(body, dict) else None
    return token if isinstance(token, str) and token else None


def _is_own_endpoint(realm: SplitResult, own: SplitResult) -> bool:
    try:
        ports = (realm.port or _HTTPS_PORT, own.port or _HTTPS_PORT)
    except ValueError:  # a port that is not a number
        return False
    return (
        realm.scheme == "https"
        and realm.hostname == own.hostname
        and ports[0] == ports[1]
        and "@" not in realm.netloc  # no userinfo: it would name another host to a lenient client
    )


def _bearer_token(
    host: str,
    repository: str,
    challenge: str,
    credential: RegistryCredential | None,
    http: Callable[..., httpx.Response],
) -> str | None:
    """Trade ``credential`` for a pull token at the realm the registry names, or ``None`` with a warning.

    The credential goes only to an https realm on the registry's own host and port, with no
    userinfo: the realm comes from the registry's answer, so an unchecked one would send the
    long-lived token wherever it points. ``host`` may carry a port (``host:5443``).
    """
    params = dict(_CHALLENGE_PARAM.findall(challenge))
    realm = urlsplit(params.get("realm", ""))
    own = urlsplit(f"https://{host}")
    if not challenge.lower().startswith("bearer "):
        logger.warning(f"{host}: unread, it asked for a login this client does not speak (not a Bearer challenge)")
        return None
    if not _is_own_endpoint(realm, own):
        logger.warning(
            f"{host}: unread, its token endpoint is not its own https endpoint; a registry that delegates its "
            "login to another host (as Docker Hub does) is not supported by this reader"
        )
        return None
    query = {"service": params.get("service", host), "scope": params.get("scope", f"repository:{repository}:pull")}
    auth = (credential.username, credential.token) if credential else None
    resp = http("GET", realm.geturl(), params=query, auth=auth, timeout=15.0)
    token = _token_of(resp)
    if token is None:
        who = f"the login of {credential.username}" if credential else "an anonymous read"
        logger.warning(f"{host}: unread, its token endpoint refused {who} (HTTP {resp.status_code})")
        return None
    return token


class DockerHubClient:
    """Minimal authenticated Docker Hub v2 client (login, list, delete)."""

    def __init__(self, namespace: str, token: str | None = None) -> None:
        self.namespace = namespace
        self._token = token

    @classmethod
    def from_env(cls) -> DockerHubClient:
        """Build a client from ``DOCKERHUB_USERNAME``/``DOCKERHUB_TOKEN`` (CI secrets).

        On a workstation they come from SOPS, which `get_settings()` injects into
        the environment. Importing the toolkit no longer does that (TOOL-097), so
        build settings here when CI has not set them.
        """
        if not (os.environ.get("DOCKERHUB_USERNAME") and os.environ.get("DOCKERHUB_TOKEN")):
            from toolkit.config.settings import get_settings

            get_settings()
        user = os.environ.get("DOCKERHUB_USERNAME")
        password = os.environ.get("DOCKERHUB_TOKEN")
        if not user or not password:
            raise ValueError("DOCKERHUB_USERNAME and DOCKERHUB_TOKEN must be set in the environment")
        return cls(namespace=user, token=cls._login(user, password))

    @staticmethod
    def _login(user: str, password: str) -> str:
        resp = httpx.post(f"{_HUB}/users/login", json={"username": user, "password": password}, timeout=30.0)
        resp.raise_for_status()
        token = resp.json().get("token")
        if not token:
            raise ValueError("Docker Hub login returned no token")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def list_tags(self, repo: str) -> list[TagInfo]:
        """All tags for ``<namespace>/<repo>``. A missing repo yields ``[]`` (nothing to prune)."""
        tags: list[TagInfo] = []
        url: str | None = f"{_HUB}/repositories/{self.namespace}/{repo}/tags/?page_size=100"
        while url:
            resp = httpx.get(url, headers=self._headers(), timeout=30.0)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            for result in data.get("results", []):
                name = result.get("name")
                if name:
                    tags.append(TagInfo(name=name, last_updated=result.get("last_updated") or ""))
            url = data.get("next")
        return tags

    def delete_tag(self, repo: str, tag: str) -> bool:
        """Delete one tag. 204 (deleted) and 404 (already gone) are both success."""
        resp = httpx.delete(
            f"{_HUB}/repositories/{self.namespace}/{repo}/tags/{tag}/",
            headers=self._headers(),
            timeout=30.0,
        )
        if resp.status_code in (204, 404):
            return True
        logger.warning(f"Failed to delete {repo}:{tag} (HTTP {resp.status_code})")
        return False


def image_repositories(
    apps: list[str], common: dict[str, Any] | None = None, registry: Path | None = None
) -> dict[str, str]:
    """The Docker Hub repository each app is deployed from (#2511), keyed by app.

    The same sources the generators read: ``derived_image`` for a contract-managed
    product, ``apps.platform.<app>.image_name`` for an in-tree one, and
    ``edge.errors.image_name`` for errors. A repository is a name under the hub
    namespace, so only the last segment of an image is kept. A product whose image
    lives in another registry (its entry's ``image_registry``) is not the hub client's
    to list or delete from, so it is left out of the result.
    """
    if common is None:
        common = (
            yaml.safe_load((PROJECT_ROOT / product_registry.COMMON_VALUES_RELPATH).read_text(encoding="utf-8")) or {}
        )
    repos: dict[str, str] = {}
    for app in apps:
        if app == "errors":
            name = ((common.get("edge") or {}).get("errors") or {}).get("image_name")
            key = "edge.errors.image_name"
        elif product_registry.product(app, registry).contract_managed:
            image = product_registry.derived_image(app, registry)
            prefix = f"{product_registry.platform_registry()}/"
            if not image.startswith(prefix):
                logger.info(f"{app}: image {image} is not in {prefix.rstrip('/')}; not pruned here")
                continue
            name = image.removeprefix(prefix)
            key = "the product registry"
        else:
            name = (((common.get("apps") or {}).get("platform") or {}).get(app) or {}).get("image_name")
            key = f"apps.platform.{app}.image_name"
        if not name:
            raise ValueError(f"No image repository for '{app}': {key} is not set")
        if "/" in name:
            # The hub client lists and deletes under its own namespace, so a name
            # that carries another one would prune the wrong repository.
            raise ValueError(f"Image repository for '{app}' from {key} is '{name}', not a bare name")
        repos[app] = name
    return repos


def prune(
    repos: dict[str, str],
    retention: int,
    dry_run: bool,
    client: DockerHubClient | None = None,
    protected: dict[str, set[str]] | None = None,
) -> int:
    """Prune stale tags in each app's repository (``repos`` maps app -> repo).

    ``protected`` maps app -> sha tags pinned by a committed overlay; those are
    never deleted (ADR-056 prune guard). Returns the count deleted (or, in
    ``dry_run``, that would be deleted).
    """
    client = client or DockerHubClient.from_env()
    protected = protected or {}
    total = 0
    for app, repo in repos.items():
        tags = client.list_tags(repo)
        keep = protected.get(app, set())
        stale = select_stale_tags(tags, retention, protected=keep)
        sha_count = sum(1 for t in tags if t.name.startswith(SHA_TAG_PREFIX))
        kept = min(sha_count, retention)
        if not stale:
            logger.info(f"{repo}: nothing to prune ({sha_count} sha-* tags, all {kept} retained)")
            continue
        deleted = 0
        for tag in stale:
            if dry_run:
                logger.info(f"{repo}: would delete {tag}")
                deleted += 1
            elif client.delete_tag(repo, tag):
                logger.info(f"{repo}: deleted {tag}")
                deleted += 1
        logger.info(f"{repo}: {deleted} deleted, kept {kept} of {sha_count} sha-*")
        total += deleted
    logger.success(f"Prune complete{' (dry-run)' if dry_run else ''}: {total} tag(s)")
    return total
