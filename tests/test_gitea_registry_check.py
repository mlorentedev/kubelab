"""IDP-053 S2c (AC4) -- `toolkit services gitea registry-check` proves a pull token by CONSEQUENCE.

A grant read from `common.yaml` says what the token should hold; whether it reaches a given
product's package depends on the owner's visibility and the reviewer account's team units, which
no diff shows. So the command pulls a manifest with the token and reports the status the registry
answers, and the negative half pulls a package the token must not reach and passes only on a
denial. The registry is the only fake, and the token is the one thing no output may carry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from toolkit.features import product_registry
from toolkit.features.registry_check import NoVerdict, check_pull, manifest_status

TOKEN = "fake-pull-token-do-not-leak"  # noqa: S105 - a test value
HOST = "gitea.kubelab.live"
TAG = "sha-0123456789ab"
OWN = f"https://{HOST}/v2/personal/beta/manifests/{TAG}"
OTHER = f"https://{HOST}/v2/teledyne/secret/manifests/{TAG}"
REALM = f"https://{HOST}/v2/token"

REGISTRY = f"""\
products:
  api:
    forge: in-tree
  web:
    repository: mlorentedev/web
    forge: github
    receiver: generic
  beta:
    repository: personal/beta
    forge: gitea
    receiver: generic
    image_registry: {HOST}/personal
    private: true
    pull_credential: {{username: reviewer, secret: apps.services.core.gitea.registry_pull_token}}
