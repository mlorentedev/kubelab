"""Every K8s manifest must have a declared path to the cluster.

The defect this guards against (found by SEC-004 / kubelab#970, 2026-08-15): a
manifest can be *correct in git* and *absent from the cluster* indefinitely,
with nothing reporting a problem. `infra/k8s/overlays/prod/argocd.yaml` sat with
the SEC-004 `rate-limit` middleware applied to nothing, while the `kubelab-prod`
Argo CD Application reported `Synced` the whole time -- a Synced Application
says nothing about resources it does not manage, and the whole file was outside
the overlay because *one* of its three documents carries a `RESOLVE_*`
placeholder. That file has since been split so only the EndpointSlice stays out
(see `OUT_OF_BAND` below); the general hazard is what this test covers.

So a manifest under `infra/k8s/{base,overlays}` must be reachable by exactly one
of three routes, and this test fails if it is reachable by none:

1. referenced by a `kustomization.yaml` (Argo CD syncs it),
2. declared in `cluster_bootstrap` in common.yaml (ADR-047 D2 applies it),
3. named in `OUT_OF_BAND` below, together with the command that applies it.

Route 3 is the point of this test. It does not forbid out-of-band manifests --
they are a legitimate, ADR-backed category -- it forbids *silent* ones. Adding a
manifest that nothing applies now requires writing down what applies it.

Deliberately reads files, no kubectl: this has to run on a CI runner with no
cluster, mirroring `tests/test_spoke_rbac_covers_manifests.py`. It therefore
proves a manifest has a *route* to the cluster, never that it *arrived* -- that
second axis needs a live check (`tests/infra/test_rate_limit.py` does it for the
rate-limit middleware specifically).
"""

from __future__ import annotations

import pathlib
import re
from typing import NamedTuple

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
K8S_ROOTS = ("infra/k8s/base", "infra/k8s/overlays")
COMMON_YAML = REPO_ROOT / "infra/config/values/common.yaml"
MAKEFILE = REPO_ROOT / "Makefile"

#: `.rendered/` is the gitignored audit copy of secret-bearing middlewares
#: (ADR-035); it is output, not source.
SKIPPED_DIR_PARTS = frozenset({".rendered"})
MANIFEST_SUFFIXES = (".yaml", ".yml")


class OutOfBand(NamedTuple):
    """A manifest applied by something other than Kustomize or cluster_bootstrap."""

    #: The Makefile target that applies it. Asserted to exist -- see
    #: `test_every_out_of_band_trigger_exists`.
    trigger: str
    #: Why it cannot go through the overlay. One line, no hand-waving.
    reason: str


#: Manifests with no kustomization and no `cluster_bootstrap` entry. Each needs a
#: real trigger and a real reason. Keep this list SHORT -- every entry is a
#: resource that drifts silently between deploys.
OUT_OF_BAND: dict[str, OutOfBand] = {
    "infra/k8s/overlays/prod/argocd-endpointslice.yaml": OutOfBand(
        trigger="deploy-argocd",
        reason=(
            "Carries RESOLVE_GCP1_TAILSCALE_IP -- gcp1 is a Spot instance and its "
            "Tailscale IP rotates on replacement, so the value cannot be committed "
            "(ADR-047 D3 / TOOL-009 T4). Split out of argocd.yaml so that only this "
            "one document stays out-of-band; the Service and IngressRoute alongside "
            "it are Kustomize-managed."
        ),
    ),
    "infra/k8s/overlays/prod/secrets.yaml": OutOfBand(
        trigger="apply-secrets",
        reason="Placeholders only (REPLACE_WITH_SOPS_VALUE); real values injected from SOPS at deploy time (ADR-014/ADR-038).",
    ),
    "infra/k8s/overlays/staging/secrets.yaml": OutOfBand(
        trigger="apply-secrets",
        reason="Placeholders only (REPLACE_WITH_SOPS_VALUE); real values injected from SOPS at deploy time (ADR-014/ADR-038).",
    ),
}


def _manifest_files() -> list[pathlib.Path]:
    """Every candidate manifest under the Kustomize-managed roots."""
    files: list[pathlib.Path] = []
    for root in K8S_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*")):
            if not path.is_file() or path.suffix not in MANIFEST_SUFFIXES:
                continue
            if SKIPPED_DIR_PARTS & set(path.parts):
                continue
            if path.name == "kustomization.yaml":
                continue
            files.append(path)
    return files


