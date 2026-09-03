"""SEC-VIKUNJA-001 (#1568) AC1: registration is closed in the RENDERED ConfigMap.

Reading `base/services/vikunja-config/vikunja.env` proves the key is written down.
It does not prove Kustomize emitted it, and prod does not consume that file directly
-- it merges its own override on top through `configMapGenerator` `behavior: merge`.
A merge that silently stopped applying, or a base key shadowed by an overlay, is
invisible to every file-reading check. That is not hypothetical in this repository:
`overlays/prod/patches.yaml` once carried a `tls: {}` block with a comment claiming
it removed the base's ACME resolver, and prod retried an impossible Let's Encrypt
order for months while every file-reading check agreed with the comment (#927).

So these assertions run `kubectl kustomize` and read what comes out, for BOTH
environments -- the fix reaches prod by inheritance, and an inherited value is
exactly the kind that a future overlay edit can drop without anyone noticing.

The live half is `tests/infra/test_vikunja_registration_closed_live.py`. Neither
replaces the other: this one fails when the manifest is wrong, that one fails when
the manifest is right and the pod never picked it up.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

ENVIRONMENTS = ("staging", "prod")

#: Kustomize appends a content hash, so the emitted name is `vikunja-config-<hash>`.
#: Matching on the prefix is deliberate -- pinning the full name would fail on every
#: unrelated edit to the env file, and a test that has to be updated whenever it goes
#: red gets loosened rather than read.
CONFIGMAP_PREFIX = "vikunja-config"

REGISTRATION_KEY = "VIKUNJA_SERVICE_ENABLEREGISTRATION"

#: A floor, not an inventory of the file. Its job is to catch an emitted ConfigMap
#: that is empty or truncated -- against which a `.get(REGISTRATION_KEY) != "true"`
#: style assertion would pass while nothing was configured at all. Copying the whole
#: key set here would instead fail on every legitimate addition (lesson-416).
LOAD_BEARING_KEYS = frozenset({"VIKUNJA_SERVICE_PUBLICURL", "VIKUNJA_DATABASE_TYPE"})


def _kustomize(path: str) -> list[dict]:
    """Render a Kustomize directory, or skip loudly if kubectl is unavailable.

    A skip here means CANNOT CHECK, which is not the same as OK and must never be
    reported as one.
    """
    if shutil.which("kubectl") is None:
        pytest.skip(
            "CANNOT CHECK: kubectl is not installed, so the rendered output cannot be "
            "produced. This is not a pass -- SEC-VIKUNJA-001 AC1 is unverified in this "
            "environment."
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


def _vikunja_config(env: str) -> dict:
    """The emitted `vikunja-config` ConfigMap for one overlay."""
    docs = _kustomize(f"infra/k8s/overlays/{env}")
    matches = [
        doc
        for doc in docs
        if doc.get("kind") == "ConfigMap" and str(doc.get("metadata", {}).get("name", "")).startswith(CONFIGMAP_PREFIX)
    ]

    assert len(matches) == 1, (
        f"expected exactly one ConfigMap named {CONFIGMAP_PREFIX}-* in the {env} "
        f"render, found {len(matches)}: {[m['metadata']['name'] for m in matches]}. "
        "Zero means the assertions below would have nothing to check; more than one "
        "means the Deployment's envFrom may not reference the one being asserted."
    )
    return matches[0]


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_public_registration_is_closed_in_the_render(env: str) -> None:
    """`VIKUNJA_SERVICE_ENABLEREGISTRATION=false` survives into both overlays.

    Absence is the failure this guards, not a wrong value: the key appeared nowhere
    in the repository until #1568, so Vikunja's own default (`true`) applied and prod
    answered 400 to `POST /api/v1/register`. An assertion phrased as "not true" would
    have passed against that instance.
    """
    data = _vikunja_config(env).get("data") or {}

    missing_floor = LOAD_BEARING_KEYS - set(data)
    assert not missing_floor, (
        f"the {env} `vikunja-config` render is missing keys that are always present: "
        f"{sorted(missing_floor)}. The ConfigMap is empty or truncated, so a check on "
        f"{REGISTRATION_KEY} alone would be vacuous. Fix the render before reading "
        "this file's result."
    )

    assert REGISTRATION_KEY in data, (
        f"{REGISTRATION_KEY} is absent from the {env} render. Vikunja defaults it to "
        "`true`, so absence IS public self-registration -- there is no wrong value to "
        "spot, which is how this survived review until #1568. Declare it in "
        "`infra/k8s/base/services/vikunja-config/vikunja.env`; prod inherits it via "
        "`behavior: merge`."
    )

    assert data[REGISTRATION_KEY] == "false", (
        f"{env} renders {REGISTRATION_KEY}={data[REGISTRATION_KEY]!r}, expected "
        "'false'. `tasks.kubelab.live` is internet-facing and ADR-066 D3 deliberately "
        "keeps Traefik ForwardAuth off it, so this flag is the registration control."
    )


def test_the_configmap_name_carries_a_hash_in_both_environments() -> None:
    """The generated name differs per environment, which is what rolls the pod.

    Vikunja reads its environment once at container start. If `vikunja-config` were
    ever emitted under a stable name, editing this value would leave Argo CD reporting
    Synced/Healthy while the running pod kept `true` indefinitely -- a silent no-op
    rather than a visible failure (lesson-404, #1446).

    Asserting the two environments differ does double duty: it proves a hash is being
    appended at all, and it proves prod's `behavior: merge` overlay is applied BEFORE
    hashing rather than being dropped.
    """
    names = {env: _vikunja_config(env)["metadata"]["name"] for env in ENVIRONMENTS}

    for env, name in names.items():
        assert name != CONFIGMAP_PREFIX, (
            f"{env} emits the bare name {CONFIGMAP_PREFIX!r} with no content hash. "
            "Changing a value would then not change the object name, and the running "
            "pod would never re-read it. Remove any `disableNameSuffixHash` option."
        )

    assert names["staging"] != names["prod"], (
        f"staging and prod emit the same ConfigMap name ({names['staging']}), so they "
        "carry identical content. Prod overrides its domain and bucket via "
        "`behavior: merge`; identical hashes mean that overlay is not being applied."
    )
