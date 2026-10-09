"""The agent's own tailnet identity: a userspace tailscale sidecar (spec AI-009 PR 3b-2).

ADR-041 gives fleet agents a tag, `tag:hermes`, minted into a preauth key by the
`agents` user, so the ACL scopes them instead of the node's allow-all. On ace2
the sidecar runs on the agent's rootless daemon in userspace mode: it routes
nothing for the gateway, and the host refuses the tailnet to everything else
the agent runs (lesson-525, tests/test_agent_egress.py).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.test_agent_egress import _role_vars
from tests.test_agent_stack_role import _common, _render, _resolved, _tasks

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"


def _services() -> dict:
    return yaml.safe_load(_render("compose-hermes.yml.j2"))["services"]


def _sidecar() -> dict:
    return _services()["tailscale"]


def _task(name: str) -> dict:
    matches = [t for t in _tasks() if t.get("name") == name]
    assert len(matches) == 1, f"expected one task named {name!r}"
    return matches[0]


def test_the_sidecar_is_userspace_and_holds_no_privilege() -> None:
    sidecar = _sidecar()
    assert sidecar["environment"]["TS_USERSPACE"] == "true"
    for key in ("cap_add", "devices", "privileged", "network_mode"):
        assert key not in sidecar, f"a userspace sidecar needs no {key}"


def test_the_proxy_is_never_published() -> None:
    """The gateway reaches it on the project network; a published port would hand
    `tag:hermes` to anything that can reach the host."""
    assert "ports" not in _sidecar()


def test_the_tag_comes_from_the_key_alone() -> None:
    """ADR-041 errata: `--advertise-tags` beside a tagged key fails registration."""
    env = _sidecar()["environment"]
    headscale = _common()["apps"]["services"]["core"]["headscale"]
    assert "--advertise-tags" not in env["TS_EXTRA_ARGS"]
    assert env["TS_EXTRA_ARGS"] == f"--login-server=https://{headscale['domain']}"
    assert env["TS_AUTH_ONCE"] == "true", "a restart must rejoin from its state, never need the consumed key"


def test_the_node_key_is_outside_what_the_gateway_mounts() -> None:
    context = _resolved_context()
    state = context["agent_stack_hermes_ts_state"]
    home = context["agent_stack_hermes_home"]
    assert f"{state}:/var/lib/tailscale" in _sidecar()["volumes"]
    assert not state.startswith(home + "/") and state != home
    for volume in _services()["hermes"]["volumes"]:
        assert not volume.split(":")[0].startswith(state), "the gateway must not see the sidecar's state"


def test_only_the_sidecar_reads_the_preauth_key() -> None:
    ts_env = _resolved_context()["agent_stack_hermes_ts_env"]
    assert _sidecar()["env_file"] == [ts_env]
    assert ts_env not in _services()["hermes"]["env_file"]


def test_the_image_is_pinned_in_the_ssot() -> None:
    image = _common()["apps"]["services"]["ai"]["hermes_kubelab"]["sidecar"]["image"]
    assert _sidecar()["image"] == image
    assert image.startswith("tailscale/tailscale:v"), "a floating tag changes the client under Headscale unseen"


def test_the_key_is_minted_once_single_use_and_tagged() -> None:
    task = _task("Mint the sidecar's preauth key on Headscale")
    cmd = task["ansible.builtin.command"]
    assert "--tags tag:hermes" in cmd
    assert "--user {{ agent_stack_headscale_agents_user_id }}" in cmd
    assert "--reusable" not in cmd
    assert "--expiration 1h" in cmd
    assert task["when"] == "not (_agent_stack_hermes_ts_on_tailnet | bool)"
    assert task["delegate_to"] == "{{ agent_stack_headscale_host }}"
    assert task.get("no_log") is True, "the key is the command's output"
    # The gate is the sidecar's own answer, never its state file: tailscaled writes
    # that at its first start, so a failed first login would never be retried.
    ask = _task("Ask the sidecar whether it is on the tailnet")
    assert "tailscale status --json" in ask["ansible.builtin.command"]
    hold = _task("Hold whether the sidecar is on the tailnet")
    assert "BackendState == 'Running'" in hold["ansible.builtin.set_fact"]["_agent_stack_hermes_ts_on_tailnet"]
    assert not [t for t in _tasks() if "tailscaled.state" in str(t.get("ansible.builtin.stat", ""))]


def test_the_key_is_minted_under_the_agents_user() -> None:
    headscale = _common()["apps"]["services"]["core"]["headscale"]
    assert headscale["agents_user_id"] != headscale["infra_user_id"], "infra nodes' user would make it an infra node"
    assert (
        _role_vars()["agent_stack_headscale_agents_user_id"]
        == "{{ config.apps.services.core.headscale.agents_user_id }}"
    )


def test_the_env_file_is_private_and_emptied_after_registration() -> None:
    renders = [t for t in _tasks() if (t.get("ansible.builtin.template") or {}).get("src") == "hermes-tailscale.env.j2"]
    assert len(renders) == 2, "rendered with the key, then emptied"
    for task in renders:
        assert task["ansible.builtin.template"]["mode"] == "0600"
        assert task["ansible.builtin.template"]["owner"] == "{{ agent_stack_agent_user }}"
        assert task.get("no_log") is True
    empty = _task("Empty the sidecar's env file once it is registered")
    assert empty["vars"]["_agent_stack_hermes_ts_key"] == ""
    names = [t.get("name") for t in _tasks()]
    order = [
        "Verify the sidecar is on the tailnet as tag:hermes",
        "Empty the sidecar's env file once it is registered",
        "Recreate the sidecar without its consumed key",
        "Verify the sidecar rejoined from its state alone",
    ]
    assert [names.index(n) for n in order] == sorted(names.index(n) for n in order)


def test_a_new_key_recreates_the_sidecar_so_it_logs_in_again() -> None:
    """`TS_AUTH_ONCE` does not block a re-login: containerboot (v1.102.5,
    cmd/containerboot/main.go, `authLoop`) runs `tailscale up` with the key whenever
    tailscaled starts in `NeedsLogin`, state or no state. It reads the key only at
    start, though, so a freshly minted key must recreate the container."""
    from itertools import product

    from jinja2 import Environment, StrictUndefined

    env = Environment(undefined=StrictUndefined)
    env.filters["bool"] = lambda value: value if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")
    command = env.from_string(_task("Start hermes-kubelab")["ansible.builtin.command"])
    registers = ("_agent_stack_hermes_env_file", "_agent_stack_hermes_config", "_agent_stack_hermes_ts_env_file")
    # The fourth input is a fact, and set_fact hands it over as a string.
    for *changed, unbound in product((False, True), repeat=len(registers) + 1):
        context = {name: {"changed": flag} for name, flag in zip(registers, changed, strict=True)}
        rendered = command.render(
            agent_stack_hermes_project="p", agent_stack_hermes_compose="c", _agent_stack_hermes_unbound=str(unbound), **context
        )
        # Recreated exactly when an input changed or the port is lost: always
        # would break `changed=0`, and never would leave a new key unread.
        assert ("--force-recreate" in rendered) == (any(changed) or unbound), (changed, unbound, rendered)


def test_every_provision_reads_the_tag_from_the_running_sidecar() -> None:
    task = _task("Verify the sidecar is on the tailnet as tag:hermes")
    assert "tailscale status --json" in task["ansible.builtin.command"]
    assert "'tag:hermes' not in" in task["failed_when"]
    assert "'Running'" in task["failed_when"]
    assert "when" not in task, "the tag is read at every provision, not only at registration"
    assert task["become_user"] == "{{ agent_stack_agent_user }}"


def _resolved_context() -> dict:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    return _resolved(env)
