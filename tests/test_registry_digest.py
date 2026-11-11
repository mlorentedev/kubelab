"""`registry.tag_digest` and the release proof on a registry that is not Docker Hub (IDP-053 S8, #2627).

The proof asks two tags for their manifest digest. On GHCR and on the Gitea registry that read is an
OCI ``HEAD /v2/<name>/manifests/<tag>`` that the registry answers 401 to until the caller trades the
catalogued pull credential for a bearer token at the registry's own token endpoint. The fake below
behaves that way, so a test fails if the credential is never sent, is sent to the wrong place, or is
sent where a manifest should be. The HTTP call and the secret lookup are injected: no test here
reaches a network or decrypts a secrets file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from toolkit.features import product_release, registry
from toolkit.features.product_contract import ContractError

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
PULL_TOKEN = "ghp_not-a-real-token"  # noqa: S105 - a fixture, not a credential
BEARER = "bearer-issued-by-the-registry"
SHA = "661a205c0ffee0ddba11ca5cadeba5eba11fade1"
VERSION = "1.4.0"
CATALOG_KEY = "ghcr.pull_token"

REGISTRIES = {
    "ghcr": ("ghcr.io/acme", "ghcr.io", "https://ghcr.io/token"),
    "gitea": ("gitea.kubelab.live/personal", "gitea.kubelab.live", "https://gitea.kubelab.live/v2/token"),
}


class _Oci:
    """An OCI registry that demands a bearer token for manifests and issues one to the right login."""

    def __init__(self, host: str, realm: str, digests: dict[str, str], *, login: tuple[str, str] | None = None):
        self.host, self.realm, self.digests, self.login = host, realm, digests, login
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        if url.startswith(self.realm):
            return self._token(kwargs.get("auth"))
        assert url.startswith(f"https://{self.host}/v2/"), f"a read left the registry: {url}"
        if kwargs.get("headers", {}).get("Authorization") != f"Bearer {BEARER}":
            repository = url.split("/v2/", 1)[1].split("/manifests/", 1)[0]
            challenge = f'Bearer realm="{self.realm}",service="{self.host}",scope="repository:{repository}:pull"'
            return httpx.Response(401, headers={"www-authenticate": challenge})
        digest = self.digests.get(url.rsplit("/", 1)[1])
        if digest is None:
            return httpx.Response(404)
        return httpx.Response(200, headers={"docker-content-digest": digest})

    def _token(self, auth: tuple[str, str] | None) -> httpx.Response:
        if self.login is not None and auth != self.login:
            return httpx.Response(401)
        return httpx.Response(200, json={"token": BEARER})

    def manifest_reads(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [c for c in self.calls if not c[1].startswith(self.realm)]


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    warn = MagicMock()
    monkeypatch.setattr(registry.logger, "warning", warn)
    return warn


def _oci(kind: str, digests: dict[str, str], login: tuple[str, str] | None = None) -> tuple[str, _Oci]:
    path, host, realm = REGISTRIES[kind]
    return path, _Oci(host, realm, digests, login=login)


CREDENTIAL = registry.RegistryCredential("deploy-bot", PULL_TOKEN)


@pytest.mark.parametrize("kind", ["ghcr", "gitea"])
class TestAuthenticatedManifestDigest:
    def test_the_digest_is_read_with_the_catalogued_credential(self, kind: str) -> None:
        path, http = _oci(kind, {VERSION: DIGEST}, login=("deploy-bot", PULL_TOKEN))

        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http) == DIGEST

    def test_the_credential_goes_to_the_token_endpoint_and_a_bearer_goes_to_the_manifest(self, kind: str) -> None:
        path, http = _oci(kind, {VERSION: DIGEST}, login=("deploy-bot", PULL_TOKEN))

        registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http)

        (token_call,) = [c for c in http.calls if c[1].startswith(http.realm)]
        assert token_call[2]["auth"] == ("deploy-bot", PULL_TOKEN)
        owner = path.split("/", 1)[1]
        assert token_call[2]["params"]["scope"] == f"repository:{owner}/web:pull"
        for _, url, kwargs in http.manifest_reads():
            assert PULL_TOKEN not in url + str(kwargs.get("headers")), "the long-lived token reached a manifest read"
            assert "auth" not in kwargs

    def test_a_refused_login_is_none_naming_the_registry_and_never_the_token(
        self, kind: str, warnings: MagicMock
    ) -> None:
        path, http = _oci(kind, {VERSION: DIGEST}, login=("deploy-bot", "something-else"))

        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http) is None

        (message,), _ = warnings.call_args
        assert path.split("/")[0] in message and "401" in message
        assert PULL_TOKEN not in message

    def test_an_absent_tag_is_none(self, kind: str) -> None:
        path, http = _oci(kind, {})

        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http) is None

    def test_a_public_package_is_read_with_no_credential(self, kind: str) -> None:
        path, http = _oci(kind, {VERSION: DIGEST})

        assert registry.tag_digest(path, "web", VERSION, http=http) == DIGEST

        (token_call,) = [c for c in http.calls if c[1].startswith(http.realm)]
        assert token_call[2].get("auth") is None


class TestARegistryThatCannotBeRead:
    def test_a_token_endpoint_on_another_host_never_receives_the_credential(self, warnings: MagicMock) -> None:
        seen: list[str] = []

        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            seen.append(url)
            challenge = 'Bearer realm="https://auth.elsewhere.example/token",service="ghcr.io"'
            return httpx.Response(401, headers={"www-authenticate": challenge})

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, CREDENTIAL, http=http) is None

        assert seen == ["https://ghcr.io/v2/acme/web/manifests/" + VERSION]
        assert "ghcr.io" in warnings.call_args.args[0]

    def test_a_registry_that_challenges_in_a_scheme_it_does_not_speak_is_none(self, warnings: MagicMock) -> None:
        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(401, headers={"www-authenticate": 'Negotiate realm="x"'})

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, CREDENTIAL, http=http) is None
        assert "ghcr.io" in warnings.call_args.args[0]

    @pytest.mark.parametrize("digest", [None, "md5:nope"], ids=["no header", "not a sha256 digest"])
    def test_an_answer_with_no_usable_digest_is_none(self, digest: str | None, warnings: MagicMock) -> None:
        headers = {"docker-content-digest": digest} if digest else {}

        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, headers=headers)

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, http=http) is None
        assert "ghcr.io" in warnings.call_args.args[0]

    def test_an_unreachable_registry_is_none_naming_it(self, warnings: MagicMock) -> None:
        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("no route")

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, CREDENTIAL, http=http) is None
        assert "ghcr.io" in warnings.call_args.args[0]


class TestTheCatalogSecret:
    def test_it_reads_the_key_through_the_configuration_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = MagicMock()
        manager.get_secret_by_path.return_value = PULL_TOKEN
        monkeypatch.setattr("toolkit.features.configuration.ConfigurationManager", lambda env: manager)

        assert registry.catalog_secret(CATALOG_KEY) == PULL_TOKEN
        manager.get_secret_by_path.assert_called_once_with(CATALOG_KEY)

    def test_the_credential_does_not_print_its_token(self) -> None:
        assert PULL_TOKEN not in repr(CREDENTIAL) and PULL_TOKEN not in str(CREDENTIAL)


# --- the release proof on a private registry -----------------------------------------------------

_PRODUCTS = """\
products:
  api:
    forge: in-tree
  resume:
    forge: github
    repository: acme/resume
    receiver: generic
    private: true
    image_registry: ghcr.io/acme
    pull_credential:
      username: deploy-bot
      secret: {key}
