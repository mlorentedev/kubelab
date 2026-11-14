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
BOT = "deploy-bot"
READER = "registry-reader"
STALE_TOKEN = "fixture-rotated-away"  # noqa: S105 - a fixture, not a credential
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
        if not self._accepts(kwargs.get("headers", {}).get("Authorization")):
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
        return httpx.Response(200, json={"token": self._issue()})

    def _issue(self) -> str:
        return BEARER

    def _accepts(self, authorization: str | None) -> bool:
        return authorization == f"Bearer {BEARER}"

    def manifest_reads(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [c for c in self.calls if not c[1].startswith(self.realm)]

    def token_exchanges(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [c for c in self.calls if c[1].startswith(self.realm)]


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    warn = MagicMock()
    monkeypatch.setattr(registry.logger, "warning", warn)
    return warn


def _oci(kind: str, digests: dict[str, str], login: tuple[str, str] | None = None) -> tuple[str, _Oci]:
    path, host, realm = REGISTRIES[kind]
    return path, _Oci(host, realm, digests, login=login)


CREDENTIAL = registry.RegistryCredential(BOT, PULL_TOKEN)


@pytest.mark.parametrize("kind", ["ghcr", "gitea"])
class TestAuthenticatedManifestDigest:
    def test_the_digest_is_read_with_the_catalogued_credential(self, kind: str) -> None:
        path, http = _oci(kind, {VERSION: DIGEST}, login=(BOT, PULL_TOKEN))

        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http) == DIGEST

    def test_the_credential_goes_to_the_token_endpoint_and_a_bearer_goes_to_the_manifest(self, kind: str) -> None:
        path, http = _oci(kind, {VERSION: DIGEST}, login=(BOT, PULL_TOKEN))

        registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http)

        (token_call,) = [c for c in http.calls if c[1].startswith(http.realm)]
        assert token_call[2]["auth"] == (BOT, PULL_TOKEN)
        owner = path.split("/", 1)[1]
        assert token_call[2]["params"]["scope"] == f"repository:{owner}/web:pull"
        for _, url, kwargs in http.manifest_reads():
            assert PULL_TOKEN not in url + str(kwargs.get("headers")), "the long-lived token reached a manifest read"
            assert "auth" not in kwargs

    def test_a_refused_login_is_none_naming_the_registry_and_never_the_token(
        self, kind: str, warnings: MagicMock
    ) -> None:
        path, http = _oci(kind, {VERSION: DIGEST}, login=(BOT, STALE_TOKEN))

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


def _challenging(challenge: str, seen: list[str], *, token_status: int = 200) -> Any:
    """A registry that answers every manifest read with ``challenge`` and every GET with a token body."""

    def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
        seen.append(f"{method} {url}")
        if method == "GET":
            return httpx.Response(token_status, json={"token": BEARER})
        return httpx.Response(401, headers={"www-authenticate": challenge})

    return http


