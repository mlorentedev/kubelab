"""Which commands a unit test may not spawn (#1886).

A unit test that reaches a real cluster or host does not fail when the binary is
missing; it skips, or the toolkit swallows the `FileNotFoundError`. So the same
test passes in CI (no kubeconfig) and mutates staging on a workstation that has
one. `denied` names the command when argv would start such a client, and the
barrier in `conftest.py` refuses it unless the test opts in.

Only commands in command position count: argv[0], the command after a wrapper
(`sudo`, `timeout`, `env`), and every command inside an `sh -c` string. An
argument that happens to be called `restic` is not a restic invocation.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from pathlib import PurePath

# Clients whose only job is to reach something outside this machine.
DENIED = frozenset(
    {
        "kubectl",
        "helm",
        "ssh",
        "scp",
        "rsync",
        "ansible",
        "ansible-playbook",
        "terraform",
        "tofu",
        "tailscale",
        "headscale",
        "restic",
    }
)

# Subcommands of a denied client that never leave the machine.
LOCAL_SUBCOMMANDS = {
    "kubectl": {"kustomize"},
    "helm": {"template", "lint", "version"},
}

# kubectl/helm global flags that take a value as the next token.
VALUED_FLAGS = frozenset(
    {
        "--kubeconfig",
        "-n",
        "--namespace",
        "--context",
        "--kube-context",
        "--cluster",
        "--user",
        "--as",
        "--as-group",
        "-s",
        "--server",
        "--token",
        "--request-timeout",
    }
)

# Commands that run another command, and which of their flags take a value
# (`sudo -u deployer kubectl ...` runs kubectl, not `deployer`).
WRAPPERS = {
    "sudo": frozenset({"-u", "-g", "-h", "-C", "-D", "-p", "-r", "-t", "-U", "-R"}),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "env": frozenset({"-u", "-C", "--unset", "--chdir"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "xargs": frozenset({"-I", "-n", "-P", "-L", "-d", "-E", "-a", "-s"}),
    "nohup": frozenset(),
    "time": frozenset(),
    "command": frozenset(),
    "exec": frozenset(),
}
SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
SEPARATORS = frozenset({";", "|", "||", "&", "&&", "(", ")", "\n"})
_DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _name(token: str) -> str:
    name = PurePath(token).name
    return name[:-4] if name.endswith(".exe") else name


def _shell_tokens(script: str) -> list[str]:
    lexer = shlex.shlex(script, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _subcommand(rest: Sequence[str]) -> tuple[str | None, list[str]]:
    """The first positional word after the client's global flags, and what follows it."""
    i = 0
    while i < len(rest):
        token = rest[i]
        if token in SEPARATORS:
            return None, []
        if token in VALUED_FLAGS:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return token, list(rest[i + 1 :])
    return None, []


def _judge(name: str, rest: Sequence[str]) -> str | None:
    sub, after = _subcommand(rest)
    if name not in LOCAL_SUBCOMMANDS:
        return name
    if sub in LOCAL_SUBCOMMANDS[name]:
        return None
    if name == "kubectl" and sub == "version" and any(t.startswith("--client") for t in after):
        return None
    return f"{name} {sub}" if sub else name


def _scan(tokens: Sequence[str]) -> str | None:
    at_command = True
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in SEPARATORS:
            at_command = True
            i += 1
            continue
        if not at_command:
            i += 1
            continue
        if _ASSIGNMENT.match(token):
            i += 1
            continue
        name = _name(token)
        if name in WRAPPERS:
            valued = WRAPPERS[name]
            i += 1
            while i < len(tokens) and (
                tokens[i].startswith("-") or _ASSIGNMENT.match(tokens[i]) or _DURATION.match(tokens[i])
            ):
                i += 2 if tokens[i] in valued else 1
            continue
        at_command = False
        if name in SHELLS and "-c" in tokens[i + 1 : i + 3]:
            c = tokens.index("-c", i + 1)
            if c + 1 < len(tokens):
                found = _scan(_shell_tokens(tokens[c + 1]))
                if found:
                    return found
            i = c + 2
            continue
        if name in DENIED:
            found = _judge(name, tokens[i + 1 :])
            if found:
                return found
        i += 1
    return None


def denied(args: str | bytes | Sequence[str], shell: bool = False) -> str | None:
    """`"<client> <subcommand>"` when argv would reach a cluster or a host, else None.

    With `shell=True` (as `Popen` takes it), a sequence's first item is the script.
    """
    if isinstance(args, (str, bytes)):
        script = args.decode() if isinstance(args, bytes) else args
        return _scan(_shell_tokens(script))
    argv = [str(a) for a in args]
    if shell and argv:
        return _scan(_shell_tokens(argv[0]))
    return _scan(argv)
