"""ADR028-004: every stateful service must declare where its state may live.

Nine stateful PVCs shipped in both staging and prod for no decided reason: they
sit in `infra/k8s/base/`, both overlays inherit base, and so a topology decision
was made as a side effect of a packaging choice. This gate turns the resulting
classification from ADR prose into something enforced.

Two INDEPENDENT axes, declared per service in `common.yaml`:

  state_promotion  dual      — state has a promotion path in git, so a second
                               instance is reconstructable rather than forked.
                   singleton — no promotion path; a second live instance would
                               fork state that cannot be merged back.
  location         always-on | on-demand  — ADR-028's "would I need this at
                               3 AM?" test.
                   undecided — a RECORDED deferral, which must name its ticket.

"prod" is an environment, not a location: neither axis implies the other.

Mirrors `tests/test_spoke_rbac_covers_manifests.py` (TOOL-029) deliberately —
that test already solved this exact shape: discover shipped resources from
manifest files with no cluster available, cross-reference against a declared
SSOT, fail loudly and specifically, and never silently skip. The homelab is
on-demand, so like its precedent this needs nothing running to be meaningful.

Ground truth is the manifests, not a hand-kept list: a service that gains a PVC
is classified or this test fails. The reverse direction — a classification with
no PVC — is deliberately NOT an error, because PRs 3 and 4 of this spec retire
gitea's staging twin while its classification stays meaningful.
"""

from __future__ import annotations

import copy
import os
import pathlib
import re
import shutil
import subprocess
from typing import Any

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMON_VALUES = REPO_ROOT / "infra/config/values/common.yaml"

#: Both roots, not `base` alone. No overlay ships a PVC today, so this is a
#: superset — but PRs 3/4 move gitea's resources into
#: `overlays/prod/`, and scanning base alone would let them drop out of this
#: gate's field of view at exactly the moment their placement starts to matter.
MANIFEST_ROOTS = ("infra/k8s/base", "infra/k8s/overlays")

#: Gitignored audit copies of SOPS-rendered middlewares (ADR-035 Stage 1).
SKIPPED_PATH_PARTS = frozenset({".rendered"})

#: The declared vocabulary. Membership is checked, not just presence: a typo
#: like `singelton` passing a presence-only check is precisely the vacuous-gate
#: failure this spec's R4 was written to prevent ("a test that cannot be shown
#: to fail is not a gate").
STATE_PROMOTION_VALUES = frozenset({"dual", "singleton"})
LOCATION_VALUES = frozenset({"always-on", "on-demand", "undecided"})

#: `undecided` is a recorded decision, never a blank. A service claiming it must
#: also carry `location_deferred_to` naming the ticket that owns the decision,
#: so the sentinel cannot quietly become the dodge for every future service.
DEFERRAL_KEY = "location_deferred_to"

#: And the deferral must be a *ticket*, not a mood. A truthiness check would
#: accept `location_deferred_to: later`, which records nothing anyone can chase
#: — the sentinel would be back to meaning "we didn't decide", which is exactly
#: what ADR-061 D4 says it must never mean.
TICKET_REFERENCE = re.compile(r"^#\d+$")


def _iter_manifests() -> list[pathlib.Path]:
    """Every manifest file under the scanned roots, audit copies excluded."""
    files: list[pathlib.Path] = []
    for root in MANIFEST_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.yaml")):
            if SKIPPED_PATH_PARTS & set(path.parts):
                continue
            files.append(path)
    return files


def _stateful_services() -> dict[str, list[str]]:
    """Map owning service -> its PVC names, discovered from the manifests.

    The owning service is the file stem: `services/crowdsec.yaml` owns both
    `crowdsec-db` and `crowdsec-config`. Deriving it from the PVC's own name
    would be wrong — `crowdsec-db` would resolve to a `crowdsec-db` service that
    does not exist, and the two PVCs would split into two phantom services.
    """
    owned: dict[str, list[str]] = {}
    for path in _iter_manifests():
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError as exc:  # pragma: no cover - malformed manifest
            pytest.fail(f"{path.relative_to(REPO_ROOT)} is not parseable YAML: {exc}")
        for doc in docs:
            # Kustomize patch files hold bare lists; only mappings are resources.
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") != "PersistentVolumeClaim":
                continue
            name = (doc.get("metadata") or {}).get("name")
            if name:
                owned.setdefault(path.stem, []).append(name)
    return owned