class TestTheCredentialGoesOnlyWhereTheRegistryItselfAsks:
    @pytest.mark.parametrize(
        "realm",
        [
            "http://ghcr.io/token",
            "https://ghcr.io:8443/token",
            "https://user:pass@ghcr.io/token",
            "https://user@ghcr.io/token",
            "https://:pass@ghcr.io/token",
            "https://ghcr.io.elsewhere.example/token",
        ],
        ids=["plain http", "another port", "userinfo", "username only", "password only", "lookalike host"],
    )
    def test_a_realm_that_is_not_the_registrys_own_https_endpoint_gets_no_request(self, realm: str) -> None:
        seen: list[str] = []
        http = _challenging(f'Bearer realm="{realm}",service="ghcr.io"', seen)

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, CREDENTIAL, http=http) is None

        assert [call.split(" ", 1)[0] for call in seen] == ["HEAD"], "the credential must not leave the registry"

    def test_a_registry_declared_with_a_port_is_matched_with_that_port(self) -> None:
        seen: list[str] = []
        http = _challenging('Bearer realm="https://reg.example:5443/token",service="reg.example"', seen)

        registry.tag_digest("reg.example:5443/acme", "web", VERSION, CREDENTIAL, http=http)

        assert seen[1] == "GET https://reg.example:5443/token"

    def test_the_default_port_of_the_realm_matches_a_declared_443(self) -> None:
        seen: list[str] = []
        http = _challenging('Bearer realm="https://reg.example/token",service="reg.example"', seen)

        registry.tag_digest("reg.example:443/acme", "web", VERSION, CREDENTIAL, http=http)

        assert seen[1] == "GET https://reg.example/token"

    @pytest.mark.parametrize(
        "challenge",
        [
            'Basic realm="https://ghcr.io/token"',
            'Basic realm="x", Bearer realm="https://ghcr.io/token",service="ghcr.io"',
        ],
        ids=["basic only", "basic listed first"],
    )
    def test_a_basic_challenge_is_refused_not_answered(self, challenge: str) -> None:
        seen: list[str] = []

        assert (
            registry.tag_digest("ghcr.io/acme", "web", VERSION, CREDENTIAL, http=_challenging(challenge, seen)) is None
        )

        assert [call.split(" ", 1)[0] for call in seen] == ["HEAD"]

    @pytest.mark.parametrize("status", [401, 403, 500])
    def test_a_token_endpoint_that_refuses_is_refused_even_with_a_token_in_its_body(self, status: int) -> None:
        seen: list[str] = []
        challenge = 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'

        http = _challenging(challenge, seen, token_status=status)

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, CREDENTIAL, http=http) is None
        assert [call.split(" ", 1)[0] for call in seen] == ["HEAD", "GET"], "no manifest read may follow a refusal"

    @pytest.mark.parametrize("status", [206, 301, 302, 307])
    def test_a_manifest_answer_that_is_not_200_is_unread_even_with_a_digest_header(self, status: int) -> None:
        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(status, headers={"docker-content-digest": DIGEST})

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, http=http) is None

    @pytest.mark.parametrize(
        "digest", ["sha256:", "sha256:zzz", "sha256:" + "a" * 63, "sha256:" + "A" * 64, DIGEST + "0"]
    )
    def test_a_digest_is_sixty_four_lowercase_hex_digits_not_a_prefix(self, digest: str) -> None:
        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, headers={"docker-content-digest": digest})

        assert registry.tag_digest("ghcr.io/acme", "web", VERSION, http=http) is None

    def test_the_hub_digest_is_held_to_the_same_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reply = MagicMock(status_code=200, **{"json.return_value": {"digest": "sha256:zzz"}})
        monkeypatch.setattr(registry.httpx, "get", MagicMock(return_value=reply))

        assert registry.tag_digest("docker.io/ns", "kubelab-web", VERSION) is None


ENV_VAR = "GHCR_PULL_TOKEN"  # what CATALOG_KEY flattens to


