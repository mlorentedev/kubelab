"""Restore the newest Gitea capture from R2 and prove it brings the forge back (BACKUP-040).

`restic check` proves a repository is consistent, not that what it holds brings
Gitea back. This restores the Beelink's newest snapshot into a private temp
directory and passes only if:

- `git fsck --full` passes on every restored bare repository;
- the image live runs starts on the restored data with no network, and its API
  answers with a token minted inside the scratch container;
- every repository live lists exists on disk and in the restored database, none
  that has branches live came back with none, and every restored branch head is
  a commit live knows.

"Complete", never "equal": the snapshot can be hours older than live, so a push
made since is expected. A commit live does not know is the failure, because it
means the restore holds history that never existed.

The restored data is the whole forge: private repositories, `gitea.db` with
password hashes, `app.ini` with secrets and the SSH host keys. It stays in a
`0700` directory, only names and counts are printed, and the container (with
its volumes, lesson-498) and the directory are removed on every exit path. The
container runs as root and writes into the bind mount, so the directory is
wiped from inside a container first; a leftover fails the drill.

Live is read with the admin token, whose grant is `read:repository` and never a
write scope.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.postgres_drill import remove_scratch_container

Run = Callable[..., "tuple[int, str, str]"]

#: Where the capture stages Gitea's data directory, relative to the staging dir.
#: The snapshot stores absolute paths, so this must match the capture.
SERVICE = "gitea"

#: Seconds the restored server gets to answer `/api/healthz`. It runs its
#: migrations check and opens the indexers on start.
READY_TIMEOUT = 180


def _default_run(argv: list[str], *, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def repos_on_disk(root: Path) -> set[str]:
    """`owner/name` for every bare repository under `git/repositories`.

    Lower case, because that is how Gitea names them on disk whatever the
    repository is called; `compare` matches on the lowered name.
    """
    base = root / "git" / "repositories"
    if not base.is_dir():
        return set()
    return {
        f"{owner.name}/{repo.name[: -len('.git')]}"
        for owner in base.iterdir()
        if owner.is_dir()
        for repo in owner.iterdir()
        if repo.is_dir() and repo.name.endswith(".git")
    }


def compare(
    live: dict[str, int],
    restored: dict[str, dict[str, str]],
    on_disk: set[str],
    commit_known: Callable[[str, str], Optional[bool]],
) -> tuple[bool, list[str]]:
    """Complete, not equal. `live` is branch counts; `restored` maps each branch to its head."""
    ok = True
    lines = []
    for repo in sorted(live):
        if repo.lower() not in on_disk:
            lines.append(f"FAIL {repo}: missing from the restored repositories")
            ok = False
            continue
        if repo not in restored:
            lines.append(f"FAIL {repo}: on disk but missing from the restored database")
            ok = False
            continue
        heads = restored[repo]
        if live[repo] > 0 and not heads:
            lines.append(f"FAIL {repo}: restored with no branches, live has {live[repo]}")
            ok = False
            continue
        unknown = []
        for branch, sha in sorted(heads.items()):
            known = commit_known(repo, sha)
            if known is None:
                lines.append(f"FAIL {repo}: CANNOT CHECK branch {branch} against live")
                ok = False
            elif not known:
                unknown.append(branch)
        if unknown:
            lines.append(f"FAIL {repo}: head of {', '.join(unknown)} is a commit live does not know")
            ok = False
        else:
            lines.append(f"     {repo}: {len(heads)} branch(es) restored, live {live[repo]}")
    for repo in sorted(set(restored) - set(live)):
        lines.append(f"     {repo}: restored, gone from live since the snapshot")
    return ok, lines


_UNREAD = object()


def _paginate(fetch: Callable[[str], Any], path: str, key: Optional[str] = None) -> Optional[list[Any]]:
    """Walk a Gitea list endpoint until a short page. None if any page could not be read.

    A JSON `null` page is an empty collection: Gitea answers `/branches` of a
    repository with no commits that way. Only `_UNREAD` means the read failed.
    """
    items: list[Any] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        body = fetch(f"{path}{sep}limit=50&page={page}")
        if body is _UNREAD:
            return None
        batch = (body[key] if key else body) if body is not None else []
        items.extend(batch)
        if len(batch) < 50:
            return items
        page += 1


class _Scratch:
    """The restored server, reached through `docker exec` because it has no network."""

    def __init__(self, run: Run, name: str) -> None:
        self.run = run
        self.name = name
        self.token = ""

    def get(self, path: str) -> Any:
        """The decoded body, or `_UNREAD` when the request or the decode failed."""
        rc, out, _ = self.run(
            [
                "docker",
                "exec",
                self.name,
                "wget",
                "-qO-",
                "--header",
                f"Authorization: token {self.token}",
                f"http://localhost:3000/api/v1{path}",
            ]
        )
        if rc != 0:
            return _UNREAD
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return _UNREAD

    def heads(self) -> Optional[dict[str, dict[str, str]]]:
        repos = _paginate(self.get, "/repos/search", key="data")
        if repos is None:
            return None
        result = {}
        for repo in repos:
            full = f"{repo['owner']['username']}/{repo['name']}"
            branches = _paginate(self.get, f"/repos/{full}/branches")
            if branches is None:
                return None
            result[full] = {b["name"]: b["commit"]["id"] for b in branches}
        return result


def _wipe(run: Run, image: str, workdir: Path) -> bool:
    """Remove the restored data, including what the root-run container wrote into it."""
    if not workdir.exists():
        return True
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{workdir}:/w",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "rm -rf /w/* /w/.[!.]*",
        ]
    )
    shutil.rmtree(workdir, ignore_errors=True)
    return not workdir.exists()


def run_drill(
    *,
    repo: str,
    restic_env: dict[str, str],
    staging_dir: str,
    image: str,
    admin_user: str,
    live: Any,
    run: Run = _default_run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Restore the newest Gitea capture in `repo` and check it against `live`. True only on a whole restore.

    `live` is a Gitea client holding the admin token: `list_repos`, `list_branches`
    and `commit_exists` are the only methods called.
    """
    rc, out, err = run(["restic", "-r", repo, "snapshots", "--json", "--latest", "1"], env=restic_env)
    snapshots = json.loads(out or "[]") if rc == 0 else []
    if not snapshots:
        logger.error(f"drill: no snapshot readable in {repo}: {err.strip()[:160]}")
        return False
    snapshot = snapshots[-1]
    logger.info(f"drill: snapshot {snapshot['short_id']} taken {snapshot['time']}")

    try:
        live_repos = sorted(live.list_repos())
        live_counts = {name: len(live.list_branches(*name.split("/", 1))) for name in live_repos}
    except Exception as exc:  # noqa: BLE001 - any failure to read live is CANNOT CHECK
        logger.error(f"drill: CANNOT CHECK — live Gitea could not be read: {str(exc)[:160]}")
        return False
    if not live_counts:
        # Every check below is "for each repository live has" (lesson-416).
        logger.error("drill: CANNOT CHECK — live Gitea listed no repositories")
        return False

    workdir = Path(tempfile.mkdtemp(prefix="giteadrill-"))
    name = f"giteadrill-{secrets.token_hex(4)}"
    ok = False
    try:
        ok = _restore_and_check(
            run=run,
            repo=repo,
            restic_env=restic_env,
            snapshot=snapshot["short_id"],
            source=f"{staging_dir}/{SERVICE}",
            workdir=workdir,
            name=name,
            image=image,
            admin_user=admin_user,
            live=live,
            live_counts=live_counts,
            sleep=sleep,
            clock=clock,
        )
    finally:
        # Unconditional: `docker run -d` can create the container and still fail.
        try:
            removed = remove_scratch_container(run, name)
        finally:
            wiped = _wipe(run, image, workdir)
            if not wiped:
                logger.error(f"drill: could not remove {workdir}; it holds a full copy of the forge, delete it now")
    # A restore that passed but left the forge's copy behind is not a pass.
    return ok and removed and wiped


