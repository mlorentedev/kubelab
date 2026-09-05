"""TOOL-035 AC7: the Gitea Actions runner is declared, labelled and gated.

Three properties, each with a measured reason for existing rather than a general
principle.

**1. The registration mint must be gated on the SOPS key being absent.** From Gitea's
`models/actions/runner_token.go`, a registration token "reuses the latest active token
or creates a new one, **invalidating all prior tokens for the same scope**". So minting
is not idempotent, and worse than merely noisy: re-provisioning the node would revoke
the token the running runner registered with and silently deregister it. The bot and
admin token mints on this node already carry exactly this gate for the same reason.

**2. `ubuntu-latest` does not exist in Gitea.** GitHub's hosted label is a fiction on a
self-hosted forge; act_runner resolves `runs-on` against its own declared labels. A
migrated workflow saying `runs-on: ubuntu-latest` matches nothing, and a job that
matches no runner sits **queued forever** — it does not fail. That is the fails-open
shape AC6 names, so the mapping is asserted here rather than discovered by a pipeline
that never starts.

**3. Resource limits, per ADR-030.** The Beelink is an 8 GB on-demand node also running
Gitea, MinIO and the GitHub runner. An unbounded CI container is the one workload here
that can evict the forge it builds for.

These read the rendered template, not the role's prose. The file explains its own
reasoning at length, and scanning the whole text for a token matches the explanation
whether or not the directive is present — a false green this repository has hit
repeatedly, including in the test next door.
"""

from __future__ import annotations

import re

import yaml
from tests.ansible_jinja import ansible_env
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tests.test_beelink_compose_unit import REPO, ROLE

COMPOSE_TEMPLATE = "compose.yml.j2"

#: The service name the rest of this file asserts against.
RUNNER_SERVICE = "act-runner"

#: Gitea resolves `runs-on` against the runner's declared labels. This is the label a
#: migrated GitHub workflow will ask for.
GITHUB_HOSTED_LABEL = "ubuntu-latest"


def _ssot() -> dict:
    """The runner's declaration, read once and shared by both renderers."""
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    return common["apps"]["services"]["automation"]["gitea_runner"]


def _render_with(env, runner: dict) -> dict:
    """Render the compose template with an explicit runner declaration.

    Takes the whole declaration rather than a flag so a future field is exercised by
    the branch tests too, instead of silently defaulting.
    """
    return yaml.safe_load(env.get_template(COMPOSE_TEMPLATE).render(**_template_vars(runner)))


def _template_vars(runner: dict) -> dict:
    """Every variable the Beelink compose template needs, for one runner declaration.

    Runner values come from the passed declaration rather than from the SSOT read
    directly, so the enabled/disabled branch tests can vary one field without
    duplicating this list — and so a field added later is exercised by both branches
    instead of silently defaulting in one.
    """
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    gitea = common["apps"]["services"]["core"]["gitea"]
    return dict(

            ansible_managed="Ansible managed",
            restart_policy="unless-stopped",
            beelink_deploy_dir="/opt/kubelab",
            beelink_gitea_data_dir="/opt/gitea/data",
            beelink_runner_work_dir="/opt/runner/_work",
            tailscale_ip=common["networking"]["nodes"]["beelink"]["tailscale_ip"],
            gitea_image=gitea["image"],
            gitea_domain=gitea["domain"],
            gitea_ssh_host=gitea["domain"],
            gitea_ssh_port=2222,
            gitea_http_port=3000,
            gitea_bot_user="hefesto",
            gitea_bot_email="bot@example.com",
            gitea_admin_user="manu",
            gitea_admin_email="ops@example.com",
            gitea_admin_password="x",
            gitea_secret_key="x",
            gitea_oidc_client_secret="x",
            gitea_lfs_jwt_secret="x",
            gitea_internal_token="x",
            gitea_health_path=gitea["health_path"],
            gitea_oidc_discovery_url="https://auth.kubelab.live/.well-known/openid-configuration",
            gitea_cpu_limit=gitea["resources"]["cpu_limit"],
            gitea_memory_limit=gitea["resources"]["memory_limit"],
            beelink_minio_data_dir="/opt/minio/data",
            minio_image="minio/minio",
            minio_api_port=9000,
            minio_console_port=9001,
            minio_root_user="x",
            minio_root_password="x",
            minio_data_dir="/opt/minio/data",
            minio_cpu_limit="1",
            minio_memory_limit="1G",
            runner_image="myoung34/github-runner",
            runner_repo_url="https://github.com/mlorentedev/kubelab",
            runner_access_token="x",
            runner_group="default",
            runner_labels="self-hosted,linux,docker",
            runner_cpu_limit="2",
            runner_memory_limit="2G",
            # From the SSOT rather than literals: the label mapping is the thing
            # under test, so a copy here would assert the test against itself.
            act_runner_enabled=runner["enabled"],
            act_runner_name=runner["name"],
            act_runner_runner_name=runner["runner_name"],
            act_runner_image=runner["image"],
            act_runner_token="x",
            act_runner_cpu_limit=runner["resources"]["cpu_limit"],
            act_runner_memory_limit=runner["resources"]["memory_limit"],
            act_runner_labels=runner["labels"],
            act_runner_log_retention_days=runner["log_retention_days"],
            act_runner_artifact_retention_days=runner["artifact_retention_days"],
            act_runner_run_retention_days=runner["run_retention_days"],
            docker_dns_servers=["100.100.100.100", "1.1.1.1"],

    )