@pytest.fixture
def sops(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The secrets catalog, standing in for SOPS; the environment variable the key names starts unset."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    manager = MagicMock()
    manager.get_secret_by_path.return_value = None
    monkeypatch.setattr("toolkit.features.configuration.ConfigurationManager", lambda env: manager)
    return manager


class TestTheCatalogSecret:
    def test_it_reads_the_key_through_the_configuration_manager(self, sops: MagicMock) -> None:
        sops.get_secret_by_path.return_value = PULL_TOKEN

        assert registry.catalog_secret(CATALOG_KEY) == PULL_TOKEN
        sops.get_secret_by_path.assert_called_once_with(CATALOG_KEY)

    @pytest.mark.parametrize(
        ("key", "variable"),
        [
            ("ghcr.pull_token", "GHCR_PULL_TOKEN"),
            ("gitea.registry_pull_token", "GITEA_REGISTRY_PULL_TOKEN"),
            ("ghcr.pull-token", "GHCR_PULL_TOKEN"),
        ],
    )
    def test_the_environment_variable_is_the_flattened_key(self, key: str, variable: str) -> None:
        assert registry.catalog_secret_variable(key) == variable

    def test_the_environment_variable_is_read_before_sops(
        self, monkeypatch: pytest.MonkeyPatch, sops: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, PULL_TOKEN)

        assert registry.catalog_secret(CATALOG_KEY) == PULL_TOKEN
        sops.get_secret_by_path.assert_not_called()

    @pytest.mark.parametrize("value", ["", "  \n"], ids=["empty", "blank"])
    def test_an_empty_variable_is_unset_and_falls_back_to_sops(
        self, monkeypatch: pytest.MonkeyPatch, sops: MagicMock, value: str
    ) -> None:
        """An Actions secret nobody created reaches the step as an empty string, not as an absent variable."""
        sops.get_secret_by_path.return_value = PULL_TOKEN
        monkeypatch.setenv(ENV_VAR, value)

        assert registry.catalog_secret(CATALOG_KEY) == PULL_TOKEN

    def test_neither_source_is_none(self, sops: MagicMock) -> None:
        assert registry.catalog_secret(CATALOG_KEY) is None

    def test_the_token_never_reaches_a_log_line(self, monkeypatch: pytest.MonkeyPatch, sops: MagicMock) -> None:
        logged = MagicMock()
        monkeypatch.setattr(registry, "logger", logged)
        monkeypatch.setenv(ENV_VAR, PULL_TOKEN)

        registry.catalog_secret(CATALOG_KEY)

        assert logged.info.called, "the environment path must say which source it used"
        assert ENV_VAR in str(logged.mock_calls)
        assert PULL_TOKEN not in str(logged.mock_calls)

    def test_the_sops_path_does_not_claim_the_environment(
        self, sops: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logged = MagicMock()
        monkeypatch.setattr(registry, "logger", logged)
        monkeypatch.setenv(ENV_VAR, "")

        registry.catalog_secret(CATALOG_KEY)

        assert ENV_VAR not in str(logged.mock_calls)

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
    path.write_text(_PRODUCTS.format(key=CATALOG_KEY), encoding="utf-8", newline="\n")
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
            login=(BOT, PULL_TOKEN),
        )
        secret = _secret(PULL_TOKEN)

        assert _prove(private_registry, http, secret) == DIGEST

        secret.assert_called_once_with(CATALOG_KEY)

    @pytest.mark.parametrize("length", [7, 10])
    def test_a_sha_tag_of_either_length_is_proven(self, private_registry: Path, length: int) -> None:
        """#2627 AC1: a check fixed at 7 hex digits fails the 10-digit product."""
        digests = {VERSION: DIGEST, f"sha-{SHA[:length]}": DIGEST}
        http = _Oci("ghcr.io", "https://ghcr.io/token", digests, login=(BOT, PULL_TOKEN))

        assert _prove(private_registry, http, _secret(PULL_TOKEN)) == DIGEST

        assert http.manifest_reads()[-1][1].endswith(f"/manifests/sha-{SHA[:length]}")

    def test_a_tag_naming_another_build_is_refused(self, private_registry: Path) -> None:
        digests = {VERSION: DIGEST, f"sha-{SHA[:7]}": OTHER}
        http = _Oci("ghcr.io", "https://ghcr.io/token", digests, login=(BOT, PULL_TOKEN))

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

    def test_the_variable_the_key_names_is_the_credential_where_there_is_no_age_key(
        self, private_registry: Path, monkeypatch: pytest.MonkeyPatch, sops: MagicMock
    ) -> None:
        """#3286: a hosted runner has the pull token as an Actions secret in the environment, and no SOPS."""
        monkeypatch.setenv(ENV_VAR, PULL_TOKEN)
        http = _Oci(
            "ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST, f"sha-{SHA[:7]}": DIGEST}, login=(BOT, PULL_TOKEN)
        )

        assert _prove(private_registry, http, None) == DIGEST

        sops.get_secret_by_path.assert_not_called()

    def test_with_neither_source_the_refusal_names_the_variable_to_set(
        self, private_registry: Path, sops: MagicMock
    ) -> None:
        http = MagicMock()

        with pytest.raises(ContractError) as refused:
            _prove(private_registry, http, None)

        assert ENV_VAR in refused.value.fix and CATALOG_KEY in refused.value.error
        http.assert_not_called()

    def test_a_token_from_the_environment_is_in_no_refusal_and_no_log_line(
        self, private_registry: Path, monkeypatch: pytest.MonkeyPatch, sops: MagicMock, warnings: MagicMock
    ) -> None:
        monkeypatch.setenv(ENV_VAR, PULL_TOKEN)
        http = _Oci("ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST}, login=(BOT, STALE_TOKEN))

        with pytest.raises(ContractError) as refused:
            _prove(private_registry, http, None)

        e = refused.value
        assert PULL_TOKEN not in f"{e.error}{e.why}{e.fix}{warnings.mock_calls}"

    def test_a_refused_login_names_the_registry_and_the_login_not_a_missing_tag(self, private_registry: Path) -> None:
        http = _Oci("ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST}, login=(BOT, STALE_TOKEN))

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
            newline="\n",
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
    products.write_text(_GITEA_PRODUCTS, encoding="utf-8", newline="\n")
    monkeypatch.setenv("GITEA_URL", "https://gitea.invalid")
    monkeypatch.setenv("GITEA_REPO_READER_TOKEN", "not-a-real-token")
    monkeypatch.setattr("toolkit.features.forge_adapter.GiteaClient", _GiteaReads)
    _GiteaReads.instances.clear()
    realm = "https://gitea.kubelab.live/v2/token"
    http = _Oci("gitea.kubelab.live", realm, {VERSION: DIGEST, f"sha-{SHA[:10]}": DIGEST}, login=(READER, PULL_TOKEN))
    secret = _secret(PULL_TOKEN)
    out = tmp_path / "out" / "beta.yaml"

    release = product_release.fetch_release_contract("beta", VERSION, out, products, http=http, secret=secret)

    assert (release.repository, release.sha, release.digest) == ("personal/beta", SHA, DIGEST)
    assert out.read_text(encoding="utf-8") == _GITEA_CONTRACT
    secret.assert_called_once_with("gitea.registry_pull_token")
    (client,) = _GiteaReads.instances
    assert [call[0] for call in client.calls] == ["get_tag", "get_raw_file"]
    assert client.calls[1][-1] == SHA, "the contract is read at the release commit, not a branch"


class _Rotating(_Oci):
    """An OCI registry whose bearers are numbered and last ``lifetime`` manifest reads (``None``: for good)."""

    def __init__(self, *args: Any, lifetime: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.lifetime, self.issued, self.uses = lifetime, 0, 0

    def _issue(self) -> str:
        self.issued, self.uses = self.issued + 1, 0
        return f"bearer-{self.issued}"

    def _accepts(self, authorization: str | None) -> bool:
        if authorization != f"Bearer bearer-{self.issued}" or self.lifetime is not None and self.uses >= self.lifetime:
            return False
        self.uses += 1
        return True


def _anonymous(reads: list[tuple[str, str, dict[str, Any]]]) -> list[tuple[str, str, dict[str, Any]]]:
    return [read for read in reads if "Authorization" not in read[2].get("headers", {})]


class TestOneBearerPerProof:
    """A bearer is scoped to one repository and valid for all its tags, so a proof trades for it once (#3287)."""

    def test_a_missing_sha_tag_costs_one_token_exchange_not_one_per_length(self, private_registry: Path) -> None:
        http = _Oci("ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST}, login=(BOT, PULL_TOKEN))

        with pytest.raises(ContractError):
            _prove(private_registry, http, _secret(PULL_TOKEN))

        lengths = len(registry.SHA_TAG_HEX_LENGTHS)
        assert len(http.token_exchanges()) == 1
        assert len(_anonymous(http.manifest_reads())) == 1, "only the first read may go out unauthenticated"
        assert len(http.manifest_reads()) == 2 + lengths, "the release tag, once more with the bearer, then each length"

    def test_a_bearer_that_expires_mid_proof_is_refreshed_once_and_the_proof_goes_on(
        self, private_registry: Path
    ) -> None:
        digests = {VERSION: DIGEST, f"sha-{SHA[:10]}": DIGEST}
        http = _Rotating("ghcr.io", "https://ghcr.io/token", digests, login=(BOT, PULL_TOKEN), lifetime=3)

        assert _prove(private_registry, http, _secret(PULL_TOKEN)) == DIGEST

        assert len(http.token_exchanges()) == 2

    def test_a_bearer_the_registry_keeps_refusing_is_refreshed_once_then_refused(self, warnings: MagicMock) -> None:
        path, http = "ghcr.io/acme", _Rotating("ghcr.io", "https://ghcr.io/token", {VERSION: DIGEST}, lifetime=1)
        bearers = registry.BearerCache()
        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http, bearers=bearers) == DIGEST
        http.lifetime = 0  # the registry now refuses every bearer, the fresh one included

        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http, bearers=bearers) is None

        assert len(http.token_exchanges()) == 2, "one exchange to get in, one refresh, no loop"
        assert "401" in warnings.call_args.args[0]
        reads = len(http.manifest_reads())
        registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http, bearers=bearers)
        assert len(_anonymous(http.manifest_reads()[reads:])) == 1, "a refused bearer is not kept for the next read"

    def test_a_shared_cache_serves_two_reads_of_one_repository_with_one_exchange(self) -> None:
        path, http = _oci("ghcr", {VERSION: DIGEST, "other": OTHER})
        bearers = registry.BearerCache()

        assert registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http, bearers=bearers) == DIGEST
        assert registry.tag_digest(path, "web", "other", CREDENTIAL, http=http, bearers=bearers) == OTHER

        assert len(http.token_exchanges()) == 1
        assert BEARER not in repr(bearers)

    def test_a_bearer_is_never_used_for_another_repository(self) -> None:
        path, http = _oci("ghcr", {VERSION: DIGEST})
        bearers = registry.BearerCache()

        registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http, bearers=bearers)
        registry.tag_digest(path, "api", VERSION, CREDENTIAL, http=http, bearers=bearers)

        scopes = [call[2]["params"]["scope"] for call in http.token_exchanges()]
        assert scopes == ["repository:acme/web:pull", "repository:acme/api:pull"]

    def test_without_a_cache_every_read_trades_for_its_own_bearer(self) -> None:
        """Nothing is kept between calls unless the caller hands a cache in: no module-level state."""
        path, http = _oci("ghcr", {VERSION: DIGEST})

        registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http)
        registry.tag_digest(path, "web", VERSION, CREDENTIAL, http=http)

        assert len(http.token_exchanges()) == 2


