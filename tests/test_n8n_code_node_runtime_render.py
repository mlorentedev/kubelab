"""APP-CONFIG-014 (#1705): n8n's environment satisfies what its Code nodes need.

`multi-forge-sync` read its HMAC secret from `$env` and n8n blocks Code-node access
to `$env` by default (`N8N_BLOCK_ENV_ACCESS_IN_NODE`, true since n8n v20). The node
threw on the first read, so the workflow failed at its FIRST Code node -- before the
signature check, before routing, before the project lookup. Measured across every
rotated event log in prod: `workflow.success` for that workflow = 0, ever, against
6008 for `notify-router`. The integration never ran once.

Nothing reported it. The webhook answers 200 to an unsigned request, to a
bad-signature request, and to its own crash, because n8n's Respond node is not what
emits that status on a failed run. A green delivery in Gitea, an active workflow and
a healthy pod were all true the whole time.

THE REQUIREMENT IS DERIVED FROM THE WORKFLOWS, NOT COPIED FROM THE MANIFEST. A test
holding its own list of required keys passes when the manifest matches the list and
says nothing about whether the list still matches what the workflows do. So this
reads the committed workflow JSON, extracts what its Code nodes actually reference,
and asserts the RENDERED ConfigMap satisfies exactly that (lesson-416). Add a
workflow that touches `$env` or `require`s a new builtin and this fails until the
environment is declared for it.

Rendered, not read from the source file, for the reason `test_vikunja_registration_
render.py` gives at length: prod merges its own overrides on top, and a merge that
stops applying is invisible to every file-reading check.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "infra" / "n8n" / "workflows"

ENVIRONMENTS = ("staging", "prod")
CONFIGMAP_PREFIX = "n8n-config"

CODE_NODE_TYPE = "n8n-nodes-base.code"

#: `$env.FOO` / `$env['FOO']` / `$env["FOO"]`.
ENV_REFERENCE = re.compile(r"\$env(?:\.\w+|\[\s*['\"]\w+['\"]\s*\])")

#: `require('crypto')`, single or double quoted.
REQUIRE_CALL = re.compile(r"require\(\s*['\"]([\w/-]+)['\"]\s*\)")

#: A floor, not an inventory: catches an emitted ConfigMap that is empty or
#: truncated, against which the assertions below would be vacuously true. Copying
#: the whole key set here would fail on every legitimate addition.
LOAD_BEARING_KEYS = frozenset({"N8N_HOST", "WEBHOOK_URL", "DB_TYPE"})


def _kustomize(path: str) -> list[dict]:
    """Render a Kustomize directory, or skip loudly if kubectl is unavailable.

    A skip means CANNOT CHECK, which is not a pass and must never be reported as one.
    """
    if shutil.which("kubectl") is None:
        pytest.skip(
            "CANNOT CHECK: kubectl is not installed, so the rendered output cannot be "
            "produced. This is not a pass -- #1705 is unverified in this environment."
        )

    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize {path} failed:\n{result.stderr}")

    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _n8n_config(env: str) -> dict:
    docs = _kustomize(f"infra/k8s/overlays/{env}")
    matches = [
        doc
        for doc in docs
        if doc.get("kind") == "ConfigMap" and str(doc.get("metadata", {}).get("name", "")).startswith(CONFIGMAP_PREFIX)
    ]
    assert len(matches) == 1, (
        f"expected exactly one ConfigMap named {CONFIGMAP_PREFIX}-* in the {env} render, "
        f"found {len(matches)}: {[m['metadata']['name'] for m in matches]}."
    )
    return matches[0]


def _code_node_sources() -> dict[str, str]:
    """Every committed Code node's JavaScript, keyed `workflow::node`."""
    sources: dict[str, str] = {}
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for node in document.get("nodes", []):
            if node.get("type") != CODE_NODE_TYPE:
                continue
            code = (node.get("parameters") or {}).get("jsCode")
            if isinstance(code, str):
                sources[f"{path.stem}::{node.get('name')}"] = code
    return sources