def _render() -> dict:
    """Render the Beelink compose template with the declaration as committed."""
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    return yaml.safe_load(env.get_template(COMPOSE_TEMPLATE).render(**_template_vars(_ssot())))


def _runner() -> dict:
    services = _render()["services"]
    assert RUNNER_SERVICE in services, (
        f"the compose template emits no `{RUNNER_SERVICE}` service. Gitea Actions is "
        "already enabled on the instance and on both migrated repositories "
        "(`has_actions=True`, `/actions/tasks` -> 200), so the runner is the only "
        "missing piece — and a workflow with no runner QUEUES rather than failing."
    )
    return services[RUNNER_SERVICE]


def _config() -> dict:
    """The rendered act_runner config.yaml, parsed."""
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    runner = _ssot()
    return yaml.safe_load(
        env.get_template("act-runner-config.yaml.j2").render(
            ansible_managed="Ansible managed",
            act_runner_capacity=runner["capacity"],
            act_runner_labels=runner["labels"],
            act_runner_container_options=runner["container_options"],
        )
    )


def test_the_runner_advertises_the_github_hosted_label() -> None:
    """A migrated workflow says `runs-on: ubuntu-latest`, which Gitea does not define.

    Gitea has no hosted runners, so the label is only ever what act_runner declares.
    Without the mapping, `runs-on: ubuntu-latest` matches no runner and the job waits
    indefinitely — no error, no failed check, nothing to notice.
    """
    labels = _config()["runner"]["labels"]

    assert any(str(label).startswith(f"{GITHUB_HOSTED_LABEL}:") for label in labels), (
        f"no label maps `{GITHUB_HOSTED_LABEL}` to an image; got {labels}. Every "
        "workflow migrated from GitHub asks for it, and a job matching no runner is "
        "queued forever rather than reported as failed."
    )


#: Physical RAM on the Beelink, measured 2026-09-03 (`free -m` reports 7716 MB of
#: 8 GB). Not read from a config file because no SSOT declares the node's hardware,
#: and inventing one to satisfy a test would be worse than a documented constant.
BEELINK_TOTAL_MB = 7716

#: What must remain for the OS, page cache, and the ~450 MB the service stack uses
#: at rest (gitea 131M, minio 135M, glances 108M, github-runner 61M -- measured, not
#: their declared ceilings, which reserve nothing).
RESERVED_MB = 1800


def _budget_mb() -> float:
    """The memory a configuration commits: every job container, plus the daemon.

    Extracted so the term the budget check adds can be shown to CHANGE AN ANSWER at
    a reachable configuration, rather than merely being present in a sum.
    """
    runner = _ssot()
    per_job = re.search(r"--memory=(\d+(?:\.\d+)?)([gGmM])", str(runner["container_options"]))
    daemon = re.search(r"(\d+(?:\.\d+)?)\s*([gGmM])", str(runner["resources"]["memory_limit"]))
    assert per_job and daemon

    def to_mb(m: re.Match[str]) -> float:
        return float(m.group(1)) * (1024 if m.group(2).lower() == "g" else 1)

    return int(runner["capacity"]) * to_mb(per_job) + to_mb(daemon)