def _service_block(config: dict[str, Any], service: str) -> dict[str, Any] | None:
    """Resolve a service's config block from wherever it actually lives.

    Seven of the eight classified services sit under
    `apps.services.<category>.<name>`. The eighth, `postgres`, is at
    `infra.postgres` — deliberately, per ADR-051, the same shared-multi-consumer
    pattern ADR-036 established for SMTP. Walking `apps.services.*` alone would
    silently under-cover it, so both trees are searched (R4).
    """
    categories = (config.get("apps") or {}).get("services") or {}
    for block in categories.values():
        if isinstance(block, dict) and isinstance(block.get(service), dict):
            return block[service]
    shared = (config.get("infra") or {}).get(service)
    return shared if isinstance(shared, dict) else None


def _promotion_problems(block: dict[str, Any]) -> list[str]:
    promotion = block.get("state_promotion")
    if promotion is None:
        return ["missing `state_promotion`"]
    if promotion not in STATE_PROMOTION_VALUES:
        return [f"`state_promotion: {promotion}` is not one of {sorted(STATE_PROMOTION_VALUES)}"]
    return []


def _deferral_problems(block: dict[str, Any]) -> list[str]:
    deferral = block.get(DEFERRAL_KEY)
    if not deferral:
        return [
            f"`location: undecided` without `{DEFERRAL_KEY}` — a deferral must name the ticket that owns the decision"
        ]
    if not (isinstance(deferral, str) and TICKET_REFERENCE.fullmatch(deferral)):
        return [
            f"`{DEFERRAL_KEY}: {deferral!r}` is not a ticket "
            "reference (expected the form `#972`) — a deferral nobody "
            "can chase is not a recorded decision"
        ]
    return []


def _location_problems(block: dict[str, Any]) -> list[str]:
    location = block.get("location")
    if location is None:
        return ["missing `location`"]
    if location not in LOCATION_VALUES:
        return [f"`location: {location}` is not one of {sorted(LOCATION_VALUES)}"]
    if location == "undecided":
        return _deferral_problems(block)
    return []


def classification_problems(services: dict[str, list[str]], config: dict[str, Any]) -> list[str]:
    """Return one human-readable problem per violation; empty means compliant.

    Pure over its two arguments so the negative controls below can feed it a
    synthetic fixture instead of mutating the real repo.
    """
    problems: list[str] = []
    for service, pvcs in sorted(services.items()):
        where = f"{service} (PVCs: {', '.join(sorted(pvcs))})"
        block = _service_block(config, service)
        if block is None:
            problems.append(f"{where}: no config block found in common.yaml")
            continue
        problems += [f"{where}: {p}" for p in _promotion_problems(block) + _location_problems(block)]
    return problems


@pytest.fixture(scope="module")
def common_config() -> dict[str, Any]:
    return yaml.safe_load(COMMON_VALUES.read_text())


def test_manifests_actually_yield_stateful_services() -> None:
    """Guard the discovery step itself.

    If `_stateful_services()` ever returns nothing — a moved directory, a
    renamed kind — every assertion below would pass vacuously while checking
    nothing at all. Two vacuous controls shipped on a single day during OBS-007;
    this is the cheap insurance against a third.
    """
    assert _stateful_services(), (
        f"no PersistentVolumeClaim found under {MANIFEST_ROOTS} — the discovery "
        "step is broken, so the classification gate would pass vacuously"
    )


def test_every_stateful_service_declares_a_classification(
    common_config: dict[str, Any],
) -> None:
    """The gate itself, run against the real repo."""
    problems = classification_problems(_stateful_services(), common_config)
    assert not problems, "Stateful services with an incomplete classification:\n" + "\n".join(
        f"  - {p}" for p in problems
    )