def _restore_and_check(
    *,
    run: Run,
    repo: str,
    restic_env: dict[str, str],
    snapshot: str,
    source: str,
    workdir: Path,
    name: str,
    image: str,
    admin_user: str,
    live: Any,
    live_counts: dict[str, int],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> bool:
    started = clock()
    rc, _, err = run(
        ["restic", "-r", repo, "restore", snapshot, "--include", source, "--target", str(workdir)],
        env=restic_env,
    )
    data = workdir / source.lstrip("/")
    if rc != 0 or not data.is_dir():
        logger.error(f"drill: restic could not restore {source}: {err.strip()[:160]}")
        return False
    restored_at = clock()
    on_disk = repos_on_disk(data)
    logger.success(f"drill: restored {len(on_disk)} repositories in {restored_at - started:.0f}s")

    broken = [
        full
        for full in sorted(on_disk)
        if run(["git", "--git-dir", str(data / "git/repositories" / f"{full}.git"), "fsck", "--full", "--no-progress"])[
            0
        ]
        != 0
    ]
    for full in broken:
        logger.error(f"FAIL {full}: git fsck --full failed")
    if broken:
        return False
    logger.success(f"drill: git fsck --full passed on all {len(on_disk)} repositories")

    # No network: the restored app.ini points at live services, mailers and
    # webhooks, and none of them may hear from a copy.
    rc, _, err = run(["docker", "run", "-d", "--name", name, "--network", "none", "-v", f"{data}:/data", image])
    if rc != 0:
        logger.error(f"drill: the restored server did not start: {err.strip()[:160]}")
        return False
    deadline = clock() + READY_TIMEOUT
    while run(["docker", "exec", name, "wget", "-qO", "/dev/null", "http://localhost:3000/api/healthz"])[0] != 0:
        if clock() > deadline:
            logger.error(f"drill: the restored server did not answer within {READY_TIMEOUT}s")
            return False
        sleep(2)
    logger.success(f"drill: the restored server answers, {clock() - started:.0f}s after the restore began")

    scratch = _Scratch(run, name)
    rc, token, err = run(
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
            f"drill-{secrets.token_hex(4)}",
            "--scopes",
            "read:repository",
            "--raw",
        ]
    )
    scratch.token = token.strip()
    if rc != 0 or not scratch.token:
        # The token is never printed; Gitea's error names the cause without it.
        logger.error(f"drill: could not mint a token in the restored server: {err.strip()[:160]}")
        return False
    restored = scratch.heads()
    if restored is None:
        logger.error("drill: CANNOT CHECK — the restored server's API could not be read")
        return False

    def commit_known(full: str, sha: str) -> Optional[bool]:
        try:
            return bool(live.commit_exists(*full.split("/", 1), sha))
        except Exception:  # noqa: BLE001 - reported per branch as CANNOT CHECK
            return None

    ok, lines = compare(live_counts, restored, on_disk, commit_known)
    for line in lines:
        (logger.error if line.startswith("FAIL") else logger.info)(line)
    if ok:
        logger.success(
            f"drill: snapshot {snapshot} restores Gitea completely "
            f"({len(live_counts)} repositories, {clock() - started:.0f}s end to end)"
        )
    return ok