"""


class Resp:
    def __init__(self, status: int, headers: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body or {}
        self.text = "must never be read for the verdict"

    def json(self) -> dict[str, Any]:
        return self._body


class Session:
    """A registry answering from a table of `(url) -> responses in order`; every call is recorded."""

    def __init__(self, answers: dict[str, list[Resp | Exception]]) -> None:
        self.answers = {url: list(queue) for url, queue in answers.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> Resp:
        self.calls.append((url, kwargs))
        queue = self.answers.get(url)
        if not queue:
            raise AssertionError(f"unexpected GET {url}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def entry(tmp_path: Path) -> product_registry.Product:
    path = tmp_path / "products.yaml"
    path.write_text(REGISTRY, encoding="utf-8", newline="\n")
    return product_registry.load_registry(path).products["beta"]


def _check(entry, session, **kwargs):
    args: dict[str, Any] = {"package": None, "expect_denied": False, "tag": TAG, "token": TOKEN}
    return check_pull(entry, "beta", session=session, **{**args, **kwargs})


def _seen(session: Session) -> str:
    return " ".join(f"{url} {kwargs}" for url, kwargs in session.calls)


class TestThePullByConsequence:
    def test_the_apps_own_package_is_pulled_by_default_and_a_200_passes(self, entry) -> None:
        session = Session({OWN: [Resp(200)]})

        result = _check(entry, session)

        assert result.ok and result.status == 200
        assert [url for url, _ in session.calls] == [OWN]
        assert "personal/beta" in result.message and TAG in result.message

    @pytest.mark.parametrize("status", [401, 403, 404, 500, 502])
    def test_any_other_status_fails_without_the_flag(self, entry, status: int) -> None:
        result = _check(entry, Session({OWN: [Resp(status)]}))

        assert not result.ok and result.status == status
        assert str(status) in result.message

    def test_a_named_package_is_pulled_instead_of_the_apps_own(self, entry) -> None:
        session = Session({OTHER: [Resp(403)]})

        result = _check(entry, session, package="teledyne/secret", expect_denied=True)

        assert result.ok and result.status == 403
        assert [url for url, _ in session.calls] == [OTHER]

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_denial_passes_only_with_the_flag(self, entry, status: int) -> None:
        assert _check(entry, Session({OTHER: [Resp(status)]}), package="teledyne/secret", expect_denied=True).ok
        assert not _check(entry, Session({OTHER: [Resp(status)]}), package="teledyne/secret").ok

    @pytest.mark.parametrize("status", [200, 404, 500, 502])
    def test_with_the_flag_anything_but_401_or_403_fails(self, entry, status: int) -> None:
        """A pull that succeeds proves the token reaches what it must not; a 404 or a 5xx proves nothing."""
        result = _check(entry, Session({OTHER: [Resp(status)]}), package="teledyne/secret", expect_denied=True)

        assert not result.ok and result.status == status

    def test_a_denied_pull_run_without_the_flag_says_what_the_flag_is_for(self, entry) -> None:
        result = _check(entry, Session({OTHER: [Resp(403)]}), package="teledyne/secret")

        assert not result.ok and "--expect-denied" in result.message

    @pytest.mark.parametrize("package", ["", " ", "no-owner", "a/b c", "../x/y", "a//b"])
    def test_an_empty_or_malformed_package_fails_and_nothing_is_requested(self, entry, package: str) -> None:
        session = Session({})

        result = _check(entry, session, package=package, expect_denied=True)

        assert not result.ok and result.status is None
        assert session.calls == []

    @pytest.mark.parametrize("failure", [requests.ConnectionError("refused"), requests.Timeout("slow")])
    @pytest.mark.parametrize("expect_denied", [False, True])
    def test_a_registry_that_cannot_be_reached_never_passes(self, entry, failure, expect_denied: bool) -> None:
        """An unreachable registry is no denial: with the flag it must still fail."""
        result = _check(entry, Session({OWN: [failure], OTHER: [failure]}), expect_denied=expect_denied)

        assert not result.ok and result.status is None


class TestTheRegistryAuthHandshake:
    CHALLENGE = {"WWW-Authenticate": f'Bearer realm="{REALM}",service="container_registry",scope="*"'}

    def test_a_registry_that_challenges_gets_a_bearer_token_from_its_realm(self, entry) -> None:
        session = Session(
            {OWN: [Resp(401, self.CHALLENGE), Resp(200)], REALM: [Resp(200, body={"token": "bearer-value"})]}
        )

        result = _check(entry, session)

        assert result.ok and result.status == 200
        urls = [url for url, _ in session.calls]
        assert urls == [OWN, REALM, OWN]
        realm_call = session.calls[1][1]
        assert realm_call["auth"] == ("reviewer", TOKEN), "the realm is asked with the pull login"
        assert realm_call["params"]["scope"] == "repository:personal/beta:pull"
        assert session.calls[2][1]["headers"]["Authorization"] == "Bearer bearer-value"
        assert all(kwargs["allow_redirects"] is False for _, kwargs in session.calls), (
            "a redirect on any leg could carry the login or the bearer token to another host"
        )

    def test_a_denial_after_the_handshake_is_the_status_reported(self, entry) -> None:
        session = Session(
            {OTHER: [Resp(401, self.CHALLENGE), Resp(403)], REALM: [Resp(200, body={"token": "bearer-value"})]}
        )

        result = _check(entry, session, package="teledyne/secret", expect_denied=True)

        assert result.ok and result.status == 403

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_realm_that_refuses_the_login_is_a_denial(self, entry, status: int) -> None:
        session = Session({OTHER: [Resp(401, self.CHALLENGE)], REALM: [Resp(status)]})

        result = _check(entry, session, package="teledyne/secret", expect_denied=True)

        assert result.ok and result.status == status

    def test_a_realm_answering_500_is_not_a_denial(self, entry) -> None:
        session = Session({OTHER: [Resp(401, self.CHALLENGE)], REALM: [Resp(500)]})

        assert not _check(entry, session, package="teledyne/secret", expect_denied=True).ok

    def test_a_realm_on_another_host_is_never_sent_the_login(self, entry) -> None:
        """The challenge is attacker-influenced input: the pull login goes only to the registry's own host."""
        hostile = {"WWW-Authenticate": 'Bearer realm="https://evil.example/token",service="x"'}
        session = Session({OWN: [Resp(401, hostile)]})

        result = _check(entry, session)

        assert not result.ok
        assert [url for url, _ in session.calls] == [OWN]

    @pytest.mark.parametrize("expect_denied", [False, True])
    def test_a_realm_on_another_host_gives_no_verdict_even_when_a_denial_is_expected(
        self, entry, expect_denied: bool
    ) -> None:
        """The 401 that carried the off-host challenge is not a verdict on the token: it was never tested."""
        hostile = {"WWW-Authenticate": 'Bearer realm="https://evil.example/token",service="x"'}
        session = Session({OTHER: [Resp(401, hostile)]})

        result = _check(entry, session, package="teledyne/secret", expect_denied=expect_denied)

        assert not result.ok, "an unanswered handshake must not read as a denial"
        assert result.status is None
        assert "no verdict" in result.message and "another host" in result.message
        assert "evil.example" not in result.message
        assert [url for url, _ in session.calls] == [OTHER]


