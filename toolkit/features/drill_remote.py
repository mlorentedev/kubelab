"""Run a restore drill on another host, with every input resolved here (BACKUP-071).

The workstation holds the SOPS keys, so it resolves everything the drill takes,
live reads included, into one JSON payload. The host gets that payload on the
ssh session's stdin and runs `toolkit backup drill-<x> --inputs-stdin`, which
calls the same `run_from_inputs` a local run calls. That path reads no config; the
import-time `dev` load is #2021's, and ace2 has no sops and no key to serve it.

What travels where:

- argv (visible in `ps` on both ends) carries the host, the commit and the
  drill's name, never a secret;
- stdin carries the payload, restic credentials and the Gitea token included.
  It is read once into memory on the host and never written or echoed;
- no VPS credential and no forwarded agent reach the host: Headscale's live
  reads happen here, before the payload is built.

The host runs the commit this tree is at, not master. Its checkout (owned by
`dev_node`) is fetched and detached at that commit on every run, which is why a
dirty tree, or a commit `origin` does not have, refuses to start: the evidence
would vouch for code the host never ran.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from toolkit.core.logging import logger

#: Drills that can run on another host, and the module that resolves and runs each.
DRILLS = {"gitea": "toolkit.features.gitea_drill", "headscale": "toolkit.features.headscale_drill"}

#: The drill checkout, relative to the dev user's home. `dev_node_drill_checkout` provisions it.
CHECKOUT = ".local/share/kubelab-drill"

#: Exit code of the remote script when the checkout could not be brought to the commit.
SETUP_FAILED = 97

#: ssh's own exit code for a connection or authentication failure.
SSH_FAILED = 255

GitRun = Callable[..., "tuple[int, str, str]"]
Stream = Callable[..., int]


def _git(argv: list[str], *, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _stream(argv: list[str], *, stdin: str) -> int:
    """Run with `stdin` as input and the output straight to this terminal, as a local drill prints it."""
    return subprocess.run(argv, input=stdin, text=True, check=False).returncode


def module_for(drill: str) -> Any:
    """The module that resolves and runs `drill`, locally or on a host."""
    import importlib

    return importlib.import_module(DRILLS[drill])


def ssh_target(net: dict[str, Any], host: str) -> str:
    """`user@tailnet-address` of a homelab node. KeyError when the node is not declared."""
    from toolkit.features.k8s_connect import resolve_ssh_user

    node = net["nodes"][host]
    return f"{resolve_ssh_user(net, host)}@{node['tailscale_ip']}"


def remote_script(drill: str, sha: str) -> str:
    """The shell the host runs. Every step before the drill reads /dev/null, so the payload reaches only the drill."""
    if drill not in DRILLS:
        raise ValueError(f"unknown drill {drill!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("a remote drill runs a full commit id, nothing else")
    fail = f'{{ echo "drill: setup failed on $(hostname)" >&2; exit {SETUP_FAILED}; }}'
    return "\n".join(
        [
            f'cd "$HOME/{CHECKOUT}" </dev/null || {fail}',
            f"git fetch -q origin </dev/null >&2 || {fail}",
            f"git checkout -q --detach {sha} </dev/null >&2 || {fail}",
            f"make worktree-init </dev/null >&2 || {fail}",
            f"exec poetry run toolkit backup drill-{drill} --inputs-stdin",
        ]
    )


def preflight(git: GitRun, root: Path) -> Optional[str]:
    """HEAD of `root` when `origin` can reproduce it, else None after naming why."""
    base = ["git", "-C", str(root)]
    rc, status, err = git([*base, "status", "--porcelain"])
    if rc != 0:
        logger.error(f"drill: CANNOT CHECK — git could not read the tree: {err.strip()[:160]}")
        return None
    if status.strip():
        logger.error("drill: CANNOT CHECK — the tree has uncommitted changes; the host would not run them")
        return None
    rc, out, err = git([*base, "rev-parse", "HEAD"])
    sha = out.strip()
    if rc != 0 or not sha:
        logger.error(f"drill: CANNOT CHECK — git could not name HEAD: {err.strip()[:160]}")
        return None
    rc, branches, err = git([*base, "branch", "-r", "--contains", sha])
    if rc != 0:
        logger.error(f"drill: CANNOT CHECK — git could not list remote branches: {err.strip()[:160]}")
        return None
    if not any(line.strip().startswith("origin/") for line in branches.splitlines()):
        logger.error(
            f"drill: CANNOT CHECK — no origin/* branch here contains {sha[:12]}; "
            "push it, or `git fetch origin` if these refs are stale"
        )
        return None
    return sha


def run_remote(drill: str, inputs: dict[str, Any], *, target: str, sha: str, stream: Stream = _stream) -> bool:
    """Send `inputs` to `drill-<drill> --inputs-stdin` on `target` at `sha`. True only when the drill passes there."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, remote_script(drill, sha)]
    logger.info(f"drill: running {drill} on {target} at {sha[:12]}")
    rc = stream(argv, stdin=json.dumps({"drill": drill, "inputs": inputs}))
    if rc == 0:
        return True
    if rc == SSH_FAILED:
        logger.error(f"drill: CANNOT CHECK — could not reach {target} over ssh")
    elif rc == SETUP_FAILED:
        logger.error(f"drill: CANNOT CHECK — the drill checkout could not be prepared on {target} (see above)")
    else:
        logger.error(f"drill: {drill} did not pass on {target} (exit {rc}; its output above says why)")
    return False


def drill_on_host(
    drill: str,
    *,
    env: str,
    host: str,
    project_root: Optional[Path] = None,
    git: GitRun = _git,
    stream: Stream = _stream,
) -> bool:
    """Preflight this tree, resolve the drill's inputs here, and run it on `host`."""
    from toolkit.features.configuration import ConfigurationManager

    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    logger.section(f"{drill} restore drill on {host} ({env})")
    sha = preflight(git, root)
    if sha is None:
        return False
    try:
        net = ConfigurationManager(env, root).get_plaintext_values()["networking"]
    except KeyError:
        logger.error(f"drill: CANNOT CHECK — the {env} config declares no networking block")
        return False
    if host not in (net.get("nodes") or {}):
        logger.error(f"drill: CANNOT CHECK — networking.nodes.{host} is not declared")
        return False
    try:
        target = ssh_target(net, host)
    except KeyError as exc:  # resolve_ssh_user names what is missing
        logger.error(f"drill: CANNOT CHECK — {exc.args[0] if exc.args else exc}")
        return False
    inputs = module_for(drill).resolve_inputs(env, root)
    if inputs is None:
        return False
    return run_remote(drill, inputs, target=target, sha=sha, stream=stream)


def run_from_stdin(drill: str, text: str) -> bool:
    """The host's entrypoint: run `drill` on the payload in `text`. Never echoes any of it."""
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict) or payload.get("drill") != drill:
            raise ValueError("payload is for another drill")
        inputs = payload["inputs"]
        if not isinstance(inputs, dict):
            raise ValueError("inputs is not an object")
    except Exception as exc:  # noqa: BLE001 - name the failure class, never its content
        logger.error(f"drill: CANNOT CHECK — the inputs payload is unusable ({type(exc).__name__})")
        return False
    try:
        return bool(module_for(drill).run_from_inputs(inputs))
    except Exception as exc:  # noqa: BLE001 - a traceback would render the payload's values
        logger.error(f"drill: CANNOT CHECK — the drill could not run on these inputs ({type(exc).__name__})")
        return False