def test_the_daemon_s_own_ceiling_can_decide_the_budget() -> None:
    """Counting act_runner itself is not decoration, and this pins it at a REAL configuration.

    Mutation-tested 2026-09-04: dropping the daemon term from the budget left the
    suite green, because at today's numbers (capacity 2, 2G per job, 1G daemon) the
    answer is "fits" either way. A term that never changes an answer is a term
    nobody would notice losing -- which is exactly how the daemon's old 512M went
    unmodelled until it was measured sitting ON that limit.

    So the term is pinned where it decides: 1.6G per job at capacity 3 fits WITHOUT
    it and does not fit WITH it. Not a contrived number -- it is the shape of the
    change this repository is actively considering, since `build-pdf` peaked at
    479M against a 2G allowance and the obvious move is to lower the per-job limit
    and raise capacity together.
    """
    budget = BEELINK_TOTAL_MB - RESERVED_MB
    per_job_mb, capacity, daemon_mb = 1.6 * 1024, 3, 1024

    without_daemon = capacity * per_job_mb
    with_daemon = without_daemon + daemon_mb

    assert without_daemon <= budget, "the fixture no longer models a config that passes without the term"
    assert with_daemon > budget, "the fixture no longer models a config the term rejects"


def test_the_committed_total_counts_both_kinds_of_container() -> None:
    """The live configuration's committed memory includes the daemon's ceiling.

    Asserted on the DERIVED total rather than by reading the sum, so a refactor that
    drops the term fails here even on a day when the budget assertion would still
    pass without it.
    """
    runner = _ssot()
    daemon = re.search(r"(\d+(?:\.\d+)?)\s*([gGmM])", str(runner["resources"]["memory_limit"]))
    per_job = re.search(r"--memory=(\d+(?:\.\d+)?)([gGmM])", str(runner["container_options"]))
    assert daemon and per_job
    daemon_mb = float(daemon.group(1)) * (1024 if daemon.group(2).lower() == "g" else 1)
    per_job_mb = float(per_job.group(1)) * (1024 if per_job.group(2).lower() == "g" else 1)

    assert _budget_mb() == int(runner["capacity"]) * per_job_mb + daemon_mb
    assert daemon_mb > 0, "the daemon contributes nothing; the term is present but empty"


def test_concurrent_jobs_fit_in_the_node_s_memory() -> None:
    """capacity x per-job memory must fit, whatever those two numbers become.

    Pinning `capacity == 1` would have been the wrong assertion: it fixes a value
    rather than the property that makes the value safe, and it goes red on a change
    that is perfectly correct -- which is how a test gets loosened instead of read.

    The property is arithmetic. **CPU can be oversubscribed safely and memory cannot**:
    too many CPU shares only throttles, while too much committed memory invokes the
    OOM killer on a node that also hosts the forge these jobs build for. So this
    checks memory, and lets CPU be a judgement call.

    WHAT THIS ARITHMETIC CANNOT SEE, stated here because a green result on it was
    read as "the node is safe" and that is a stronger claim than it makes. Measured
    on the Beelink 2026-09-04, peak RSS while four pull requests ran:

        buildkit builder   4095M   no limit    <- larger than everything below
        (unnamed)          1968M   no limit
        job:build-pdf       479M   2G limit    <- what this test models, at 23%

    Every container a job starts through the mounted Docker socket is created by
    the daemon on the HOST -- a sibling, outside the job's cgroup, inheriting no
    limit. Those containers are declared in a workflow in another repository, so
    nothing here can count them. This test therefore bounds the containers act_runner
    itself creates, and says nothing about the ones they create in turn. Keeping the
    limitation written down is the difference between a guard and a false assurance.
    """
    runner = _ssot()
    capacity = int(runner["capacity"])
    options = str(runner["container_options"])

    match = re.search(r"--memory=(\d+(?:\.\d+)?)([gGmM])", options)
    assert match, (
        f"container_options declares no parseable --memory: {options!r}. Without it "
        "the job container is unbounded and this arithmetic is vacuous."
    )
    per_job_mb = float(match.group(1)) * (1024 if match.group(2).lower() == "g" else 1)

    # THE DAEMON'S OWN CEILING COUNTS. It was omitted while it was 512M, which was
    # small enough for the omission not to matter and is exactly why it went
    # unnoticed -- the number moved to 1G when act_runner was measured sitting ON
    # its old limit, and an unmodelled term that grows is one that changes the
    # answer without changing the test.
    runner_match = re.search(r"(\d+(?:\.\d+)?)\s*([gGmM])", str(runner["resources"]["memory_limit"]))
    assert runner_match, (
        f"the runner's own memory_limit is unparseable: {runner['resources']['memory_limit']!r}. "
        "It is a term in this budget, not decoration."
    )
    daemon_mb = float(runner_match.group(1)) * (1024 if runner_match.group(2).lower() == "g" else 1)

    committed = capacity * per_job_mb + daemon_mb
    budget = BEELINK_TOTAL_MB - RESERVED_MB

    assert committed <= budget, (
        f"{capacity} concurrent jobs x {per_job_mb:.0f} MB + {daemon_mb:.0f} MB for act_runner "
        f"itself = {committed:.0f} MB, over the {budget} MB budget on a {BEELINK_TOTAL_MB} MB "
        "node. Raising capacity without shrinking the per-job limit is how parallel CI becomes "
        "an OOM event that takes Gitea down with it."
    )

    assert capacity >= 1, "capacity below 1 means no job ever runs"
    # The floor, per lesson-416: every assertion above is satisfied by a budget of
    # zero committed memory, which is the one state that can never occur.
    assert committed > 0, "nothing was counted; this budget check is measuring an empty set"