class TestTheRealmAuthority:
    """The realm is network input: only the registry's own scheme, host AND port may receive the login."""

    PORTED = "forge.example:5000"
    OWN_URL = f"https://{PORTED}/v2/personal/beta/manifests/{TAG}"

    def _handshake(self, realm: str, host: str = PORTED):
        challenge = {"WWW-Authenticate": f'Bearer realm="{realm}",service="registry"'}
        session = Session(
            {
                f"https://{host}/v2/personal/beta/manifests/{TAG}": [Resp(401, challenge), Resp(200)],
                realm: [Resp(200, body={"token": "bearer-value"})],
            }
        )
        return session, manifest_status(session, host, "personal/beta", TAG, "reviewer", TOKEN)

    def test_a_realm_on_the_same_host_and_port_is_answered(self) -> None:
        session, status = self._handshake(f"https://{self.PORTED}/v2/token")

        assert status == 200
        assert [url for url, _ in session.calls][1] == f"https://{self.PORTED}/v2/token"

    @pytest.mark.parametrize(
        ("host", "realm"),
        [
            ("forge.example", "https://forge.example:443/v2/token"),
            ("forge.example:443", "https://forge.example/v2/token"),
            ("Forge.Example", "https://forge.example/v2/token"),
        ],
    )
    def test_the_default_port_is_the_same_authority_as_none(self, host: str, realm: str) -> None:
        _, status = self._handshake(realm, host=host)

        assert status == 200

    @pytest.mark.parametrize(
        "realm",
        [
            "https://forge.example:6000/v2/token",
            "https://forge.example/v2/token",
            "https://forge.example:5000.evil.example/v2/token",
            "https://forge.example:notaport/v2/token",
        ],
    )
    def test_a_realm_on_another_port_gets_no_verdict_and_no_login(self, realm: str) -> None:
        challenge = {"WWW-Authenticate": f'Bearer realm="{realm}",service="registry"'}
        session = Session({self.OWN_URL: [Resp(401, challenge)]})

        with pytest.raises(NoVerdict):
            manifest_status(session, self.PORTED, "personal/beta", TAG, "reviewer", TOKEN)

        assert [url for url, _ in session.calls] == [self.OWN_URL]

    @pytest.mark.parametrize("expect_denied", [False, True])
    def test_a_realm_that_is_not_https_gets_no_verdict_before_any_login_is_sent(
        self, entry, expect_denied: bool
    ) -> None:
        plain = {"WWW-Authenticate": f'Bearer realm="http://{HOST}/v2/token",service="x"'}
        session = Session({OWN: [Resp(401, plain)]})

        result = _check(entry, session, expect_denied=expect_denied)

        assert not result.ok and result.status is None
        assert "no verdict" in result.message and "HTTPS" in result.message
        assert [url for url, _ in session.calls] == [OWN]