"""


@pytest.fixture
def private_registry(tmp_path: Path) -> Path:
    path = tmp_path / "products.yaml"
    path.write_text(_PRODUCTS.format(key=CATALOG_KEY), encoding="utf-8")
    return path


def _prove(registry_file: Path, http: Any, secret: Any) -> str:
    return product_release._prove_image("resume", VERSION, SHA, registry_file, http=http, secret=secret)


def _secret(value: str | None) -> MagicMock:
    return MagicMock(return_value=value)


class TestTheReleaseProofOnAPrivateRegistry:
    def test_the_release_is_proven_with_the_entrys_credential(self, private_registry: Path) -> None:
        http = _Oci(
            "ghcr.io",
            "https://ghcr.io/token",
            {VERSION: DIGEST, f"sha-{SHA[:7]}": DIGEST},
            login=("deploy-bot", PULL_TOKEN),
        )
        secret = _secret(PULL_TOKEN)

        assert _prove(private_registry, http, secret) == DIGEST

        secret.assert_called_once_with(CATALOG_KEY)

    @pytest.mark.parametrize("length", [7, 10])
    def test_a_sha_tag_of_either_length_is_proven(self, private_registry: Path, length: int) -> None:
        """#2627 AC1: a check fixed at 7 hex digits fails the 10-digit product."""
        digests = {VERSION: DIGEST, f"sha-{SHA[:length]}": DIGEST}
        http = _Oci("ghcr.io", "https://ghcr.io/token", digests, login=("deploy-bot", PULL_TOKEN))

        assert _prove(private_registry, http, _secret(PULL_TOKEN)) == DIGEST

        assert http.manifest_reads()[-1][1].endswith(f"/manifests/sha-{SHA[:length]}")

    def test_a_tag_naming_another_build_is_refused(self, private_registry: Path) -> None:
        digests = {VERSION: DIGEST, f"sha-{SHA[:7]}": OTHER}
        http = _Oci("ghcr.io", "https://ghcr.io/token", digests, login=("deploy-bot", PULL_TOKEN))

        with pytest.raises(ContractError) as refused:
            _prove(private_registry, http, _secret(PULL_TOKEN))

        assert "different digests" in refused.value.error

    @pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
    def test_a_missing_credential_is_refused_by_registry_before_any_read(
        self, private_registry: Path, value: str | None
    ) -> None:
        """#2627 AC2: ERROR / WHY / FIX name the registry and the catalog key, not 'check that the tag exists'."""
        http = MagicMock()

        with pytest.raises(ContractError) as refused:
            _prove(private_registry, http, _secret(value))

        e = refused.value
        assert "ghcr.io" in e.error and CATALOG_KEY in e.error
        assert "ghcr.io" in e.why and e.fix
        assert "exists" not in e.fix
        http.assert_not_called()

    def test_a_refused_login_names_the_registry_and_the_login_not_a_missing_tag(self, private_registry: Path) -> None:
        http = _Oci("ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST}, login=("deploy-bot", "rotated-away"))

        with pytest.raises(ContractError) as refused:
            _prove(private_registry, http, _secret(PULL_TOKEN))

        e = refused.value
        assert "ghcr.io" in e.error and "deploy-bot" in e.why
        assert PULL_TOKEN not in f"{e.error}{e.why}{e.fix}"

    def test_a_public_entry_on_another_registry_is_read_anonymously(self, tmp_path: Path) -> None:
        path = tmp_path / "products.yaml"
        path.write_text(
            "products:\n  resume:\n    forge: github\n    repository: acme/resume\n    receiver: generic\n"
            "    image_registry: ghcr.io/acme\n",
            encoding="utf-8",
        )
        http = _Oci("ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST, f"sha-{SHA[:7]}": DIGEST})
        secret = _secret(PULL_TOKEN)

        assert _prove(path, http, secret) == DIGEST

        secret.assert_not_called()


# --- release-contract on a Gitea product, end to end through the adapter -------------------------

_GITEA_PRODUCTS = """\
products:
  api:
    forge: in-tree
  beta:
    forge: gitea
    repository: personal/beta
    receiver: generic
    private: true
    image_registry: gitea.kubelab.live/personal
    pull_credential:
      username: registry-reader
      secret: gitea.registry_pull_token
"""

_GITEA_CONTRACT = """\
schema_version: 1
image: gitea.kubelab.live/personal/beta
port: 8080
health_path: /
hostnames:
  staging: staging.beta.example
auth: public
secrets: []
"""


class _GiteaReads:
    """Stands in for ``GiteaClient``: the two reads release-contract makes, answered from memory."""

    instances: list[_GiteaReads] = []

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token, self.calls = url, token, []
        _GiteaReads.instances.append(self)

    def get_tag(self, owner: str, name: str, tag: str) -> str | None:
        self.calls.append(("get_tag", owner, name, tag))
        return SHA if tag == f"v{VERSION}" else None

    def get_raw_file(self, owner: str, name: str, path: str, ref: str) -> str:
        self.calls.append(("get_raw_file", owner, name, path, ref))
        return _GITEA_CONTRACT


def test_release_contract_on_a_gitea_product_reads_through_the_adapter_and_the_private_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The contract comes from Gitea at the tagged commit and the proof from its registry with the catalogued login."""
    products = tmp_path / "products.yaml"
    products.write_text(_GITEA_PRODUCTS, encoding="utf-8")
    monkeypatch.setenv("GITEA_URL", "https://gitea.invalid")
    monkeypatch.setenv("GITEA_REPO_READER_TOKEN", "not-a-real-token")
    monkeypatch.setattr("toolkit.features.forge_adapter.GiteaClient", _GiteaReads)
    _GiteaReads.instances.clear()
    realm = "https://gitea.kubelab.live/v2/token"
    http = _Oci(
        "gitea.kubelab.live", realm, {VERSION: DIGEST, f"sha-{SHA[:10]}": DIGEST}, login=("registry-reader", PULL_TOKEN)
    )
    secret = _secret(PULL_TOKEN)
    out = tmp_path / "out" / "beta.yaml"

    release = product_release.fetch_release_contract("beta", VERSION, out, products, http=http, secret=secret)

    assert (release.repository, release.sha, release.digest) == ("personal/beta", SHA, DIGEST)
    assert out.read_text(encoding="utf-8") == _GITEA_CONTRACT
    secret.assert_called_once_with("gitea.registry_pull_token")
    (client,) = _GiteaReads.instances
    assert [call[0] for call in client.calls] == ["get_tag", "get_raw_file"]
    assert client.calls[1][-1] == SHA, "the contract is read at the release commit, not a branch"
