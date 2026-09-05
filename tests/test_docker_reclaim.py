"""OPS-024 (#1657) — what the reclaim removes, and what it must never reach.

The fixture below is TRANSCRIBED from the Beelink on 2026-09-05, not invented.
That matters more here than usual, because the finding this module exists for is
only visible in real data: `docker ps` reported every one of these builders as
"Up 3 hours", while `Created` puts four of them between 71 and 104 days old.
`restart: unless-stopped` had been resurrecting them at every reboot since May.

A fixture I wrote from my own understanding would have encoded that
understanding and certified it -- the failure mode measured on this repo's
`FakeClient` in #1546, where a fake returned a `permission` field no real Gitea
emits and fourteen tests passed against a reconciler that 500'd in production.

So `test_the_fixture_is_what_it_claims` asserts the fixture's own properties
before anything reads it: builders older than the gate must exist, and at least
one must be young enough to be kept. An empty expectation is not a weak
expectation -- it matches everything (lesson 416).
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from toolkit.features.docker_reclaim import (
    BUILDER_PREFIX,
    DEFAULT_MIN_AGE_HOURS,
    RUNNER_CONTAINERS,
    Container,
    DockerUnavailableError,
    ReclaimPlan,
    ReclaimRefused,
    _checked_name,
    parse_containers,
    parse_volumes,
    plan_reclaim,
    resolve_gate,
)

# `docker inspect -f '{{.Name}}|{{.Created}}|{{.State.Running}}|{{range .Mounts}}{{.Name}},{{end}}'`
# on beelink (100.64.0.3), 2026-09-05, root filesystem at 100% / 0 bytes free.
#
# Read the dates, not the names. Two of these builders are from September; the
# other four are from May and June. Every one of them reported "Up 3 hours".
BEELINK_INSPECT = """\
/buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0|2026-09-05T02:07:38.785358367Z|true|buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0_state,
/act-runner|2026-09-04T23:37:22.424794246Z|true|act_runner_data,,,
/gitea|2026-09-04T23:37:22.353382899Z|true|,,
/github-runner|2026-09-04T23:37:22.348874074Z|true|github_runner_data,github_runner_toolcache,,
/minio|2026-09-04T23:37:22.348343338Z|true|,
/glances|2026-09-04T23:37:22.33899812Z|true|,,,
/buildx_buildkit_builder-dda5575f-66d5-482c-bb42-38ce53a2b3bf0|2026-09-04T06:14:58.243615907Z|true|buildx_buildkit_builder-dda5575f-66d5-482c-bb42-38ce53a2b3bf0_state,
/buildx_buildkit_builder-3785131b-493f-41d1-947b-f3e6aba71d830|2026-06-26T06:26:18.088036214Z|true|buildx_buildkit_builder-3785131b-493f-41d1-947b-f3e6aba71d830_state,
/buildx_buildkit_builder-bfbd55c5-0d1e-4b50-bd77-39a3ded4abd20|2026-06-20T19:01:59.3400106Z|true|buildx_buildkit_builder-bfbd55c5-0d1e-4b50-bd77-39a3ded4abd20_state,
/buildx_buildkit_builder-6598ae36-b11e-47a7-b618-d30ace67546b0|2026-06-18T06:36:07.539716429Z|true|buildx_buildkit_builder-6598ae36-b11e-47a7-b618-d30ace67546b0_state,
/buildx_buildkit_builder-42d82788-6f5f-4868-b3e4-df508133644a0|2026-05-24T03:59:36.333370821Z|true|buildx_buildkit_builder-42d82788-6f5f-4868-b3e4-df508133644a0_state,
"""

# `docker volume ls --format '{{.Name}}'`, same host and moment. Note
# `buildx_buildkit_builder-ed7ae5c5-..._state`: 1.2GB whose container is already
# gone, which no container-driven cleanup would ever find.
BEELINK_VOLUMES = """\
399a4bea9ab2b2e72c19c786bdb14899f1afb3fecfeee2a92451db63f0787720
075601ddee03f27f9ec7691263de6e5b7ef243de34065feaf03decaaa0fce68e
GITEA-ACTIONS-TASK-54_WORKFLOW-CI_JOB-build-pdf
GITEA-ACTIONS-TASK-54_WORKFLOW-CI_JOB-build-pdf-env
GITEA-ACTIONS-TASK-55_WORKFLOW-CI_JOB-audit
GITEA-ACTIONS-TASK-55_WORKFLOW-CI_JOB-audit-env
act-toolcache
act_runner_data
buildx_buildkit_builder-42d82788-6f5f-4868-b3e4-df508133644a0_state
buildx_buildkit_builder-6598ae36-b11e-47a7-b618-d30ace67546b0_state
buildx_buildkit_builder-3785131b-493f-41d1-947b-f3e6aba71d830_state
buildx_buildkit_builder-bfbd55c5-0d1e-4b50-bd77-39a3ded4abd20_state
buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0_state
buildx_buildkit_builder-dda5575f-66d5-482c-bb42-38ce53a2b3bf0_state
buildx_buildkit_builder-ed7ae5c5-b0ce-439b-a0fe-0c1a20525cb30_state
github_runner_data
github_runner_toolcache
"""

# The moment the inventory above was captured.
MEASURED_AT = datetime(2026, 9, 5, 2, 46, 0, tzinfo=timezone.utc)

# Volumes that hold state something still needs. Not used to DRIVE the plan --
# the plan derives protection from live attachments -- but asserted against its
# output, so that a future change which starts consulting a hardcoded list
# fails here rather than on the node.
MUST_SURVIVE = (
    "act_runner_data",
    "act-toolcache",
    "github_runner_data",
    "github_runner_toolcache",
)


@pytest.fixture
def containers() -> list[Container]:
    return parse_containers(BEELINK_INSPECT)


@pytest.fixture
def volumes() -> list[str]:
    return parse_volumes(BEELINK_VOLUMES)


@pytest.fixture
def plan(containers: list[Container], volumes: list[str]) -> ReclaimPlan:
    return plan_reclaim(containers, volumes, MEASURED_AT, DEFAULT_MIN_AGE_HOURS)


# --- the fixture's own properties, before anything reads it ------------------


def test_the_fixture_is_what_it_claims(containers: list[Container], volumes: list[str]) -> None:
    """Anti-vacuity floor. Every assertion below is about a partition of this
    data, and a partition of an empty set is empty and passes."""
    builders = [c for c in containers if c.name.startswith(BUILDER_PREFIX)]
    assert len(builders) == 6, "the measured host had six builder containers"

    ages = sorted(c.age(MEASURED_AT) for c in builders)
    assert ages[0] < timedelta(hours=DEFAULT_MIN_AGE_HOURS), (
        "at least one builder must be young enough to be KEPT, or the age gate is never exercised"
    )
    assert ages[-1] > timedelta(days=100), (
        "the oldest builder was created 2026-05-24 — if this drops below 100 days the "
        "fixture has been rewritten and no longer shows the leak it was captured for"
    )

    # The trap this module exists for: every one of these reported "Up 3 hours".
    assert all(c.running for c in builders)

    assert set(MUST_SURVIVE) <= set(volumes)
    assert any(v.startswith("GITEA-ACTIONS-TASK-") for v in volumes)


# --- parsing -----------------------------------------------------------------


def test_the_leading_slash_is_stripped_from_container_names(containers: list[Container]) -> None:
    assert all(not c.name.startswith("/") for c in containers)
    assert "gitea" in {c.name for c in containers}


def test_bind_mounts_contribute_no_volume_names(containers: list[Container]) -> None:
    """Gitea's data is a bind mount at /opt/gitea, so `.Name` is empty and the
    format emits bare commas. An empty string reaching the plan would match no
    volume and be dropped silently — quiet where the loud failure is removing
    the wrong thing."""
    gitea = next(c for c in containers if c.name == "gitea")
    assert gitea.volumes == ()

    minio = next(c for c in containers if c.name == "minio")
    assert minio.volumes == ()


def test_nanosecond_timestamps_parse(containers: list[Container]) -> None:
    oldest = min(containers, key=lambda c: c.created)
    assert oldest.created == datetime(2026, 5, 24, 3, 59, 36, 333370, tzinfo=timezone.utc)


def test_a_malformed_line_is_refused_rather_than_skipped() -> None:
    with pytest.raises(DockerUnavailableError, match="cannot parse container line"):
        parse_containers("/thing|2026-09-05T00:00:00Z|true")


def test_an_unparseable_creation_time_is_refused() -> None:
    with pytest.raises(DockerUnavailableError, match="creation time"):
        parse_containers("/thing|never|true|")


def test_an_empty_daemon_is_an_answer_not_a_failure() -> None:
    assert parse_containers("") == []
    assert parse_volumes("") == []


# --- what gets removed -------------------------------------------------------


def test_age_comes_from_created_not_from_uptime(plan: ReclaimPlan) -> None:
    """The whole safety argument. All six builders had been running three hours;
    five were created months or a day earlier and are reclaimable, and only the
    genuinely recent one is held back."""
    removed = {c.name for c in plan.containers}
    assert len(removed) == 5
    assert "buildx_buildkit_builder-42d82788-6f5f-4868-b3e4-df508133644a0" in removed
    assert "buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0" not in removed


def test_the_young_builder_is_kept_with_a_reason(plan: ReclaimPlan) -> None:
    kept = {c.name: why for c, why in plan.kept_containers}
    assert "buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0" in kept
    assert "mid-build" in kept["buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0"]


def test_only_builder_containers_are_candidates(plan: ReclaimPlan) -> None:
    assert all(c.name.startswith(BUILDER_PREFIX) for c in plan.containers)
    for survivor in ("gitea", "minio", "act-runner", "github-runner", "glances"):
        assert survivor not in {c.name for c in plan.containers}
        assert survivor not in {c.name for c, _ in plan.kept_containers}


def test_the_declared_multiarch_builder_is_not_a_candidate(volumes: list[str]) -> None:
    """This fleet provisions a builder called `multiarch` on purpose. It shares
    the `buildx_buildkit_` prefix and must never be reclaimed — the `builder-`
    segment is what separates an action-generated instance from a declared one."""
    managed = Container(
        name="buildx_buildkit_multiarch0",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        running=True,
        volumes=("buildx_buildkit_multiarch0_state",),
    )
    result = plan_reclaim([managed], ["buildx_buildkit_multiarch0_state"], MEASURED_AT)
    assert result.is_noop


def test_the_containerless_state_volume_is_reclaimed(plan: ReclaimPlan) -> None:
    """1.2GB whose container is already gone. Nothing that walks containers
    finds it, which is why the volume pass is driven by the volume list."""
    assert "buildx_buildkit_builder-ed7ae5c5-b0ce-439b-a0fe-0c1a20525cb30_state" in plan.volumes


def test_gitea_actions_job_volumes_are_reclaimed(plan: ReclaimPlan) -> None:
    reclaimed = [v for v in plan.volumes if v.startswith("GITEA-ACTIONS-TASK-")]
    assert len(reclaimed) == 4


# --- what must never be removed ----------------------------------------------


@pytest.mark.parametrize("name", MUST_SURVIVE)
def test_runner_state_is_never_removed(plan: ReclaimPlan, name: str) -> None:
    assert name not in plan.volumes


def test_a_volume_held_by_a_survivor_is_kept_and_said_so() -> None:
    """The safety property, isolated: protection is DERIVED from a live
    attachment, not read from a list. The volume matches the reclaimable
    pattern and is spared anyway, because something we are not removing holds
    it."""
    doomed = Container(
        name="buildx_buildkit_builder-aaaa_state_owner",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        running=False,
        volumes=(),
    )
    shared = "buildx_buildkit_builder-aaaa-bbbb_state"
    survivor = Container(
        name="something-that-stays",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        running=True,
        volumes=(shared,),
    )
    result = plan_reclaim([doomed, survivor], [shared], MEASURED_AT)

    assert shared not in result.volumes
    assert result.kept_volumes == ((shared, "still held by something-that-stays"),)


def test_an_undeclared_volume_is_never_touched(plan: ReclaimPlan) -> None:
    """The two anonymous hex volumes match no pattern. Anything this module does
    not recognise is left alone — the opposite posture from `docker volume
    prune`, whose blast radius is whatever happens not to be running."""
    assert "399a4bea9ab2b2e72c19c786bdb14899f1afb3fecfeee2a92451db63f0787720" not in plan.volumes
    assert "075601ddee03f27f9ec7691263de6e5b7ef243de34065feaf03decaaa0fce68e" not in plan.volumes


def test_a_builder_kept_for_age_keeps_its_volume(plan: ReclaimPlan) -> None:
    """The two halves have to agree. Removing the young builder's 3.5GB state
    volume while sparing the builder would break the build the gate exists to
    protect."""
    young = "buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0_state"
    assert young not in plan.volumes
    assert young in {v for v, _ in plan.kept_volumes}


# --- the gate itself ---------------------------------------------------------


def test_a_wider_gate_reclaims_the_young_builder_too(
    containers: list[Container], volumes: list[str]
) -> None:
    """An operator watching the plan can lower the gate. At zero everything
    qualifies, which is the emergency case."""
    result = plan_reclaim(containers, volumes, MEASURED_AT, min_age_hours=0)
    assert len(result.containers) == 6
    assert result.kept_containers == ()


def test_a_gate_above_every_age_reclaims_nothing(
    containers: list[Container], volumes: list[str]
) -> None:
    result = plan_reclaim(containers, volumes, MEASURED_AT, min_age_hours=24 * 365)
    assert result.containers == ()
    assert len(result.kept_containers) == 6
    # And nothing follows them: every state volume is still held.
    assert not [v for v in result.volumes if v.endswith("_state") and "ed7ae5c5" not in v]


def test_an_explicit_zero_gate_is_not_the_default() -> None:
    """`--min-age-hours 0` is the emergency lever the Makefile documents, and
    `min_age_hours or DEFAULT` silently turned it into 4 — so the one value the
    emergency needs was the one value that could not be asked for, with no
    message either way.

    Every test above passed throughout, because they all call
    `plan_reclaim(min_age_hours=0)` directly and the defect was one layer up in
    the CLI's resolution. Covered below the defect is not covered (lesson 433).
    """
    assert resolve_gate(0) == 0
    assert resolve_gate(None) == DEFAULT_MIN_AGE_HOURS
    assert resolve_gate(12) == 12


def test_make_passes_a_zero_gate_through_to_the_cli() -> None:
    """The other half of the same bug: `$(if $(MIN_AGE_HOURS),…)` is Make's
    truthiness, not the shell's, and `0` is a non-empty string there. Verified
    rather than assumed — had Make swallowed the 0, fixing only the Python would
    have left the lever just as unreachable.

    Asserted by asking Make what it would run (`-n` expands the recipe without
    executing it) rather than by matching the Makefile's text. pr-agent called
    the string match a maintenance hazard on #1665 and was right: it would have
    gone red on a reformat that changed nothing, and — worse for a guard —
    stayed green on a rewrite that expanded to something else entirely.
    """
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["make", "-n", "node-reclaim", "NODE=beelink", "MIN_AGE_HOURS=0"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--min-age-hours 0" in result.stdout

    # Anti-vacuity: unset must NOT pass the flag, or the assertion above would
    # hold for a recipe that always sends one.
    unset = subprocess.run(
        ["make", "-n", "node-reclaim", "NODE=beelink"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert unset.returncode == 0, unset.stderr
    assert "--min-age-hours" not in unset.stdout


def test_a_negative_gate_is_refused(containers: list[Container], volumes: list[str]) -> None:
    with pytest.raises(ReclaimRefused, match="negative age gate"):
        plan_reclaim(containers, volumes, MEASURED_AT, min_age_hours=-1)


def test_is_noop_reports_both_halves() -> None:
    assert ReclaimPlan().is_noop
    assert not ReclaimPlan(volumes=("x",)).is_noop
    assert not ReclaimPlan(
        containers=(Container("c", datetime(2025, 1, 1, tzinfo=timezone.utc), False, ()),)
    ).is_noop


# --- remote command construction ---------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    ["a; rm -rf /", "$(id)", "`id`", "a b", "--force", "", "a|b", "a&b", "*"],
)
def test_a_name_that_could_change_a_remote_command_is_refused(hostile: str) -> None:
    """These names come from Docker's own output, so this asserts an invariant
    rather than sanitising input. The day the parse loosens, this is the line
    that fails instead of the line that builds `docker rm -f $(anything)`."""
    with pytest.raises(ReclaimRefused, match="refusing to build a remote command"):
        _checked_name(hostile)


def test_every_real_name_survives_the_check(containers: list[Container], volumes: list[str]) -> None:
    """Anti-vacuity for the check above: a validator that rejected everything
    would pass every hostile case and be useless."""
    for container in containers:
        assert _checked_name(container.name) == container.name
    for volume in volumes:
        assert _checked_name(volume) == volume


def test_containers_are_removed_before_the_volumes_they_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Docker refuses to remove an attached volume, so a volume pass that runs
    first fails on every volume that matters — which is all of them, since a
    volume worth reclaiming is one a builder is holding.

    Found by mutation: flipping the two loops left all 35 other tests green.
    The order was stated in a docstring and asserted nowhere, the same shape as
    lesson 433 — correctness that reads as obvious is exactly what nobody writes
    a test for.
    """
    calls: list[str] = []
    monkeypatch.setattr(
        "toolkit.features.docker_reclaim._ssh",
        lambda target, command, **kw: calls.append(command) or "",
    )

    from toolkit.features.docker_reclaim import remove

    builder = Container(
        name="buildx_buildkit_builder-aaaa-bbbb",
        created=datetime(2025, 1, 1, tzinfo=timezone.utc),
        running=True,
        volumes=("buildx_buildkit_builder-aaaa-bbbb_state",),
    )
    remove(
        "user@host",
        ReclaimPlan(containers=(builder,), volumes=("buildx_buildkit_builder-aaaa-bbbb_state",)),
    )

    assert calls == [
        "docker rm -f buildx_buildkit_builder-aaaa-bbbb",
        "docker volume rm buildx_buildkit_builder-aaaa-bbbb_state",
    ]


def test_both_runners_on_this_node_are_paused() -> None:
    """A node with one runner must not mask a failure to stop the other. Naming
    them here means adding a third runner without adding it to the pause list
    fails a test rather than filling a disk."""
    assert set(RUNNER_CONTAINERS) == {"act-runner", "github-runner"}