class TestDockerHubThroughTheInjectedTransport:
    def test_a_docker_hub_proof_makes_no_call_of_its_own_when_http_is_injected(
        self, private_registry: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An injected ``http`` is the only transport: a Hub image must not reach the network behind it."""

        def real_call(*args: Any, **kwargs: Any) -> httpx.Response:
            raise AssertionError("a real httpx call was made")

        monkeypatch.setattr(registry.httpx, "get", real_call)
        monkeypatch.setattr(registry.httpx, "request", real_call)
        seen: list[str] = []

        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            seen.append(f"{method} {url}")
            return httpx.Response(200, json={"digest": DIGEST})

        assert registry.tag_digest("docker.io/ns", "kubelab-web", VERSION, http=http) == DIGEST
        assert seen == [f"GET {registry._HUB}/repositories/ns/kubelab-web/tags/{VERSION}"]

    def test_a_release_proof_of_a_hub_image_uses_the_injected_transport(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "products.yaml"
        path.write_text(
            "products:\n  resume:\n    forge: github\n    repository: acme/resume\n    receiver: generic\n"
            "    image_registry: docker.io/acme\n",
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(registry.httpx, "get", MagicMock(side_effect=AssertionError("a real httpx call")))

        def http(method: str, url: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, json={"digest": DIGEST})

        assert _prove(path, http, _secret(None)) == DIGEST


class TestADelegatedLoginIsRefusedAndSaidSo:
    def test_the_refusal_tells_the_operator_a_delegating_registry_is_not_supported(
        self, private_registry: Path, warnings: MagicMock
    ) -> None:
        seen: list[str] = []
        challenge = 'Bearer realm="https://auth.elsewhere.example/token",service="ghcr.io"'

        with pytest.raises(ContractError) as refused:
            _prove(private_registry, _challenging(challenge, seen), _secret(PULL_TOKEN))

        assert [call.split(" ", 1)[0] for call in seen] == ["HEAD"], "the credential must not leave the registry"
        assert "another host" in refused.value.fix and "explicit decision" in refused.value.fix
        assert "ghcr.io" in refused.value.error
        assert "delegates" in warnings.call_args.args[0] and "not supported" in warnings.call_args.args[0]