def test_the_job_containers_are_bounded_not_just_the_runner() -> None:
    """The runner's compose limit bounds a 43 MB process, not the build.

    A job container is a SIBLING started on the host daemon through the mounted
    socket. It is not a child of act_runner and inherits none of its
    `deploy.resources`. `container.options` is the only thing that bounds it, and
    without this assertion the compose limit reads as protection while the process
    that actually consumes the node is unlimited.
    """
    options = str(_config()["container"]["options"] or "")

    assert "--memory" in options, (
        f"container.options has no --memory: {options!r}. The runner's own compose "
        "limit does not reach the job container."
    )
    assert "--cpus" in options, f"container.options has no --cpus: {options!r}"


def test_the_registration_token_is_injected_not_literal() -> None:
    """The token is a rendered variable, so it comes from SOPS and not from the file.

    `compose.yml.j2` is committed. A registration token written into it would be a
    live credential in git, which is what the whole secret-delivery path exists to
    avoid.
    """
    raw = (ROLE / "templates" / COMPOSE_TEMPLATE).read_text()

    assert 'GITEA_RUNNER_REGISTRATION_TOKEN: "{{ act_runner_token }}"' in raw, (
        "the runner's registration token must come from a Jinja variable fed by SOPS, "
        "never a literal in a committed template."
    )


def test_the_runner_is_resource_bounded() -> None:
    """ADR-030: CI on this node must not be able to evict the forge it builds for.

    The Beelink is 8 GB and on-demand, and it also runs Gitea, MinIO and the GitHub
    runner. An unbounded build container is the one workload here that can take the
    others down.
    """
    limits = (_runner().get("deploy") or {}).get("resources", {}).get("limits", {})

    assert limits.get("cpus"), "the runner declares no CPU limit (ADR-030)"
    assert limits.get("memory"), "the runner declares no memory limit (ADR-030)"


def test_the_runner_reaches_the_docker_socket() -> None:
    """Four of the six jobs in `resume`'s `ci.yml` build images.

    `setup-buildx-action` and `build-push-action` need a daemon. The existing GitHub
    runner on this node has the same mount for the same reason, which is the precedent
    ADR-030 already accepted.
    """
    volumes = _runner().get("volumes") or []

    assert any("/var/run/docker.sock" in str(v) for v in volumes), (
        "the runner has no Docker socket, so every image-building job fails."
    )


def test_the_mint_is_gated_on_the_secret_being_absent() -> None:
    """Re-minting REVOKES the token the running runner registered with.

    `models/actions/runner_token.go`: generating a registration token "reuses the
    latest active token or creates a new one, **invalidating all prior tokens for the
    same scope**". So an ungated mint does not merely churn — re-provisioning the node
    would silently deregister its own runner. The bot and admin token mints in this
    same file already carry this gate; this asserts the third one does too.
    """
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    minting = [
        t
        for t in tasks
        if "act_runner" in yaml.safe_dump(t) and ("generate-runner-token" in yaml.safe_dump(t))
    ]

    assert minting, "no task mints the runner registration token"
    for task in minting:
        assert task.get("when"), (
            f"the mint task {task.get('name')!r} has no `when:` gate. Minting is not "
            "idempotent and invalidates the previous token, so an ungated mint "
            "deregisters the running runner on every re-provision."
        )


def test_disabling_the_runner_removes_it_from_the_render() -> None:
    """`enabled: false` must actually withhold the service, not just read as if it does.

    Ansible is additive: deleting a service from a template stops rendering it and
    does nothing to the container already running. So the declaration needs a false
    branch that a test exercises — otherwise `enabled` is documentation, and the
    first person to rely on it finds a runner still taking jobs.

    The string-truthiness trap is the reason this asserts on the RENDER rather than
    on the flag. Ansible can deliver a var declared as `"{{ ... }}"` as the string
    `"False"`, and every non-empty string is truthy in Jinja — without `| bool` the
    gate would render the service for precisely the value meant to suppress it.
    """
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    runner = _ssot()
    rendered = _render_with(env, {**runner, "enabled": False})

    assert RUNNER_SERVICE not in rendered["services"], (
        f"`{RUNNER_SERVICE}` is still rendered with enabled=false; the gate does not gate."
    )
    # The rest of the stack must survive the branch — a gate that takes the forge
    # with it is worse than no gate.
    assert "gitea" in rendered["services"] and "github-runner" in rendered["services"], (
        "disabling the Actions runner removed other services from the stack"
    )


