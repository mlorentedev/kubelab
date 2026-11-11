"""Run `git` against the Gitea forge with a credential that never reaches a terminal.

WHO PUSHES. The agents' authoring account (`apps.auth.identities.agent`, AUTH-022),
with its API token as the password of an HTTPS basic-auth login, which Gitea
accepts. Its token carries `write:issue,write:repository`, and its write reaches
only the repositories that name it under `writers:` in `gitea.organizations`, as
a collaborator; the default branch of each of those is protected, with a push
whitelist that does not include it (AUTH-024). So an agent pushes a branch and
opens a pull request, and every operation is recorded as the agent.

Until #2578 this path authenticated as the forge's sole admin with the password
ADR-062 D4 reserves for when Authelia is unavailable, and checked no such
condition, because no non-admin identity could author. AUTH-022 created one.
There is NO FALLBACK to that password: with the token absent the run fails and
names the key, because a fallback would put the break-glass credential back on
the routine path the first time a token went missing.

It is NOT the human path: a person works on the forge over SSH with the key on
their own account, through the `forge` host that dotfiles declares and pins
(dotfiles#2512) -- `git clone forge:personal/resume.git`.

WHY HTTPS NEEDS IT. The forge's SSH is published on the mesh only, and over HTTPS
no workstation holds a per-human credential for `gitea.kubelab.live` -- only `github.com`,
via `gh`. The obvious workarounds are all the wrong shape: a token in the remote URL
lands in `.git/config` and in every error message that echoes the address; a
`store` helper writes it to `~/.git-credentials` in plaintext; and printing it to
copy-paste puts it in a transcript, which is a durable artefact nothing scans and
nothing can un-print.

WHY THE OTHER TOKENS ARE NOT IT. Measured by consequence against prod on
2026-09-04, pushing a ref to `personal/resume` and deleting it: `admin_token` is
refused with 403 at the HTTP layer (no `write:repository`, deliberately: that
scope on a token holding admin reach is a standing DELETE capability), and the
bot reaches receive-pack but authoring is not its role (ADR-065 D1 puts the
machine identity in reconciliation). That measurement is also what shows Gitea
honours a token as a basic-auth password on the git endpoints: the admin token
was refused by its scope, not by the login.

NOTE THE PROBE, because it is the reason this docstring can say "measured": a
`git push --dry-run` crosses Gitea's token-scope gate and stops there, so it
reported success for a credential the pre-receive hook then refused. See
lesson-425.

HOW THE SECRET TRAVELS. Into the child process's environment, and nowhere else:

- NOT on a command line, where it would be visible in `ps` to every user on the box
  and captured by any shell-history or audit hook.
- NOT in the repository's config, so the clone is safe to hand to anyone.
- NOT on this process's stdout. The inline helper's stdout is the pipe git reads
  from, not the terminal -- git execs it and consumes the answer.

`GIT_TERMINAL_PROMPT=0` and `GIT_ASKPASS=/bin/false` are the fail-closed pair: if
the helper is ever bypassed, git must fail rather than block a non-interactive run
forever waiting on a prompt nobody will answer.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

#: The inline credential helper. It answers git's `get` with two lines read from
#: the environment this module sets on the child.
#:
#: THE LEADING `!` IS LOAD-BEARING: without it git looks for a program called
#: `git-credential-f() {...}` and the whole thing fails with a shell syntax error
#: rather than with anything that names the cause. Measured while writing the
#: probe this module came from.
#:
#: It answers every action, including `store` and `erase`, by doing nothing for
#: those -- git only ever reads the `get` output, and a helper that errored on the
#: others would make a successful push print a spurious failure.
CREDENTIAL_HELPER = (
    '!f() { test "$1" = get || exit 0; echo "username=$GITEA_GIT_USER"; echo "password=$GITEA_GIT_PASS"; }; f'
)

#: Passed to every invocation. `core.hooksPath` is neutralised because this repo
#: sets it GLOBALLY to its own shared hooks directory, so ANY clone on this machine
#: inherits kubelab's pre-commit -- including foreign repositories that have their
#: own. Measured: a push probe against `personal/resume` ran kubelab's
#: trailing-whitespace hook, which modified files in the clone and aborted the push
#: with an exit code that read as "permission denied".
BASE_CONFIG: tuple[str, ...] = (
    "-c",
    f"credential.helper={CREDENTIAL_HELPER}",
    "-c",
    "core.hooksPath=/dev/null",
)


class GiteaGitError(Exception):
    """The credential needed to talk to the forge is absent from SOPS."""


def resolve_git_credential(merged: Mapping[str, Any]) -> tuple[str, str]:
    """`(login, token)` of the agents' authoring account, from a merged configuration.

    SEPARATE FROM THE RUNNER so a test can assert WHICH credential is chosen
    without running git, and so the choice is stated in one place rather than
    inlined at a call site where a later edit could quietly swap it back.
    """
    gitea = merged["apps"]["services"]["core"]["gitea"]
    username = str(merged["apps"]["auth"]["identities"]["agent"])
    token = gitea.get("agent_token")
    if not token:
        raise GiteaGitError(
            "apps.services.core.gitea.agent_token is absent from SOPS, and it is the only "
            f"credential this command pushes with: it authenticates as the agents' account ({username}). "
            "Mint it with `make provision NODE=bee ENV=prod TAGS=gitea` (AUTH-022); there is no "
            "fallback to the admin password, which ADR-062 D4 keeps for break-glass."
        )
    return username, str(token)


def build_env(username: str, password: str, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child environment carrying the credential.

    Fails closed on both fallbacks: with no helper answer, git must error rather
    than prompt. A run that blocks forever on an invisible prompt is the failure
    mode that makes people paste tokens onto command lines.
    """
    return {
        **(dict(base_env) if base_env is not None else dict(os.environ)),
        "GITEA_GIT_USER": username,
        "GITEA_GIT_PASS": password,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
    }


def build_argv(args: Sequence[str]) -> list[str]:
    """The full `git` command line. THE CREDENTIAL IS NOT IN IT, by construction.

    Asserted directly by the test suite, because "the secret is not on the command
    line" is a property of this list and of nothing else -- and a command line is
    readable by every user on the host through `ps`, which no amount of care
    elsewhere compensates for.
    """
    return ["git", *BASE_CONFIG, *args]


def run_git(
    args: Sequence[str],
    merged: Mapping[str, Any],
    cwd: Path | None = None,
    runner: Any = subprocess.run,
) -> int:
    """Run `git <args>` with the forge credential injected. Returns git's exit code.

    OUTPUT IS NOT CAPTURED. It streams to the caller's terminal, which is both what
    makes this usable interactively and safe to stream: git never echoes the
    credential -- the helper writes it to a pipe git reads, not to a terminal.
    Capturing it would mean re-emitting it, and re-emitting output is how a secret
    that stayed out of a log ends up in a transcript.
    """
    username, password = resolve_git_credential(merged)
    proc = runner(build_argv(args), cwd=str(cwd) if cwd else None, env=build_env(username, password))
    return int(proc.returncode)
