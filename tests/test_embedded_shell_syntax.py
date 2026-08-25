"""Every shell script embedded in a K8s manifest must parse as a shell script.

A container that runs `command: [/bin/sh, -e, -c]` with the program in `args`
carries a second language inside a YAML string, and nothing in the delivery path
reads it as one. `yamllint` sees a valid string. `kubectl kustomize` renders it.
`kubectl apply` accepts it. The Argo CD sync succeeds. The manifest is *correct
YAML describing a broken program*, and the first actor that evaluates the shell
is the container itself — a CronJob pod, on a schedule, in a cluster, where the
symptom is a Failed Job that nothing alerts on.

Measured 2026-08-25 (#1378): a fix to `disk-watcher`'s emitter added an
explanatory comment inside the jq program, which is passed as `jq -c '...'` —
single-quoted *by the shell*. The comment read:

    # A NUMBER, never `(.status.phase == "Bound")`. jq's `==`
    # yields a JSON boolean, LogQL's `unwrap` needs a float, and

`jq's` and `LogQL's` each close the shell's single-quoted string. They are
comments to jq and never reach it, because the shell finished the word first.
Result: `sh -n` exit 2, and the 02:45 job failed where 02:00, 02:15 and 02:30
had all completed. The comment explaining the fix was what broke the fix.

Note what that costs beyond a dead watcher: `disk-watcher` feeds an alert whose
`noDataState` is `Alerting`. A watcher that fails produces no samples, so the
alert fires — correctly-looking, for entirely the wrong reason. A broken emitter
and a genuinely unbound PVC are indistinguishable downstream.

`sh -n` parses without executing, so this needs no cluster, no images and no
network. It runs with the homelab powered off, which is the point: the failure
it catches otherwise surfaces only after a merge, in a cluster, on a schedule.

Scope note — this checks *syntax*, not behaviour. A script that parses can still
be wrong. It is a floor, deliberately: the failure it catches is one nothing
else in the pipeline looks for.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Manifest trees that ship to a cluster.
MANIFEST_ROOTS = ("infra/k8s/base", "infra/k8s/overlays")

#: Gitignored audit copies of SOPS-rendered middlewares (see ADR-035 Stage 1).
SKIPPED_PATH_PARTS = frozenset({".rendered"})

#: `command[0]` values that mean "the following is a shell program".
SHELL_BINARIES = frozenset(
    {"sh", "/bin/sh", "ash", "/bin/ash", "bash", "/bin/bash", "dash", "/bin/dash"}
)

#: Where a container may hold a script.
CONTAINER_KEYS = ("containers", "initContainers", "ephemeralContainers")


def _iter_containers(node, path=()):
    """Yield every container mapping anywhere in a manifest document.

    Walks the whole tree rather than addressing `spec.template.spec.containers`:
    the same shape appears under Deployment, CronJob (one level deeper via
    jobTemplate), DaemonSet and Job, and enumerating those paths is how a new
    kind silently escapes the check.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in CONTAINER_KEYS and isinstance(value, list):
                for container in value:
                    if isinstance(container, dict):
                        yield container
            yield from _iter_containers(value, (*path, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _iter_containers(item, (*path, index))


def _script_of(container):
    """Return the shell program this container runs, or None.

    Two shapes are in use and both are legitimate:
      command: [/bin/sh, -e, -c]   args: ["<program>"]
      command: [sh, -c, "<program>"]
    """
    command = container.get("command") or []
    if not command or not isinstance(command, list):
        return None
    if str(command[0]) not in SHELL_BINARIES:
        return None
    if "-c" not in [str(part) for part in command]:
        return None

    dash_c = [str(part) for part in command].index("-c")
    if len(command) > dash_c + 1:
        return str(command[dash_c + 1])

    args = container.get("args") or []
    if args and isinstance(args, list):
        return str(args[0])
    return None


def _collect():
    found = []
    for root in MANIFEST_ROOTS:
        for manifest in sorted((REPO_ROOT / root).rglob("*.yaml")):
            if SKIPPED_PATH_PARTS & set(manifest.parts):
                continue
            try:
                documents = list(yaml.safe_load_all(manifest.read_text()))
            except yaml.YAMLError:
                # Not this test's job — the YAML linters own malformed files,
                # and failing here would report the wrong defect.
                continue
            for document in documents:
                if not isinstance(document, dict):
                    continue
                kind = document.get("kind", "?")
                name = (document.get("metadata") or {}).get("name", "?")
                for container in _iter_containers(document):
                    script = _script_of(container)
                    if script:
                        label = (
                            f"{manifest.relative_to(REPO_ROOT)}::"
                            f"{kind}/{name}::{container.get('name', '?')}"
                        )
                        found.append(pytest.param(script, id=label))
    return found


EMBEDDED_SCRIPTS = _collect()


def test_manifests_actually_contain_embedded_scripts():
    """Guard the guard.

    A walker that silently stops matching turns this file into a suite of zero
    passing tests, which reads exactly like a clean bill of health. If the
    manifests genuinely stop embedding shell, delete this file deliberately
    rather than letting it decay into decoration.
    """
    assert EMBEDDED_SCRIPTS, (
        "No embedded shell scripts found under "
        f"{MANIFEST_ROOTS}. Either the container walker broke, or the manifests "
        "no longer embed shell — verify which before touching this assertion."
    )


@pytest.mark.parametrize("script", EMBEDDED_SCRIPTS)
def test_embedded_shell_script_parses(script):
    result = subprocess.run(
        ["sh", "-n"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "Embedded shell script does not parse.\n\n"
        f"sh -n said: {result.stderr.strip()}\n\n"
        "The usual cause is an apostrophe inside a single-quoted program — a "
        "comment saying \"jq's\" or \"don't\" inside `jq -c '...'` closes the "
        "shell string before jq ever sees it. Reword without the apostrophe, or "
        "move the prose into the YAML comments above the block, where the shell "
        "never reads it."
    )