def test_the_gate_rejects_the_string_false() -> None:
    """`"False"` must disable, which is the whole reason the template carries `| bool`.

    Asserted directly because it is the failure that silently inverts: a truthy
    string renders the service while the declaration says it is off, and nothing
    about the output looks wrong.
    """
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    rendered = _render_with(env, {**_ssot(), "enabled": "False"})

    assert RUNNER_SERVICE not in rendered["services"], (
        'the string "False" rendered the runner. The `| bool` filter is missing from '
        "the gate, and Ansible can deliver this var as a string."
    )


def test_the_compose_file_is_rendered_again_after_the_token_is_minted() -> None:
    """The circularity is irreducible, so the file has to be rendered twice.

    The registration token can only be minted by a RUNNING Gitea, and Gitea is
    started by the very compose file that must carry that token. No ordering of
    tasks resolves this: the credential is issued by the service the credential
    configures.

    So on the run that mints, the compose file is rendered before the token exists
    and again after. Delete the second render and the first provision of a fresh
    node leaves a container holding an EMPTY token — looping on a rejected
    registration while reporting `Up`, with the playbook green. The runner would
    begin working on the SECOND provision, which is indistinguishable from the
    first one having worked slowly.

    This is asserted because the failure is invisible on every node that already
    has the token in SOPS. It only ever reappears on a rebuild, which is once a
    year and always under pressure.
    """
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    renders = [
        t
        for t in tasks
        if isinstance(t.get("template"), dict) and str(t["template"].get("dest", "")).endswith("compose.yml")
    ]

    assert len(renders) == 2, (
        f"expected the compose stack to be rendered twice, found {len(renders)}: "
        f"{[t.get('name') for t in renders]}.\n"
        "The second render is what gives the runner its freshly minted registration "
        "token in the SAME provision. Without it a fresh node needs two runs and the "
        "first one reports success."
    )

    second = renders[1]
    scoped = (second.get("vars") or {}).get("act_runner_token", "")

    assert "_act_runner_token" in str(scoped), (
        f"the second render does not scope `act_runner_token` to the mint's result "
        f"(got {scoped!r}). Re-rendering with the play-level fact reproduces the "
        "empty value, which is the bug rather than the fix."
    )

    guard = yaml.safe_dump(second.get("when"))

    assert "is changed" in guard or "changed" in guard, (
        f"the second render is not gated on the mint having run ({second.get('when')!r}). "
        "Ungated it rewrites the file on every provision, and `_act_runner_token.stdout` "
        "is undefined on the runs where the mint is skipped."
    )


def test_every_notify_names_a_handler_that_exists() -> None:
    """A notify pointing at nothing is silently ignored by Ansible.

    Not an error, not a warning — the handler simply never runs, and the play goes
    green. So renaming a handler without updating its notify sites removes the
    restart that made a config change take effect, and the only symptom is a
    container quietly running the old configuration.

    Scoped to this role rather than the fleet because this role is where the
    consequence is worst: three of its handlers exist specifically to close the
    bind-mount inode trap (ANSIBLE-054), and each one is load-bearing rather than
    tidy.
    """

    def _notified(doc: object) -> set[str]:
        found: set[str] = set()
        if isinstance(doc, dict):
            for key, value in doc.items():
                if key == "notify":
                    found |= {value} if isinstance(value, str) else set(value)
                else:
                    found |= _notified(value)
        elif isinstance(doc, list):
            for item in doc:
                found |= _notified(item)
        return found

    handlers = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
    defined = {h["name"] for h in handlers if isinstance(h, dict) and "name" in h}

    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    wanted = _notified(tasks) | _notified(handlers)

    assert wanted, "no task in this role notifies a handler — the parser is reading nothing"

    orphans = sorted(wanted - defined)

    assert not orphans, (
        f"notified but not defined in handlers/main.yml: {orphans}.\n"
        f"Defined handlers are {sorted(defined)}. Ansible ignores a notify that names "
        "no handler — no error, no warning, the play still goes green and whatever the "
        "handler was going to do simply does not happen."
    )
