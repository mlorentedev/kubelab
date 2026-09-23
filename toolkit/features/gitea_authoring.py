"""Open pull requests and issues on the Gitea forge from a session (TOOL-078, #1792).

WHY THIS EXISTS. TOOL-035 moved `personal/resume` onto the forge and `gitea git`
made pushing to it possible without a credential reaching a terminal, but the review
loop stayed behind: nothing could open a PR or an issue, so every pushed branch
waited for a human in the web UI. Measured 2026-09-22: five pushed branches with
commits not on `main`, one of them carrying the migration's own ADR.

WHICH CREDENTIAL. The push credential, resolved by the same function
(`resolve_git_credential`), so the choice lives in one place. Opening a PR is the
second half of the act a push begins; splitting it across two identities would make
the forge record a PR authored by someone other than the pusher.

THE RULES ARE PURE. Repository shape, head differs from base, a non-empty title:
checked here, before a request exists, so a malformed call is refused with a reason
that names the mistake instead of a 422 that names Gitea's validator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from toolkit.features.gitea_client import GiteaBasicAuthClient
from toolkit.features.gitea_git import GiteaGitError, resolve_git_credential

#: Gitea's own name rule for owners and repositories: alphanumerics, dash,
#: underscore and dot. Anything else cannot name a repository, so it is refused
#: before it can become a URL path segment.
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class AuthoringError(Exception):
    """Input that cannot become a valid PR or issue, or a credential that is missing."""


@dataclass(frozen=True)
class Opened:
    """What the caller gets back: the number and the URL, and nothing that could carry a secret."""

    number: int
    url: str


def parse_repo(full_name: str) -> tuple[str, str]:
    """`owner/name` -> `(owner, name)`. Exactly two non-empty, valid segments."""
    parts = full_name.split("/")
    if len(parts) != 2 or not all(_SEGMENT.match(p) for p in parts):
        raise AuthoringError(f"repository must be owner/name, got {full_name!r}")
    return parts[0], parts[1]


def _title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise AuthoringError("a title is required")
    return cleaned


def pull_payload(head: str, base: str, title: str, body: str) -> dict[str, str]:
    """The body of `POST /repos/{o}/{r}/pulls`. Refuses head == base, which Gitea would only reject later."""
    if not head or not base or head == base:
        raise AuthoringError(f"head and base must be two different branches, got head={head!r} base={base!r}")
    return {"head": head, "base": base, "title": _title(title), "body": body}


def issue_payload(title: str, body: str) -> dict[str, str]:
    """The body of `POST /repos/{o}/{r}/issues`."""
    return {"title": _title(title), "body": body}


def authoring_client(merged: Mapping[str, Any]) -> GiteaBasicAuthClient:
    """A basic-auth client holding the push credential, for the forge named in the configuration."""
    try:
        username, password = resolve_git_credential(merged)
    except GiteaGitError as exc:
        raise AuthoringError(str(exc)) from exc
    domain = merged["apps"]["services"]["core"]["gitea"]["domain"]
    return GiteaBasicAuthClient(f"https://{domain}", username, password)


def _opened(record: Mapping[str, Any]) -> Opened:
    return Opened(number=int(record["number"]), url=str(record["html_url"]))


def open_pull(client: GiteaBasicAuthClient, repo: str, *, head: str, base: str, title: str, body: str) -> Opened:
    """Open a pull request on `repo` (`owner/name`)."""
    owner, name = parse_repo(repo)
    return _opened(client.create_pull(owner, name, pull_payload(head, base, title, body)))


def open_issue(client: GiteaBasicAuthClient, repo: str, *, title: str, body: str) -> Opened:
    """Open an issue on `repo` (`owner/name`)."""
    owner, name = parse_repo(repo)
    return _opened(client.create_issue(owner, name, issue_payload(title, body)))