# --------------------------------------------------------------------------
# Negative controls. AC2 requires demonstrating the failure, not just a green
# main test: "A passing test alone does not satisfy this criterion."
# --------------------------------------------------------------------------

#: Minimal synthetic config — in-memory, never the live repo state, so these
#: controls cannot pass by accident if the real classification regresses.
_FIXTURE_SERVICES = {"widget": ["widget-data"]}


def _fixture_config(**overrides: Any) -> dict[str, Any]:
    block = {"name": "widget", "state_promotion": "dual", "location": "always-on"}
    block.update(overrides)
    return {"apps": {"services": {"demo": {"widget": block}}}}


def test_fixture_baseline_is_compliant() -> None:
    """The fixture must be clean, or the controls below prove nothing."""
    assert classification_problems(_FIXTURE_SERVICES, _fixture_config()) == []


@pytest.mark.parametrize(
    ("overrides", "expected_fragment"),
    [
        ({"state_promotion": None}, "missing `state_promotion`"),
        ({"location": None}, "missing `location`"),
        ({"state_promotion": "singelton"}, "is not one of"),
        ({"location": "beelink"}, "is not one of"),
        ({"location": "undecided"}, DEFERRAL_KEY),
        # A deferral has to be chaseable. These three are the shapes that read
        # as "recorded" and are not: a mood, a bare number, and a prose excuse.
        ({"location": "undecided", DEFERRAL_KEY: "later"}, "not a ticket reference"),
        ({"location": "undecided", DEFERRAL_KEY: "972"}, "not a ticket reference"),
        (
            {"location": "undecided", DEFERRAL_KEY: "see the backlog"},
            "not a ticket reference",
        ),
    ],
)
def test_gate_goes_red_on_each_violation(overrides: dict[str, Any], expected_fragment: str) -> None:
    """Every branch of the check must be demonstrably reachable."""
    config = _fixture_config()
    block = config["apps"]["services"]["demo"]["widget"]
    for key, value in overrides.items():
        if value is None:
            block.pop(key, None)
        else:
            block[key] = value

    problems = classification_problems(_FIXTURE_SERVICES, config)
    assert problems, f"gate stayed green on {overrides}"
    assert any(expected_fragment in p for p in problems), problems


def test_gate_goes_red_when_the_service_has_no_config_block() -> None:
    """A PVC whose service was never declared at all is the headline case."""
    problems = classification_problems({"ghost": ["ghost-data"]}, _fixture_config())
    assert any("no config block found" in p for p in problems), problems


def test_undecided_location_is_accepted_when_its_deferral_is_recorded() -> None:
    """`undecided` is legal — it is a decision, provided it names its ticket."""
    config = _fixture_config(location="undecided", **{DEFERRAL_KEY: "#972"})
    assert classification_problems(_FIXTURE_SERVICES, config) == []


# --------------------------------------------------------------------------
# The duplication clause (AC2, second half). Classification alone does not stop
# a `singleton` from rendering in both environments, which is the fork ADR-061
# exists to prevent. It could not land while two singletons' twins still
# rendered in both overlays; both have since left K3s (gitea to the Beelink,
# the object store retired by OPS-023), so the clause goes green on master.
# --------------------------------------------------------------------------

OVERLAYS = ("staging", "prod")


def duplication_problems(
    services: dict[str, list[str]], config: dict[str, Any], rendered: dict[str, set[str]]
) -> list[str]:
    """One problem per `singleton` service whose PVCs render in more than one overlay.

    `rendered` maps overlay -> the PVC names it renders. Pure, like
    `classification_problems`, so the controls below need no cluster and no kubectl.

    Scope: state held in a PersistentVolumeClaim of these manifests, the same set the
    classification half scans. A StatefulSet's `volumeClaimTemplates` is outside it
    (#2062); state kept outside K8s (an external database, a node's disk) has no
    overlay to be duplicated across.
    """
    problems = []
    for service, pvcs in sorted(services.items()):
        block = _service_block(config, service) or {}
        if block.get("state_promotion") != "singleton":
            continue
        envs = sorted(env for env, names in rendered.items() if set(pvcs) & names)
        if len(envs) > 1:
            problems.append(
                f"{service} is `state_promotion: singleton` but its PVCs render in {envs}: "
                "a second live instance forks state that has no promotion path"
            )
    return problems