def _kustomization_referenced() -> set[pathlib.Path]:
    """Every file path any kustomization.yaml pulls in, resolved absolute.

    Covers the four reference styles this repo actually uses: `resources`,
    `patches[].path`, and the `files` lists of `configMapGenerator` /
    `secretGenerator`. Directory entries (`../../base`) resolve to that
    directory's own kustomization, which is parsed on its own pass.
    """
    referenced: set[pathlib.Path] = set()
    for kustomization in sorted((REPO_ROOT / "infra/k8s").rglob("kustomization.yaml")):
        doc = yaml.safe_load(kustomization.read_text(encoding="utf-8")) or {}
        base = kustomization.parent
        for entry in doc.get("resources", []) or []:
            referenced.add((base / entry).resolve())
        for patch in doc.get("patches", []) or []:
            if isinstance(patch, dict) and "path" in patch:
                referenced.add((base / patch["path"]).resolve())
        for key in ("configMapGenerator", "secretGenerator"):
            for generator in doc.get(key, []) or []:
                for file_entry in generator.get("files", []) or []:
                    # `key=path` form is supported by kustomize; take the path half.
                    path_part = file_entry.split("=", 1)[-1]
                    referenced.add((base / path_part).resolve())
    return referenced


def _cluster_bootstrap_manifests() -> set[pathlib.Path]:
    """Manifest paths declared in the ADR-047 cluster_bootstrap SSOT."""
    config = yaml.safe_load(COMMON_YAML.read_text(encoding="utf-8")) or {}
    return {
        (REPO_ROOT / entry["manifest"]).resolve()
        for entry in config.get("cluster_bootstrap", []) or []
        if entry.get("manifest")
    }


class TestNoOrphanManifests:
    def test_at_least_one_manifest_found(self) -> None:
        """Guard the guard: an empty scan makes every assertion below vacuous."""
        assert len(_manifest_files()) >= 30, (
            f"Expected >=30 manifests under {K8S_ROOTS}, found {len(_manifest_files())}. "
            "If the tree was genuinely restructured, lower this bound deliberately."
        )

    def test_every_manifest_has_a_path_to_the_cluster(self) -> None:
        referenced = _kustomization_referenced() | _cluster_bootstrap_manifests()
        allowed = {(REPO_ROOT / p).resolve() for p in OUT_OF_BAND}

        orphans = [
            str(path.relative_to(REPO_ROOT))
            for path in _manifest_files()
            if path.resolve() not in referenced and path.resolve() not in allowed
        ]

        assert not orphans, (
            "These manifests are applied by nothing -- not a kustomization, not "
            "cluster_bootstrap, not OUT_OF_BAND:\n  "
            + "\n  ".join(orphans)
            + "\n\nA manifest in this state is correct in git and absent from the "
            "cluster, with no signal that anything is wrong (kubelab#970). Either "
            "register it, or add it to OUT_OF_BAND with the command that applies it."
        )

    def test_out_of_band_list_has_no_stale_entries(self) -> None:
        """An entry that became Kustomize-managed must leave this list.

        Otherwise the list slowly becomes a description of the past -- the exact
        failure mode of the `tls: {}` comment and the stale `deploy-k8s` ordering
        note in the operations runbook.
        """
        referenced = _kustomization_referenced() | _cluster_bootstrap_manifests()
        stale = [p for p in OUT_OF_BAND if (REPO_ROOT / p).resolve() in referenced]
        assert not stale, (
            f"OUT_OF_BAND entries that ARE now applied by Kustomize/cluster_bootstrap: {stale}. "
            "Remove them -- a stale exemption hides a real orphan behind it."
        )

    def test_out_of_band_entries_exist_on_disk(self) -> None:
        missing = [p for p in OUT_OF_BAND if not (REPO_ROOT / p).exists()]
        assert not missing, f"OUT_OF_BAND names files that do not exist: {missing}"

    def test_every_out_of_band_trigger_exists(self) -> None:
        """Each declared trigger must be a real Makefile target.

        This is what makes `OUT_OF_BAND` a checked claim instead of a comment
        that rots. Matching a *declaration* (`^<name>:`) rather than any mention
        of the name is deliberate: the prose above and in the Makefile itself
        says things like "applied by `make deploy-argocd`", so a substring test
        would stay green for a target that no longer exists. This session
        produced that exact case -- a `deploy-argocd-route` target was written,
        allowlisted, and then deleted when the manifest was split.

        A trigger must be a Make target, not a bare toolkit invocation, even
        though TOOL-009 T4 phrased this category as "a small toolkit command
        each". The Makefile is the interface the rest of the repo is operated
        through; requiring the wrapper keeps these manifests discoverable in
        `make help` instead of only in a test file.
        """
        text = MAKEFILE.read_text(encoding="utf-8")
        undeclared = sorted(
            {
                entry.trigger
                for entry in OUT_OF_BAND.values()
                if not re.search(rf"^{re.escape(entry.trigger)}:", text, re.MULTILINE)
            }
        )
        assert not undeclared, (
            f"OUT_OF_BAND names triggers with no Makefile target: {undeclared}. "
            "Either the target was renamed or removed (update OUT_OF_BAND), or the "
            "manifest now has no way to reach the cluster at all."
        )