def resolve_inputs(env: str = "prod", project_root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Every input the drill takes, resolved from the SSOT and SOPS on this machine. JSON-safe.

    None, after naming what is missing. Holds the restic credentials and the admin
    token: it travels to another host only on an ssh session's stdin (BACKUP-071).
    """
    from toolkit.features.backup_destination import DestinationError, repo_url, repository_name, restic_context
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.postgres_drill import staging_dir

    cm = ConfigurationManager(env, project_root)
    root = Path(project_root or cm.project_root)
    merged = cm.get_merged_config()
    try:
        dest, restic_env = restic_context(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return None

    sources = (merged.get("backup", {}) or {}).get("sources", {}) or {}
    nodes = [node for node, entries in sorted(sources.items()) if SERVICE in (entries or {})]
    if len(nodes) != 1:
        logger.error(f"drill: expected exactly one node with a '{SERVICE}' backup source, found {nodes}")
        return None

    gitea = merged["apps"]["services"]["core"]["gitea"]
    token = gitea.get("admin_token")
    if not token:
        logger.error(f"drill: CANNOT CHECK — apps.services.core.gitea.admin_token is missing from {env} SOPS")
        return None
    return {
        "repo": repo_url(dest, repository_name(cm, nodes[0])),
        "restic_env": dict(restic_env),
        "staging_dir": staging_dir(root),
        "image": str(gitea["image"]),
        "admin_user": str(merged["apps"]["auth"]["identities"]["superadmin"]),
        "gitea_url": f"https://{gitea['domain']}",
        "token": str(token),
    }


def run_from_inputs(inputs: dict[str, Any]) -> bool:
    """Run the drill on resolved inputs. Reads no config, so it runs on a host with no SOPS key."""
    from toolkit.features.gitea_client import GiteaClient

    return run_drill(
        repo=str(inputs["repo"]),
        restic_env={str(k): str(v) for k, v in inputs["restic_env"].items()},
        staging_dir=str(inputs["staging_dir"]),
        image=str(inputs["image"]),
        admin_user=str(inputs["admin_user"]),
        live=GiteaClient(str(inputs["gitea_url"]), str(inputs["token"])),
    )


def drill_gitea(env: str = "prod", project_root: Optional[Path] = None) -> bool:
    """Resolve every input from the SSOT and run the drill on this machine."""
    logger.section(f"gitea restore drill — newest capture in R2 into a scratch server ({env})")
    inputs = resolve_inputs(env, project_root)
    return inputs is not None and run_from_inputs(inputs)
