"""What an upgraded Gitea must still do, probed inside the restored scratch server (OPS-038).

The restore drill proves a snapshot brings the forge back on the pinned image.
It says nothing about the behaviour the forge's clients rely on, which is what a
version bump can break without any repository going missing. These probes run
against the scratch server, so they write to a copy that is wiped on exit:

- `gitea doctor check --all` reports nothing wrong with the migrated database;
- the REST v1 contract `dotf forge` uses: create an issue, comment on it (the
  response carries `html_url`), edit it;
- repository merge settings applied with `PATCH /repos/{o}/{r}` are read back,
  because a 200 from that endpoint says "accepted", never "applied" (TOOL-063).

Only names and counts are printed. The token is minted in the scratch server and
never leaves it.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from typing import Any, Optional

from toolkit.core.logging import logger

Run = Callable[..., "tuple[int, str, str]"]

API = "http://localhost:3000/api/v1"
WRITE_SCOPES = "write:repository,write:issue"


def _curl(run: Run, name: str, token: str, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
    """The decoded JSON answer of a 2xx, or None. `-f` turns every other status into a failure."""
    argv = ["docker", "exec", name, "curl", "-sSf", "-X", method, "-H", f"Authorization: token {token}"]
    if body is not None:
        argv += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    rc, out, _ = run([*argv, f"{API}{path}"])
    if rc != 0:
        return None
    try:
        return json.loads(out) if out.strip() else {}
    except json.JSONDecodeError:
        return None


def _mint_write_token(run: Run, name: str, admin_user: str) -> str:
    rc, token, _ = run(
        [
            "docker",
            "exec",
            "-u",
            "git",
            name,
            "gitea",
            "admin",
            "user",
            "generate-access-token",
            "--username",
            admin_user,
            "--token-name",
            f"probe-{secrets.token_hex(4)}",
            "--scopes",
            WRITE_SCOPES,
            "--raw",
        ]  # fmt: skip
    )
    return token.strip() if rc == 0 else ""


#: Doctor checks that fail the same way on the deployed 1.25.5 (measured 2026-10-17 by the baseline run of this
#: drill), so a failure there says nothing about an upgrade. Each needs a reason; none may be added to quiet a new one.
KNOWN_BASELINE_FAILURES = {
    "Garbage collect LFS": "errors on the deployed 1.25.5 against the same restored data",
}


def _check_of(lines: list[str], index: int) -> str:
    """The doctor check a result line belongs to: the nearest `[N] Name` header above it."""
    for line in reversed(lines[: index + 1]):
        match = re.match(r"^\[\d+\]\s+(.*\S)\s*$", line)
        if match:
            return match.group(1)
    return ""


def _doctor(run: Run, name: str) -> bool:
    rc, out, _ = run(["docker", "exec", "-u", "git", name, "gitea", "doctor", "check", "--all"])
    lines = out.splitlines()
    bad = [
        i
        for i, line in enumerate(lines)
        if ("[E]" in line or line.strip() == "ERROR") and _check_of(lines, i) not in KNOWN_BASELINE_FAILURES
    ]
    errors = [lines[i].strip()[:160] for i in bad]
    if rc != 0 or errors:
        logger.error(f"FAIL doctor: `gitea doctor check --all` exit {rc}, {len(errors)} error line(s)")
        # Check names and counts, never row content: doctor reports on the schema, not on the data.
        for check in sorted({_check_of(lines, i) or "?" for i in bad}):
            logger.error(f"     failing doctor check: {check}")
        for i in bad[:3]:
            for line in lines[max(0, i - 4) : i + 1]:
                logger.error(f"     {line.strip()[:160]}")
        return False
    logger.success("probe: gitea doctor check --all is clean")
    return True


def _pick_repo(run: Run, name: str, token: str, repos: list[str]) -> Optional[str]:
    """The first restored repository with issues enabled: the contract needs one to write into."""
    for full in repos:
        info = _curl(run, name, token, "GET", f"/repos/{full}")
        if isinstance(info, dict) and info.get("has_issues"):
            return full
    return None


def _contract(run: Run, name: str, token: str, full: str) -> bool:
    issue = _curl(run, name, token, "POST", f"/repos/{full}/issues", {"title": "upgrade probe"})
    if not isinstance(issue, dict) or "number" not in issue:
        logger.error("FAIL contract: POST issue was refused")
        return False
    num = issue["number"]
    comment = _curl(run, name, token, "POST", f"/repos/{full}/issues/{num}/comments", {"body": "upgrade probe"})
    if not isinstance(comment, dict) or not comment.get("html_url"):
        logger.error("FAIL contract: POST issue comment did not answer 2xx with html_url")
        return False
    if _curl(run, name, token, "PATCH", f"/repos/{full}/issues/{num}", {"body": "edited"}) is None:
        logger.error("FAIL contract: PATCH issue was refused")
        return False
    logger.success("probe: issue create, comment (html_url) and edit answer on the v1 API")
    return True


def _merge_settings(run: Run, name: str, token: str, full: str) -> bool:
    """Apply a merge style the way `ensure_settings` does, then read it back."""
    declared = {"has_pull_requests": True, "allow_squash_merge": True, "default_merge_style": "squash"}
    if _curl(run, name, token, "PATCH", f"/repos/{full}", declared) is None:
        logger.error("FAIL merge settings: PATCH repository was refused")
        return False
    read = _curl(run, name, token, "GET", f"/repos/{full}")
    if not isinstance(read, dict) or read.get("default_merge_style") != "squash":
        logger.error("FAIL merge settings: PATCH answered 2xx but default_merge_style was not applied")
        return False
    logger.success("probe: repository merge settings are applied and read back")
    return True


def run_probes(run: Run, name: str, admin_user: str, repos: list[str]) -> bool:
    """True only when every probe passes. A probe that cannot run is a failure, never a pass."""
    ok = _doctor(run, name)
    token = _mint_write_token(run, name, admin_user)
    if not token:
        logger.error("drill: CANNOT CHECK — a write token could not be minted for the upgrade probes")
        return False
    full = _pick_repo(run, name, token, sorted(repos))
    if full is None:
        logger.error("drill: CANNOT CHECK — no restored repository has issues enabled")
        return False
    return _contract(run, name, token, full) and _merge_settings(run, name, token, full) and ok
