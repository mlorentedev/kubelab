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

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tests.test_beelink_compose_unit import REPO, ROLE

COMPOSE_TEMPLATE = "compose.yml.j2"

#: The service name the rest of this file asserts against.
RUNNER_SERVICE = "act-runner"

#: Gitea resolves `runs-on` against the runner's declared labels. This is the label a
#: migrated GitHub workflow will ask for.
GITHUB_HOSTED_LABEL = "ubuntu-latest"


def _render() -> dict:
    """Render the Beelink compose template and parse it as YAML.

    Rendered rather than read: the runner block is Jinja, and asserting on the source
    text would pass on a template that never emits the service.
    """
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    gitea = common["apps"]["services"]["core"]["gitea"]

    return yaml.safe_load(
        env.get_template(COMPOSE_TEMPLATE).render(
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
            act_runner_image="gitea/act_runner:0.2.13",
            act_runner_token="x",
            act_runner_cpu_limit="2",
            act_runner_memory_limit="2G",
            act_runner_labels=f"{GITHUB_HOSTED_LABEL}:docker://catthehacker/ubuntu:act-22.04",
            docker_dns_servers=["100.100.100.100", "1.1.1.1"],
        )
    )


def _runner() -> dict:
    services = _render()["services"]
    assert RUNNER_SERVICE in services, (
        f"the compose template emits no `{RUNNER_SERVICE}` service. Gitea Actions is "
        "already enabled on the instance and on both migrated repositories "
        "(`has_actions=True`, `/actions/tasks` -> 200), so the runner is the only "
        "missing piece — and a workflow with no runner QUEUES rather than failing."
    )
    return services[RUNNER_SERVICE]


def test_the_runner_advertises_the_github_hosted_label() -> None:
    """A migrated workflow says `runs-on: ubuntu-latest`, which Gitea does not define.

    Gitea has no hosted runners, so the label is only ever what act_runner declares.
    Without the mapping, `runs-on: ubuntu-latest` matches no runner and the job waits
    indefinitely — no error, no failed check, nothing to notice.
    """
    rendered = yaml.safe_dump(_runner())

    assert GITHUB_HOSTED_LABEL in rendered, (
        f"the runner declares no `{GITHUB_HOSTED_LABEL}` label. Every workflow "
        "migrated from GitHub asks for it, and a job matching no runner is queued "
        "forever rather than reported as failed."
    )


def test_the_registration_token_is_injected_not_literal() -> None:
    """The token is a rendered variable, so it comes from SOPS and not from the file.

    `compose.yml.j2` is committed. A registration token written into it would be a
    live credential in git, which is what the whole secret-delivery path exists to
    avoid.
    """
    raw = (ROLE / "templates" / COMPOSE_TEMPLATE).read_text()
    block = raw[raw.index(f"  {RUNNER_SERVICE}:") :] if f"  {RUNNER_SERVICE}:" in raw else ""

    assert "{{ act_runner_token }}" in block, (
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
