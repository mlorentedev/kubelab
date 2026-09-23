"""TOOL-078 (#1792) -- opening pull requests and issues on the forge from a session.

`gitea git` made pushing possible without a credential reaching a terminal; this is
the other half of the same act. So the properties asserted here are the same ones
`test_gitea_git_credential.py` holds for the push path:

- the credential is the AUTHORING one (admin password over basic auth), never a token;
- it travels in the request's basic-auth header and nowhere else -- not argv, not output;
- the input rules (repository shape, head differs from base, a title) are pure and
  tested without a network, so a malformed call is refused before it leaves the process.

Each negative assertion is paired with the positive that proves it looked at something
(lesson-416): "the password is not in the output" passes vacuously over empty output.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.gitea_authoring import (
    AuthoringError,
    Opened,
    authoring_client,
    issue_payload,
    open_issue,
    open_pull,
    parse_repo,
    pull_payload,
)
from toolkit.features.gitea_client import GiteaBasicAuthClient

PASSWORD = "correct-horse-battery-staple"
ADMIN_TOKEN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
BOT_TOKEN = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def merged(**overrides: Any) -> dict[str, Any]:
    gitea = {
        "domain": "gitea.example.invalid",
        "admin_token": ADMIN_TOKEN,
        "bot_token": BOT_TOKEN,
        "admin_password": PASSWORD,
        **overrides,
    }
    return {
        "apps": {
            "services": {"core": {"gitea": gitea}},
            "auth": {"identities": {"superadmin": "manu", "machine": "hefesto"}},
        }
    }


class _Response:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.content = b"x"
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _Session:
    """Stands in for `requests.Session`, recording exactly what would go on the wire."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append((method, url, kwargs))
        return self.response


def client_with(response: _Response) -> tuple[GiteaBasicAuthClient, _Session]:
    client = GiteaBasicAuthClient("https://gitea.example.invalid", "manu", PASSWORD)
    session = _Session(response)
    client.session = session  # type: ignore[assignment]
    return client, session


# --- input rules --------------------------------------------------------------


def test_a_repository_is_owner_slash_name() -> None:
    assert parse_repo("personal/resume") == ("personal", "resume")


@pytest.mark.parametrize("bad", ["", "resume", "personal/", "/resume", "a/b/c", "personal resume"])
def test_anything_else_is_refused_before_a_request(bad: str) -> None:
    with pytest.raises(AuthoringError):
        parse_repo(bad)


def test_a_pull_request_needs_distinct_head_and_base() -> None:
    """Gitea answers 409/422 for head == base; refusing here names the mistake instead."""
    with pytest.raises(AuthoringError, match="head and base"):
        pull_payload(head="main", base="main", title="t", body="")


@pytest.mark.parametrize(("head", "base"), [("  ", "main"), ("fix/x", "\t"), (" main ", "main")])
def test_blank_or_padded_branch_names_are_refused_or_normalised(head: str, base: str) -> None:
    """Review of TOOL-078 (Major): whitespace-only names passed as truthy and reached Gitea.

    Branch names are stripped like the title, so a blank one is refused and a padded
    one that collapses onto the base is refused as the same branch.
    """
    with pytest.raises(AuthoringError, match="head and base"):
        pull_payload(head=head, base=base, title="t", body="")


def test_padding_around_a_valid_branch_is_removed() -> None:
    assert pull_payload(head=" fix/x ", base=" main", title="t", body="")["head"] == "fix/x"


def test_a_response_without_number_or_url_is_a_clean_error() -> None:
    """Review of TOOL-078 (Minor): a malformed 201 must not surface as a raw KeyError."""
    client, _ = client_with(_Response(201, {"id": 5}))
    with pytest.raises(AuthoringError, match="number"):
        open_issue(client, "personal/resume", title="t", body="")


def test_a_title_is_required() -> None:
    with pytest.raises(AuthoringError, match="title"):
        pull_payload(head="fix/x", base="main", title="   ", body="")
    with pytest.raises(AuthoringError, match="title"):
        issue_payload(title="", body="")


def test_the_pull_payload_carries_exactly_what_gitea_reads() -> None:
    assert pull_payload(head="fix/x", base="main", title=" Fix x ", body="why") == {
        "head": "fix/x",
        "base": "main",
        "title": "Fix x",
        "body": "why",
    }
    assert issue_payload(title="Broken", body="") == {"title": "Broken", "body": ""}


# --- which credential ---------------------------------------------------------


def test_the_client_uses_the_push_credential_not_a_token() -> None:
    """Opening a PR completes the act a push begins, so it belongs to the same identity.

    `admin_token` lacks `write:repository` on purpose, and the bot is the
    reconciliation identity (ADR-065 D1). Asserted on the client's fields, so a later
    edit that swaps in a token fails here rather than as a 403 in prod.
    """
    client = authoring_client(merged())
    assert isinstance(client, GiteaBasicAuthClient)
    assert client.username == "manu"
    assert client._password == PASSWORD
    assert client.base_url == "https://gitea.example.invalid"
    assert client.token == ""


def test_no_password_in_sops_is_a_clear_refusal() -> None:
    with pytest.raises(AuthoringError, match="admin_password"):
        authoring_client(merged(admin_password=None))