class TestTheLoginIsNotSwappedForTheOperatorsOwn:
    """`requests` lets a `.netrc` entry replace the Authorization header of a request that carries no `auth`."""

    def test_the_bearer_request_carries_the_bearer_token_not_a_netrc_login(
        self, entry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import requests.adapters

        import toolkit.cli.services as cli

        netrc = tmp_path / "netrc"
        netrc.write_text(
            f"machine {HOST} login operator password operators-own-password\n", encoding="utf-8", newline="\n"
        )
        netrc.chmod(0o600)
        monkeypatch.setenv("NETRC", str(netrc))
        challenge = {"WWW-Authenticate": f'Bearer realm="{REALM}",service="registry"'}
        sent: list[tuple[str, str | None]] = []

        class Registry(requests.adapters.BaseAdapter):
            def send(self, request, **kwargs):  # noqa: ANN001, ANN003
                sent.append((request.url or "", request.headers.get("Authorization")))
                response = requests.Response()
                response.url = request.url or ""
                if (request.url or "").startswith(REALM):
                    response.status_code, response._content = 200, b'{"token": "bearer-value"}'
                elif request.headers.get("Authorization") == "Bearer bearer-value":
                    response.status_code, response._content = 200, b"{}"
                else:
                    response.status_code, response._content = 401, b""
                    response.headers.update(challenge)
                response._content_consumed = True
                return response

            def close(self) -> None:
                pass

        session = cli._registry_session()
        session.mount("https://", Registry())

        result = _check(entry, session)

        assert result.ok, (result.message, sent)
        assert sent[-1] == (OWN, "Bearer bearer-value"), "the pull must carry the token it was exchanged for"
        assert all("operator" not in (header or "") for _, header in sent)


class TestTheTokenNeverLeaks:
    @pytest.mark.parametrize("status", [200, 401, 403, 500])
    def test_the_token_is_in_no_message_and_no_url(self, entry, status: int) -> None:
        session = Session({OWN: [Resp(status)]})

        result = _check(entry, session)

        assert TOKEN not in result.message
        assert all(TOKEN not in url for url, _ in session.calls)
        assert all(kwargs.get("auth") == ("reviewer", TOKEN) for _, kwargs in session.calls)

    def test_the_token_is_in_no_message_when_the_registry_cannot_be_reached(self, entry) -> None:
        result = _check(entry, Session({OWN: [requests.ConnectionError(f"refused for {TOKEN}")]}))

        assert TOKEN not in result.message


class TestWhoCanBeChecked:
    def test_an_app_that_is_not_private_is_refused_with_error_why_and_fix(self, tmp_path: Path) -> None:
        path = tmp_path / "products.yaml"
        path.write_text(REGISTRY, encoding="utf-8", newline="\n")
        web = product_registry.load_registry(path).products["web"]
        session = Session({})

        result = check_pull(web, "web", package=None, expect_denied=False, tag=TAG, token=TOKEN, session=session)

        assert not result.ok and result.status is None
        assert all(part in result.message for part in ("ERROR:", "WHY:", "FIX:")), result.message
        assert session.calls == []


class TestTheManifestRequest:
    def test_it_asks_for_a_manifest_with_the_pull_login_and_a_bounded_wait(self) -> None:
        session = Session({OWN: [Resp(200)]})

        assert manifest_status(session, HOST, "personal/beta", TAG, "reviewer", TOKEN) == 200

        ((url, kwargs),) = session.calls
        assert url == OWN
        assert kwargs["auth"] == ("reviewer", TOKEN)
        assert "application/vnd.oci.image.manifest.v1+json" in kwargs["headers"]["Accept"]
        assert kwargs["timeout"] > 0, "a registry that never answers must not hang the check"
        assert kwargs["allow_redirects"] is False, "a redirect could carry the login to another host"


class TestTheCommand:
    @pytest.fixture
    def invoke(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from typer.testing import CliRunner

        import toolkit.cli.services as cli

        path = tmp_path / "products.yaml"
        path.write_text(REGISTRY, encoding="utf-8", newline="\n")
        monkeypatch.setattr(product_registry, "registry_path", lambda: path)
        merged = {"apps": {"services": {"core": {"gitea": {"registry_pull_token": TOKEN}}}}}
        monkeypatch.setattr(cli, "_gitea_merged_config", lambda env: merged)
        monkeypatch.setattr("toolkit.features.promotion.read_pinned_version", lambda env, app: TAG)
        self.session = Session({OWN: [Resp(200)], OTHER: [Resp(403)]})
        monkeypatch.setattr(cli, "_registry_session", lambda: self.session)

        def run(*args: str):
            return CliRunner().invoke(cli.app, ["gitea", "registry-check", *args])

        return run

    def test_a_pull_that_succeeds_exits_0_and_prints_no_token(self, invoke) -> None:
        result = invoke("--app", "beta")

        assert result.exit_code == 0, result.output
        assert "200" in result.output and TOKEN not in result.output

    def test_a_denied_package_exits_0_only_with_the_flag(self, invoke) -> None:
        assert invoke("--app", "beta", "--package", "teledyne/secret", "--expect-denied").exit_code == 0
        assert invoke("--app", "beta", "--package", "teledyne/secret").exit_code == 1

    def test_an_empty_package_exits_non_zero(self, invoke) -> None:
        assert invoke("--app", "beta", "--package", "", "--expect-denied").exit_code == 1

    def test_a_token_not_minted_yet_exits_non_zero_with_error_why_and_fix(
        self, invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import toolkit.cli.services as cli

        monkeypatch.setattr(cli, "_gitea_merged_config", lambda env: {"apps": {"services": {"core": {"gitea": {}}}}})

        result = invoke("--app", "beta")

        assert result.exit_code == 1
        assert all(part in result.output for part in ("ERROR:", "WHY:", "FIX:")), result.output
        assert self.session.calls == []

    def test_the_token_reaches_the_pull_unchanged(self, invoke, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[Any] = []
        real = check_pull

        def spy(*args: Any, **kwargs: Any):
            seen.append(kwargs["token"])
            return real(*args, **kwargs)

        monkeypatch.setattr("toolkit.features.registry_check.check_pull", spy)

        assert invoke("--app", "beta").exit_code == 0
        assert seen == [TOKEN]

    @pytest.mark.parametrize("app", ["web", "api"])
    def test_a_product_without_a_pull_token_is_refused_before_any_pull_and_never_pulls_as_none(
        self, invoke, monkeypatch: pytest.MonkeyPatch, app: str
    ) -> None:
        """No pull credential means a None token; it must not become the literal password "None"."""
        seen: list[Any] = []
        monkeypatch.setattr(
            "toolkit.features.registry_check.check_pull",
            lambda *a, **k: seen.append(k["token"]) or pytest.fail("pulled"),
        )

        result = invoke("--app", app)

        assert result.exit_code == 1
        assert seen == [] and self.session.calls == []
        assert "None" not in result.output.replace("NoneType", "")

    def test_an_app_the_registry_does_not_know_exits_non_zero(self, invoke) -> None:
        result = invoke("--app", "nope")

        assert result.exit_code == 1 and self.session.calls == []