def test_the_scan_finds_code_to_scan() -> None:
    """Anti-vacuity, on the value the assertions actually consume.

    Every requirement below is derived from `_code_node_sources()`. If that returns
    nothing -- a moved directory, a renamed node type, a schema change -- each derived
    set is empty, every assertion holds trivially, and the suite reports the
    environment as correct without having examined anything. An empty expectation is
    not a weak expectation; it matches everything (lesson-416).
    """
    sources = _code_node_sources()

    assert sources, (
        f"no Code nodes found under {WORKFLOW_DIR}. Either the workflows moved or "
        f"{CODE_NODE_TYPE!r} is no longer the node type. Until this is fixed the other "
        "tests in this file prove nothing."
    )
    assert any(ENV_REFERENCE.search(code) for code in sources.values()), (
        "no committed Code node references `$env`, so the requirement this file "
        "derives is empty. If that is genuinely true now, delete this file rather than "
        "leaving a guard that cannot fail."
    )
    assert any(REQUIRE_CALL.search(code) for code in sources.values()), (
        "no committed Code node matches REQUIRE_CALL, so the allowlist requirement is "
        "empty and `test_every_builtin_a_code_node_requires_is_allowlisted` skips — "
        "green without having checked anything. `Parse Forge Event` does "
        "`require('crypto')` today, so this firing means the regex stopped matching "
        "reality, not that the requirement went away. Widen the pattern rather than "
        "deleting the assertion.\n\n"
        "BOTH derivations are pinned, not just `$env`, and they fail differently: a "
        "regex that silently stops matching turns its dependent test into a skip, and "
        "a skip is not a pass. Raised by pr-agent on #1706 — the `$env` half had this "
        "guard and the `require` half did not, which is the same asymmetry that let "
        "the bug being fixed here reach prod."
    )


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_env_access_is_unblocked_where_a_code_node_reads_env(env: str) -> None:
    """`$env` works in Code nodes, in both renders.

    Absence is the failure, not a wrong value: n8n's default is to block, so a
    ConfigMap that simply omits the key IS the outage. An assertion phrased as
    `!= "true"` would have passed against the broken instance.
    """
    users = {name: code for name, code in _code_node_sources().items() if ENV_REFERENCE.search(code)}
    if not users:
        pytest.skip("no Code node reads $env")

    data = _n8n_config(env).get("data") or {}

    missing_floor = LOAD_BEARING_KEYS - set(data)
    assert not missing_floor, (
        f"the {env} `n8n-config` render is missing always-present keys {sorted(missing_floor)}. "
        "The ConfigMap is empty or truncated, so the check below would be vacuous."
    )

    key = "N8N_BLOCK_ENV_ACCESS_IN_NODE"
    assert key in data, (
        f"{key} is absent from the {env} render, and n8n defaults it to `true` (blocked) "
        f"since v20. These Code nodes read `$env` and would throw "
        f"'access to env vars denied' before running any of their own logic: "
        f"{sorted(users)}."
    )
    assert data[key] == "false", f"{env} renders {key}={data[key]!r}, expected 'false'."


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_builtin_a_code_node_requires_is_allowlisted(env: str) -> None:
    """`require(...)` in a Code node needs the module on `NODE_FUNCTION_ALLOW_BUILTIN`.

    This is the second half of #1705 and the reason the fix is two variables rather
    than one: unblocking `$env` alone moves `Parse Forge Event`'s failure from its
    `$env` read to the `require('crypto')` two lines below it -- a different error,
    the same dead integration.
    """
    required: set[str] = set()
    for code in _code_node_sources().values():
        required.update(REQUIRE_CALL.findall(code))
    if not required:
        pytest.skip("no Code node requires a module")

    data = _n8n_config(env).get("data") or {}
    allowed_raw = data.get("NODE_FUNCTION_ALLOW_BUILTIN", "")
    allowed = {part.strip() for part in allowed_raw.split(",") if part.strip()}

    if "*" in allowed:
        return

    missing = required - allowed
    assert not missing, (
        f"{env} renders NODE_FUNCTION_ALLOW_BUILTIN={allowed_raw!r}, which does not cover "
        f"{sorted(missing)}. A Code node requiring a module that is not allowlisted throws "
        "at the `require` call, and the workflow dies at that node while the webhook still "
        "answers 200."
    )


def test_the_configmap_name_carries_a_hash_in_both_environments() -> None:
    """The generated name differs per environment, which is what rolls the pod.

    n8n reads its environment once at container start, and `n8n-config` is consumed
    through `envFrom`. Under a stable name, adding these keys would leave Argo CD
    reporting Synced/Healthy while the running pod kept the old environment forever --
    the change would not exist (lesson-404, #1446).

    Asserting the two environments DIFFER does double duty: it proves a hash is
    appended at all, and it proves prod's overlay is applied BEFORE hashing rather
    than being dropped.
    """
    names = {env: _n8n_config(env)["metadata"]["name"] for env in ENVIRONMENTS}

    for env, name in names.items():
        assert name != CONFIGMAP_PREFIX, (
            f"{env} emits the bare name {CONFIGMAP_PREFIX!r} with no content hash. "
            "Changing a value would not change the object name, and the running pod "
            "would never re-read it."
        )

    assert names["staging"] != names["prod"], (
        f"staging and prod emit the same ConfigMap name ({names['staging']}), so they carry "
        "identical content. Prod overrides its domain and log level; identical hashes mean "
        "that overlay is not being applied."
    )
