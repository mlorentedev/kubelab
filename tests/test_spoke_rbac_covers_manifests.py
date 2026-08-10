"""TOOL-029: every kind we ship must be writable by the identity that ships it.

Argo CD delivers to the spokes as a least-privilege ServiceAccount whose write
grants are enumerated by hand in `infra/k8s/argocd/spoke-rbac.yaml`, while reads
are wildcarded. A manifest introducing a *new* kind is therefore invisible to
lint, to the render, to the infra tests and to a workstation deploy — the only
actor that would refuse it is the ServiceAccount, and nothing consults it until
Argo CD tries, in a cluster, after merge.

That is exactly how #940 shipped a `LimitRange` that prod refused (#948).

The complementary safeguard impersonates the ServiceAccount during
`make deploy-k8s` (`toolkit/cli/infra.py:_impersonation_flag`), which is stronger
because it is an invariant rather than a list of known failures. But it needs a
reachable cluster, and the homelab is on-demand. This test needs nothing, so it
still runs on a GitHub-hosted runner with every node powered off — which is the
case the other safeguard cannot cover.

Deliberately reads the manifest *files* rather than `kubectl kustomize` output:
no kubectl on CI runners, and a new kind arrives as a file either way.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RBAC_MANIFEST = REPO_ROOT / "infra/k8s/argocd/spoke-rbac.yaml"

#: Only what Argo CD applies TO a spoke. `infra/k8s/argocd/` holds Application
#: and RBAC manifests that target the *hub* and are applied by other paths.
MANIFEST_ROOTS = ("infra/k8s/base", "infra/k8s/overlays")

#: Kustomize's own config, and rendered-secret audit copies (gitignored).
SKIPPED_KINDS = frozenset({"Kustomization", "Component"})
SKIPPED_PATH_PARTS = frozenset({".rendered"})

#: Kinds whose resource name is not derivable by rule. Keep this tiny and
#: explicit — an unknown kind must FAIL, never be silently skipped, because a
#: check that skips what it does not recognise reports success on the very
#: thing it was added to catch.
IRREGULAR_PLURALS = {
    "Endpoints": "endpoints",  # already plural
}

#: Resources the spoke may patch but deliberately may NOT create, with the reason.
#: An entry here is a recorded design decision, not a waiver — the object must
#: already exist in the cluster by some other path, and withholding `create` is
#: the point. Adding an entry should require arguing for it in review.
CREATE_NOT_REQUIRED = {
    ("", "namespaces"): (
        "The kubelab namespace is created by cluster bootstrap, not by Argo CD. "
        "The overlay only patches its labels and annotations, so patch+update is "
        "sufficient, and withholding create keeps the spoke unable to mint "
        "namespaces of its own. See the comment on argocd-manager-cluster-write."
    ),
}


def _plural(kind: str) -> str:
    """Lower-case resource name for a Kind, English pluralisation rules."""
    if kind in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[kind]
    lowered = kind.lower()
    if lowered.endswith("y"):
        return f"{lowered[:-1]}ies"
    if lowered.endswith(("s", "x", "ch", "sh")):
        return f"{lowered}es"
    return f"{lowered}s"


def _api_group(api_version: str) -> str:
    """Core group is the empty string, matching RBAC's `apiGroups: [""]`."""
    return api_version.split("/")[0] if "/" in api_version else ""


def _shipped_resources() -> dict[tuple[str, str], set[str]]:
    """Map (apiGroup, resource) -> the manifest files that ship it."""
    shipped: dict[tuple[str, str], set[str]] = {}
    for root in MANIFEST_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.yaml")):
            if SKIPPED_PATH_PARTS & set(path.parts):
                continue
            try:
                docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except yaml.YAMLError as exc:  # a malformed manifest is a failure, not a skip
                pytest.fail(f"{path.relative_to(REPO_ROOT)} is not parseable YAML: {exc}")
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                kind = doc.get("kind")
                if not kind or kind in SKIPPED_KINDS:
                    continue
                key = (_api_group(doc.get("apiVersion", "")), _plural(kind))
                shipped.setdefault(key, set()).add(str(path.relative_to(REPO_ROOT)))
    return shipped


def _granted_verbs() -> dict[tuple[str, str], set[str]]:
    """Map (apiGroup, resource) -> the verbs the spoke is granted on it."""
    granted: dict[tuple[str, str], set[str]] = {}
    for doc in yaml.safe_load_all(RBAC_MANIFEST.read_text(encoding="utf-8")):
        if not doc or doc.get("kind") not in ("ClusterRole", "Role"):
            continue
        for rule in doc.get("rules") or []:
            verbs = set(rule.get("verbs", []))
            for group in rule.get("apiGroups", []):
                for resource in rule.get("resources", []):
                    granted.setdefault((group, resource), set()).update(verbs)
    return granted


def _is_covered(key: tuple[str, str], granted: dict[tuple[str, str], set[str]]) -> bool:
    """Can the spoke apply this resource?

    `create` is the verb that matters: a manifest introducing a kind the cluster
    has never seen needs it, and that is precisely the case every other gate is
    blind to. A resource may opt out via CREATE_NOT_REQUIRED, but must then still
    be patchable — otherwise Argo CD cannot reconcile it at all.
    """
    verbs = granted.get(key, set())
    if "create" in verbs:
        return True
    return key in CREATE_NOT_REQUIRED and bool({"patch", "update"} & verbs)


class TestSpokeRbacCoversManifests:
    """The spoke's write grants must cover every kind the repo ships."""

    def test_rbac_manifest_is_readable(self) -> None:
        """Guard the guard: if this file moves, the test below must not pass vacuously."""
        assert RBAC_MANIFEST.exists(), f"Spoke RBAC manifest not found at {RBAC_MANIFEST}"
        assert _granted_verbs(), "Parsed zero grants — the parser no longer matches the manifest"

    def test_create_exemptions_are_still_needed(self) -> None:
        """A stale exemption is a hole nobody is looking at.

        If a resource in CREATE_NOT_REQUIRED later gains `create`, the entry has
        outlived its reason and must go, or it will silently excuse a future
        regression on that resource.
        """
        granted = _granted_verbs()
        stale = [key for key in CREATE_NOT_REQUIRED if "create" in granted.get(key, set())]
        assert not stale, (
            f"These resources now grant `create`, so their CREATE_NOT_REQUIRED entries are "
            f"obsolete and should be deleted: {stale}"
        )

    def test_every_shipped_kind_is_writable_by_the_spoke(self) -> None:
        shipped = _shipped_resources()
        assert shipped, "Found no manifests to check — the globs no longer match the repo layout"

        granted = _granted_verbs()
        missing = {key: files for key, files in shipped.items() if not _is_covered(key, granted)}

        if missing:
            lines = [
                "Kinds shipped in git that Argo CD's ServiceAccount cannot write.",
                "Argo CD will refuse these AFTER merge, in prod, and the failing sync",
                "blocks the app from reporting Synced. Add them to the appropriate role",
                f"in {RBAC_MANIFEST.relative_to(REPO_ROOT)}:",
                "",
            ]
            for (group, resource), files in sorted(missing.items()):
                lines.append(f"  apiGroup {group or '(core)'!r:12} resource {resource!r}")
                for f in sorted(files)[:3]:
                    lines.append(f"      shipped by {f}")
            pytest.fail("\n".join(lines))