@pytest.fixture(scope="module")
def rendered_pvcs() -> dict[str, set[str]]:
    if shutil.which("kubectl") is None:
        # This file promises never to skip silently; in CI a missing binary is a failure.
        if os.environ.get("CI"):
            pytest.fail("kubectl not on PATH in CI: the duplication clause cannot run")
        pytest.skip("kubectl not on PATH: the duplication clause was NOT checked")
    rendered = {}
    for env in OVERLAYS:
        out = subprocess.run(
            ["kubectl", "kustomize", str(REPO_ROOT / "infra/k8s/overlays" / env)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        rendered[env] = {
            d["metadata"]["name"]
            for d in yaml.safe_load_all(out)
            if isinstance(d, dict) and d.get("kind") == "PersistentVolumeClaim"
        }
    return rendered


def test_both_overlays_render_claims(rendered_pvcs: dict[str, set[str]]) -> None:
    """An empty render would let the clause pass on nothing (lesson-416)."""
    assert all(rendered_pvcs[env] for env in OVERLAYS), rendered_pvcs


def test_rendered_claims_carry_their_manifest_names(rendered_pvcs: dict[str, set[str]]) -> None:
    """The clause intersects manifest PVC names with rendered ones. A `namePrefix` or a
    rename in an overlay would make that intersection empty, and the clause green forever."""
    declared = {name for pvcs in _stateful_services().values() for name in pvcs}
    for env in OVERLAYS:
        assert rendered_pvcs[env] <= declared, (
            f"{env} renders PVCs no manifest declares: {rendered_pvcs[env] - declared}"
        )


def test_no_singleton_renders_in_both_overlays(
    common_config: dict[str, Any], rendered_pvcs: dict[str, set[str]]
) -> None:
    problems = duplication_problems(_stateful_services(), common_config, rendered_pvcs)
    assert not problems, "\n".join(problems)


def test_duplication_clause_goes_red_on_the_real_render(
    common_config: dict[str, Any], rendered_pvcs: dict[str, set[str]]
) -> None:
    """No singleton renders today, which is the state ADR-061 asks for, so the green test
    above never reaches the intersection on real data. This one does: postgres renders in
    both overlays, and declared `singleton` it must fail."""
    config = copy.deepcopy(common_config)
    config["infra"]["postgres"]["state_promotion"] = "singleton"
    problems = duplication_problems(_stateful_services(), config, rendered_pvcs)
    assert [p.split(" is ", 1)[0] for p in problems] == ["postgres"], problems


def test_duplication_clause_goes_red_on_a_singleton_in_both_overlays() -> None:
    config = _fixture_config(state_promotion="singleton")
    both = {"staging": {"widget-data"}, "prod": {"widget-data"}}
    assert duplication_problems(_FIXTURE_SERVICES, config, both) == [
        "widget is `state_promotion: singleton` but its PVCs render in ['prod', 'staging']: "
        "a second live instance forks state that has no promotion path"
    ]


@pytest.mark.parametrize(
    ("promotion", "rendered"),
    [
        ("singleton", {"staging": set(), "prod": {"widget-data"}}),
        ("dual", {"staging": {"widget-data"}, "prod": {"widget-data"}}),
    ],
)
def test_duplication_clause_accepts_one_overlay_or_a_dual_service(
    promotion: str, rendered: dict[str, set[str]]
) -> None:
    config = _fixture_config(state_promotion=promotion)
    assert duplication_problems(_FIXTURE_SERVICES, config, rendered) == []