class TestRenderKeysMatchTheirManifests:
    """Every `--render KEY=host` in the Makefile must name a placeholder that the
    manifest it is applied to actually contains.

    Raised in review of #1308. The rename it carried out (`RESOLVE_AWS1_*` ->
    `RESOLVE_GCP1_*`) touches two files that must agree character for character,
    and nothing checked that they did -- `test_orphan_manifests` mentions the
    placeholder only inside a prose `reason` field, which asserts nothing.

    What a mismatch would do is the reason this is not cosmetic. `render_text` is
    fail-CLOSED and raises on an unmapped placeholder, but `render_and_apply`
    converts that to a warning and returns SUCCESS when the entry is `optional`
    (`k8s_render.py:155-157`). The Makefile passed `--optional` here until this
    change, so a typo produced:

        ✓ Argo CD deployed with OIDC

    with prod's EndpointSlice still holding the PREVIOUS hub's address. Mid-hub-
    migration that reads as "prod silently keeps routing to the hub you are
    decommissioning".

    Both halves are fixed: `--optional` is gone from the hub's entry, and this
    test removes the typo class entirely rather than relying on the flag.
    """

    def _render_invocations(self) -> list[tuple[str, str]]:
        """(manifest_path, placeholder) for each render-apply in the Makefile."""
        import re

        text = (REPO_ROOT / "Makefile").read_text()
        # A recipe may wrap across escaped newlines; join them before matching.
        joined = text.replace("\\\n", " ")
        out = []
        for line in joined.splitlines():
            if "render-apply" not in line:
                continue
            manifest = re.search(r"--manifest\s+(\S+)", line)
            for placeholder in re.findall(r"--render\s+(RESOLVE_[A-Z0-9_]+)=", line):
                assert manifest, f"render-apply with --render but no --manifest: {line.strip()}"
                out.append((manifest.group(1), placeholder))
        return out

    def test_every_render_key_appears_in_its_manifest(self) -> None:
        invocations = self._render_invocations()
        assert invocations, "no render-apply invocation found; this test is watching nothing"
        for manifest, placeholder in invocations:
            path = REPO_ROOT / manifest
            assert path.exists(), f"--manifest {manifest} does not exist"
            assert placeholder in path.read_text(), (
                f"Makefile renders {placeholder} into {manifest}, which does not contain it. "
                "The substitution would not happen, and the manifest would keep whatever "
                "address it was last applied with -- reported as success if the entry is "
                "--optional."
            )

    def test_every_placeholder_in_those_manifests_is_rendered(self) -> None:
        # The other direction: a placeholder nobody renders is applied literally.
        import re

        by_manifest: dict[str, set[str]] = {}
        for manifest, placeholder in self._render_invocations():
            by_manifest.setdefault(manifest, set()).add(placeholder)
        for manifest, rendered in by_manifest.items():
            present = set(re.findall(r"RESOLVE_[A-Z0-9_]+", (REPO_ROOT / manifest).read_text()))
            missing = present - rendered
            assert not missing, (
                f"{manifest} contains {sorted(missing)} which no --render maps. "
                "render_text raises on this, and --optional would downgrade the raise to a "
                "warning reported as success."
            )