# --- what goes on the wire ----------------------------------------------------


def test_opening_a_pull_request_posts_to_the_repository_pulls() -> None:
    client, session = client_with(
        _Response(201, {"number": 7, "html_url": "https://gitea.example.invalid/personal/resume/pulls/7"})
    )
    opened = open_pull(client, "personal/resume", head="fix/x", base="main", title="Fix x", body="why")

    assert opened == Opened(number=7, url="https://gitea.example.invalid/personal/resume/pulls/7")
    [(method, url, kwargs)] = session.calls
    assert method == "POST"
    assert url == "https://gitea.example.invalid/api/v1/repos/personal/resume/pulls"
    assert kwargs["json"] == {"head": "fix/x", "base": "main", "title": "Fix x", "body": "why"}


def test_opening_an_issue_posts_to_the_repository_issues() -> None:
    client, session = client_with(
        _Response(201, {"number": 3, "html_url": "https://gitea.example.invalid/personal/resume/issues/3"})
    )
    opened = open_issue(client, "personal/resume", title="Broken", body="details")

    assert opened.number == 3
    [(method, url, kwargs)] = session.calls
    assert (method, url) == ("POST", "https://gitea.example.invalid/api/v1/repos/personal/resume/issues")
    assert kwargs["json"] == {"title": "Broken", "body": "details"}


def test_the_credential_travels_as_basic_auth_and_nowhere_else() -> None:
    """In the `auth` tuple `requests` turns into a header -- not a token header, not the URL."""
    client, session = client_with(_Response(201, {"number": 1, "html_url": "u"}))
    open_issue(client, "personal/resume", title="t", body="")

    [(_method, url, kwargs)] = session.calls
    assert kwargs["auth"] == ("manu", PASSWORD)
    assert "Authorization" not in kwargs["headers"]
    assert PASSWORD not in url
    assert PASSWORD not in str(kwargs["json"])


def test_a_forge_refusal_surfaces_gitea_s_own_reason() -> None:
    """A 422 for an existing PR on the same head must say so, not read as success."""
    client, _ = client_with(_Response(409, {"message": "pull request already exists for these targets"}))
    with pytest.raises(Exception, match="already exists"):
        open_pull(client, "personal/resume", head="fix/x", base="main", title="t", body="")


# --- the command --------------------------------------------------------------


def test_the_command_prints_the_url_and_never_the_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from typer.testing import CliRunner

    import toolkit.cli.services as cli

    body = tmp_path / "body.md"
    body.write_text("## Summary\nwhy\n")
    seen: dict[str, Any] = {}

    def fake_open_pull(client: Any, repo: str, **kw: Any) -> Opened:
        seen.update(repo=repo, client=client, **kw)
        return Opened(number=9, url="https://gitea.example.invalid/personal/resume/pulls/9")

    monkeypatch.setattr(cli, "_gitea_merged_config", lambda env: merged())
    monkeypatch.setattr("toolkit.features.gitea_authoring.open_pull", fake_open_pull)

    result = CliRunner().invoke(
        cli.app,
        [
            "gitea",
            "pr",
            "create",
            "--repo",
            "personal/resume",
            "--head",
            "fix/x",
            "--base",
            "main",
            "--title",
            "Fix x",
            "--body-file",
            str(body),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "pulls/9" in result.output  # the floor: output exists and carries the URL
    assert PASSWORD not in result.output
    assert seen["body"] == "## Summary\nwhy\n"
    assert seen["repo"] == "personal/resume"


def test_the_issue_command_prints_the_url_and_never_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of TOOL-078 (Minor): `issue create` gets its own end-to-end CLI test."""
    from typer.testing import CliRunner

    import toolkit.cli.services as cli

    def fake_open_issue(client: Any, repo: str, **kw: Any) -> Opened:
        return Opened(number=4, url="https://gitea.example.invalid/personal/resume/issues/4")

    monkeypatch.setattr(cli, "_gitea_merged_config", lambda env: merged())
    monkeypatch.setattr("toolkit.features.gitea_authoring.open_issue", fake_open_issue)

    result = CliRunner().invoke(cli.app, ["gitea", "issue", "create", "--repo", "personal/resume", "--title", "Broken"])

    assert result.exit_code == 0, result.output
    assert "issues/4" in result.output
    assert PASSWORD not in result.output


def test_an_unreachable_forge_is_a_clean_exit_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of TOOL-078 (Minor): a network error exits 1 with a message, like a refusal."""
    import requests
    from typer.testing import CliRunner

    import toolkit.cli.services as cli

    def unreachable(client: Any, repo: str, **kw: Any) -> Opened:
        raise requests.ConnectionError("forge unreachable")

    monkeypatch.setattr(cli, "_gitea_merged_config", lambda env: merged())
    monkeypatch.setattr("toolkit.features.gitea_authoring.open_issue", unreachable)

    result = CliRunner().invoke(cli.app, ["gitea", "issue", "create", "--repo", "personal/resume", "--title", "t"])

    assert result.exit_code == 1
    assert not isinstance(result.exception, requests.ConnectionError)
