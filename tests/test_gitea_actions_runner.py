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


def test_concurrent_jobs_fit_in_the_node_s_memory() -> None:
    """capacity x per-job memory must fit, whatever those two numbers become.

    Pinning `capacity == 1` would have been the wrong assertion: it fixes a value
    rather than the property that makes the value safe, and it goes red on a change
    that is perfectly correct -- which is how a test gets loosened instead of read.

    The property is arithmetic. **CPU can be oversubscribed safely and memory cannot**:
    too many CPU shares only throttles, while too much committed memory invokes the
    OOM killer on a node that also hosts the forge these jobs build for. So this
    checks memory, and lets CPU be a judgement call.
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
    committed = capacity * per_job_mb
    budget = BEELINK_TOTAL_MB - RESERVED_MB

    assert committed <= budget, (
        f"{capacity} concurrent jobs x {per_job_mb:.0f} MB = {committed:.0f} MB, over "
        f"the {budget} MB budget on a {BEELINK_TOTAL_MB} MB node. Raising capacity "
        "without shrinking the per-job limit is how parallel CI becomes an OOM event "
        "that takes Gitea down with it."
    )

    assert capacity >= 1, "capacity below 1 means no job ever runs"


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
