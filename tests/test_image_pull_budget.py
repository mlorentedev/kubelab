"""An image pull behind the lab edge is sized against its downlink first (#2742).

On 2026-10-27 `make provision NODE=ace2 ENV=prod` failed at "Pull the Open WebUI
image" with an EOF after 52 minutes. The edge shapes the uplink to
`networking.edge.uplink.bandwidth.down_kbit` on purpose (ADR-075), and nothing
said beforehand how long the pull would take.

`_includes/image-pull.yml` estimates the bytes to fetch from the registry, refuses
past a budget unless the run allows it, and bounds each attempt by the estimate.
A play whose node is behind the edge turns it on with `image_pull_down_kbit`.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import re
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import ansible_env
from toolkit.features.generator_ansible import AnsibleGenerator

REPO = Path(__file__).resolve().parents[1]
PLAYBOOKS = REPO / "infra/ansible/playbooks"
INCLUDE = PLAYBOOKS / "_includes/image-pull.yml"
ESTIMATOR = PLAYBOOKS / "files/image-pull-estimate.py"
ROLES = REPO / "infra/ansible/roles"
AGENT_STACK = ROLES / "agent_stack/tasks/main.yml"
COMMON = REPO / "infra/config/values/common.yaml"
SSOT = "{{ config.networking.edge.uplink.bandwidth.down_kbit }}"

# Roles that still pull bare on a node behind the edge, each with what holds it (#2742).
# Converting one removes it here, and a new bare pull fails until it is sized or listed.
UNSIZED_ROLES = {
    "docker": "the smoke pull: busybox, a few MB, off unless a play sets docker_smoke_build,"
    " and bounded by its own `timeout`, whose failure already names the uplink (#2722)",
}
# Plays of a node behind the edge that run a sized role without sizing it.
UNSIZED_PLAYS: dict[str, str] = {}

# Measured on 2026-10-29 for ghcr.io/open-webui/open-webui:v0.12.0 (amd64, 19 layers).
OPEN_WEBUI_BYTES = 1_618_157_731


def _estimator():
    spec = importlib.util.spec_from_file_location("image_pull_estimate", ESTIMATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(arch: str, sizes: list[int]) -> dict:
    return {
        "Descriptor": {"platform": {"architecture": arch, "os": "linux"}},
        "SchemaV2Manifest": {"layers": [{"size": size} for size in sizes]},
    }


def _manifest_list() -> list[dict]:
    attestation = {
        "Descriptor": {"platform": {"architecture": "unknown", "os": "unknown"}},
        "OCIManifest": {"layers": [{"size": 10_462_978}]},
    }
    return [_entry("amd64", [OPEN_WEBUI_BYTES - 100, 100]), attestation, _entry("arm64", [1_461_623_689])]


def test_the_estimate_reads_the_nodes_platform_and_skips_attestations():
    layer_bytes = _estimator().layer_bytes
    assert layer_bytes(_manifest_list(), "amd64") == OPEN_WEBUI_BYTES
    assert layer_bytes(_manifest_list(), "arm64") == 1_461_623_689
    assert layer_bytes(_entry("amd64", [5, 7]), "arm64") == 12, "a single-platform image is taken as it is"
    with pytest.raises(ValueError):
        layer_bytes(_manifest_list(), "riscv64")


def test_an_image_the_node_holds_costs_nothing_and_an_unreadable_one_stops_the_run():
    module = _estimator()
    held = {"present:1"}

    def run(cmd):
        if cmd[1] == "image":
            return subprocess.CompletedProcess(cmd, 0 if cmd[-1] in held else 1, "", "")
        if cmd[-1] == "private:1":
            return subprocess.CompletedProcess(cmd, 1, "", "unauthorized")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(_manifest_list()), "")

    assert module.estimate("amd64", ["present:1", "absent:1"], run=run) == {
        "bytes": OPEN_WEBUI_BYTES,
        "images": [{"image": "present:1", "bytes": 0}, {"image": "absent:1", "bytes": OPEN_WEBUI_BYTES}],
    }
    with pytest.raises(SystemExit, match="private:1"):
        module.estimate("amd64", ["private:1"], run=run)
    assert module.ARCH["x86_64"] == "amd64" and module.ARCH["aarch64"] == "arm64"


def _tasks() -> dict[str, dict]:
    return {task["name"].split(" {{")[0]: task for task in yaml.safe_load(INCLUDE.read_text(encoding="utf-8"))}


def _decide(down_kbit: int, nbytes: int, **extra) -> tuple[bool, int]:
    """What the include decides: whether the pull may start, and its bound in seconds."""
    env = ansible_env(".")
    env.filters["from_json"] = json.loads
    tasks = _tasks()
    names = {"image_pull_down_kbit": down_kbit, "_image_pull_estimate": {"stdout": json.dumps({"bytes": nbytes})}}
    names |= extra
    if down_kbit:
        facts = tasks["Size the pull of"]["ansible.builtin.set_fact"]
        names |= {key: int(env.from_string(value).render(**names)) for key, value in facts.items()}
    allowed = env.from_string("{{ (" + tasks["Refuse a pull of"]["ansible.builtin.assert"]["that"] + ") | bool }}")
    bound = env.from_string(tasks["Pull"]["async"]).render(**names)
    return allowed.render(**names) == "True", int(bound)


def test_the_estimate_is_stated_before_the_pull_whatever_it_decides():
    """`make provision` runs without -v, so a registered estimate alone says nothing."""
    names = list(_tasks())
    assert names.index("State the estimate for") < names.index("Refuse a pull of") < names.index("Pull")
    task = _tasks()["State the estimate for"]
    assert task["when"] == "image_pull_down_kbit | default(0) | int > 0"
    env = ansible_env(".")
    env.filters["from_json"] = json.loads
    images = [{"image": "a:1", "bytes": OPEN_WEBUI_BYTES}, {"image": "b:2", "bytes": 0}]
    message = env.from_string(task["ansible.builtin.debug"]["msg"]).render(
        image_pull_name="Open WebUI",
        image_pull_down_kbit=2970,
        _image_pull_bytes=OPEN_WEBUI_BYTES,
        _image_pull_seconds=4359,
        _image_pull_estimate={"stdout": json.dumps({"bytes": OPEN_WEBUI_BYTES, "images": images})},
    )
    assert message == (
        "Open WebUI: 1.6 GB to fetch (a:1 1.6 GB, b:2 0 Bytes), about 72.7 min at the edge's"
        " 2970 kbit/s, against a budget of 30 min."
    )


def test_a_pull_past_the_budget_is_refused_unless_the_run_allows_it():
    # 1.62 GB at 2970 kbit/s is 4359 s, past the 1800 s default.
    assert _decide(2970, OPEN_WEBUI_BYTES) == (False, 4359 * 2 + 300)
    assert _decide(2970, OPEN_WEBUI_BYTES, image_pull_allow_slow="true")[0]
    assert _decide(2970, OPEN_WEBUI_BYTES, image_pull_budget_seconds=5000)[0]
    assert _decide(2970, 100_000_000) == (True, 270 * 2 + 300)
    assert _decide(2970, 0) == (True, 300), "a held image still gets a bound"


def test_an_explicit_timeout_bounds_the_pull_whatever_the_estimate():
    """The lever when the estimate is wrong: a held tag counts 0, and gets 300 s."""
    assert _decide(2970, 0, image_pull_timeout_seconds="5400") == (True, 5400)
    assert _decide(0, OPEN_WEBUI_BYTES, image_pull_timeout_seconds=900) == (True, 900)


def test_a_node_outside_the_edge_is_not_estimated_and_keeps_a_fixed_bound():
    assert _decide(0, OPEN_WEBUI_BYTES) == (True, 3600)
    assert "image_pull_down_kbit | default(0) | int > 0" in _tasks()["Estimate the download of"]["when"]


def test_the_pull_is_polled_and_retried_rather_than_held():
    pull = _tasks()["Pull"]
    assert pull["poll"] > 0 and pull["until"] == "_image_pull is succeeded"
    assert "image_pull_retries" in str(pull["retries"])
    assert _tasks()["Estimate the download of"]["check_mode"] is False, "a dry run reports the estimate"


def _pull(images: list[str], failing: str = "") -> subprocess.CompletedProcess:
    """The pull's shell for `images`, with `docker` a function that logs its arguments
    and fails for the image named `failing`."""
    shell = ansible_env(".").from_string(_tasks()["Pull"]["ansible.builtin.shell"]).render(image_pull_images=images)
    docker = f'docker() {{ echo "$*"; [ "$2" != {failing!r} ]; }}; '
    return subprocess.run(["sh", "-c", docker + shell], capture_output=True, text=True, check=False)


def test_the_pull_fetches_each_listed_image_by_name_and_stops_at_a_failure():
    """By name, so it needs nothing rendered on disk and runs before any write (#2812)."""
    images = ["ghcr.io/a/b:1@sha256:" + "0" * 64, "c:2"]
    done = _pull(images)
    assert (done.returncode, done.stdout.splitlines()) == (0, [f"pull {image}" for image in images])
    stopped = _pull(images, failing=images[0])
    assert stopped.returncode != 0 and stopped.stdout.splitlines() == [f"pull {images[0]}"]
    assert _pull(["a:1; touch /tmp/x"]).stdout.splitlines() == ["pull a:1; touch /tmp/x"], "one quoted word"


def test_the_pull_is_a_change_only_when_docker_fetched_an_image():
    """`docker pull` prints its status on stdout; reading stderr, as for compose, saw none."""
    changed_when = _tasks()["Pull"]["changed_when"]
    env = ansible_env(".")

    def changed(stdout: str) -> bool:
        rendered = env.from_string("{{ (" + changed_when + ") | bool }}")
        return rendered.render(_image_pull={"stdout": stdout, "stderr": ""}) == "True"

    assert changed("abc: Pull complete\nStatus: Downloaded newer image for c:2\nc:2")
    assert not changed("Status: Image is up to date for c:2\nc:2")


def test_no_call_names_a_pull_command():
    """The include pulls the list it estimated: a command passed beside it would be ignored."""
    assert all("image_pull_command" not in args for _, args in _include_calls())


def _networking() -> dict:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]


@cache
def _inventory() -> tuple[dict[str, frozenset[str]], frozenset[str]]:
    """The groups the inventory generator emits, the derived ones included, and the
    hosts it retires: a play can name those, and they resolve to nothing."""
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    networking = common["networking"]
    inventory = AnsibleGenerator()._build_inventory(networking, backup_sources=common["backup"]["sources"])
    groups = {name: frozenset((group or {}).get("hosts") or {}) for name, group in inventory["all"]["children"].items()}
    blocks = [*networking["nodes"].items(), *((k, v) for k, v in networking.items() if isinstance(v, dict))]
    retired = frozenset(
        block.get("hostname", key) for key, block in blocks if isinstance(block, dict) and block.get("retired")
    )
    return groups, retired


def _nodes(hosts: str | list[str], networking: dict | None = None) -> set[str]:
    """The hosts a play's `hosts:` names, resolved against the generated inventory:
    unions, then `&` narrows, then `!` drops. A name it does not emit fails."""
    groups, retired = _inventory()
    every = set().union(*groups.values())

    def resolve(name: str) -> set[str]:
        if name == "all":
            return every
        if name in groups:
            return set(groups[name])
        if name in every:
            return {name}
        assert name in retired, f"hosts: {name!r} is no host or group the inventory emits"
        return set()

    found, narrowed, dropped = set(), [], set()
    for term in hosts if isinstance(hosts, list) else re.split(r"[:,]", hosts):
        term = term.strip()
        if term.startswith("&"):
            narrowed.append(resolve(term[1:]))
        elif term.startswith("!"):
            dropped |= resolve(term[1:])
        else:
            found |= resolve(term)
    for group in narrowed:
        found &= group
    return found - dropped


def _behind_the_edge(node: str, networking: dict) -> bool:
    """On the switch, or on the lab Wi-Fi the edge serves: both leave by its uplink."""
    lan_ip = networking["nodes"].get(node, {}).get("lan_ip")
    sides = (networking["lan_cidr"], networking["edge"]["lab_wifi"]["cidr"])
    return bool(lan_ip) and any(ipaddress.ip_address(lan_ip) in ipaddress.ip_network(side) for side in sides)


def _plays() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if isinstance(play, dict) and "hosts" in play:
                found.append((path.name, play))
    return found


ROLE_MODULES = ("include_role", "import_role", "ansible.builtin.include_role", "ansible.builtin.import_role")


def _roles(play: dict) -> set[str]:
    """The roles a play runs: its `roles:` list, and any `include_role`/`import_role` in its tasks."""
    found = {Path(entry["role"] if isinstance(entry, dict) else entry).name for entry in play.get("roles") or []}
    for key in ("pre_tasks", "tasks", "post_tasks", "handlers"):
        for task in _task_list(play.get(key)):
            for module in ROLE_MODULES:
                if isinstance(task.get(module), dict):
                    found.add(Path(task[module]["name"]).name)
    return found


def _plays_setting_the_downlink() -> dict[str, str]:
    found = {}
    for name, play in _plays():
        if "image_pull_down_kbit" in (play.get("vars") or {}):
            assert play["vars"]["image_pull_down_kbit"] == SSOT, f"{name}: read the SSOT, not a copy"
            found[name] = play["hosts"]
    return found


def test_only_plays_of_nodes_behind_the_edge_size_their_pulls():
    networking = _networking()
    plays = _plays_setting_the_downlink()
    names = ("provision-ace1.yml", "provision-ace2.yml", "provision-bee.yml", "provision-rpi3.yml")
    assert {plays.get(name) for name in names} == {"ace1", "ace2", "beelink", "rpi3"}
    # The edge's own pulls leave by the uplink it shapes, so they are sized the same way.
    assert {plays.get(name) for name in ("provision-rpi4.yml", "deploy-dns.yml")} == {"gateway"}
    for name, hosts in plays.items():
        nodes = _nodes(hosts, networking)
        assert nodes and all(_behind_the_edge(node, networking) for node in nodes), (
            f"{name}: {hosts} is not behind the edge"
        )


def test_every_play_names_hosts_the_inventory_emits():
    """A name that resolved to nothing used to count as outside the edge, unchecked."""
    for name, play in _plays():
        _nodes(play["hosts"])
    assert _nodes("node_backup:&on_demand") == {"ace2", "beelink", "rpi4"}
    assert _nodes("node_backup:!rpi3") == {"ace2", "beelink", "kubelab-vps", "rpi4"}
    assert _nodes("aws1") == set(), "retired: emitted by no inventory"
    with pytest.raises(AssertionError, match="no host or group"):
        _nodes("bealink")


def test_a_node_on_the_lab_wifi_is_behind_the_edge():
    """The edge serves the lab Wi-Fi from its AP and routes it out the same uplink."""
    networking = _networking()
    wifi = ipaddress.ip_network(networking["edge"]["lab_wifi"]["cidr"])
    on_wifi = {
        n
        for n, node in networking["nodes"].items()
        if node.get("lan_ip") and ipaddress.ip_address(node["lan_ip"]) in wifi
    }
    assert "rpi3" in on_wifi
    assert all(_behind_the_edge(node, networking) for node in on_wifi)


def _task_list(tasks: list | None):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for key in ("block", "rescue", "always"):
            yield from _task_list(task.get(key))


def _pulls_bare(task: dict) -> bool:
    """A task that pulls an image without the include: a command, or a module told to."""
    if "_includes/image-pull.yml" in str(task.get("ansible.builtin.import_tasks", task.get("import_tasks", ""))):
        return False
    text = " ".join(
        str(task.get(key, "")) for key in ("command", "shell", "ansible.builtin.command", "ansible.builtin.shell")
    )
    text += " " + " ".join(str(item) for item in task.get("loop") or [])
    image_pull = re.search(r"\bpull\b", text) and re.search(r"\b(docker|compose)\b", text)
    return bool(image_pull) or _module_pulls(task)


def _module_pulls(task: dict) -> bool:
    """community.docker fetches an image the daemon lacks unless told never to."""

    def args(name: str) -> dict | None:
        found = task.get(f"community.docker.{name}", task.get(name))
        return found if isinstance(found, dict) else None

    fetching = [m for m in (args("docker_container"), args("docker_compose_v2")) if m is not None]
    image = args("docker_image") or {}
    return any(m.get("pull") != "never" for m in fetching) or image.get("source") == "pull"


def _roles_pulling_bare() -> set[str]:
    found = set()
    for path in ROLES.glob("*/tasks/*.yml"):
        if any(_pulls_bare(task) for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8")))):
            found.add(path.parts[-3])
    return found


def test_no_role_on_a_node_behind_the_edge_pulls_outside_the_include():
    networking = _networking()
    behind = set()
    for _, play in _plays():
        if any(_behind_the_edge(node, networking) for node in _nodes(play["hosts"], networking)):
            behind |= _roles(play)
    assert {"glances", "agent_stack"} <= behind, "the resolution lost the roles it was written for"
    assert _roles_pulling_bare() & behind == set(UNSIZED_ROLES)


def _include_calls() -> list[tuple[str, dict]]:
    """Each call of the include from a role: the role, and the vars it passes."""
    found = []
    for path in sorted(ROLES.glob("*/tasks/*.yml")):
        for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8"))):
            if "_includes/image-pull.yml" in str(
                task.get("ansible.builtin.import_tasks", task.get("import_tasks", ""))
            ):
                found.append((path.parts[-3], task["vars"]))
    return found


def _compose_templates(role: str) -> set[str]:
    """The Compose files a role renders: a template whose source is named for one."""
    found = set()
    for path in (ROLES / role / "tasks").glob("*.yml"):
        for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8"))):
            module = task.get("template", task.get("ansible.builtin.template"))
            if isinstance(module, dict) and re.search(r"compose[\w-]*\.ya?ml\.j2$", module["src"]):
                found.add(module["src"])
    return found


def _bare(image: str) -> str:
    """`"{{ x }}"`, `{{ x }}` and `x` all name x; anything else is kept whole, so it fails to match."""
    return re.sub(r"^\{\{\s*(.+?)\s*\}\}$", r"\1", image.strip("'\""))


def _images_pulled(template: Path) -> set[str]:
    """The image of each service a compose pull fetches: every one not built on the node.

    A service starts at any key two spaces in, its name a template or not."""
    found = set()
    for service in re.split(r"^  (?=[^\s#].*:\s*$)", template.read_text(encoding="utf-8"), flags=re.M):
        image = re.search(r"^\s+image:\s*(.+?)\s*$", service, re.M)
        if image and not re.search(r"^\s+pull_policy:\s*never\b", service, re.M):
            found.add(_bare(image.group(1)))
    return found


def test_a_compose_stack_fetches_no_image_its_role_does_not_pull():
    """The include pulls the images a call lists, so one a Compose file adds and the
    list lacks would be fetched by `up`, unsized (#2742, #2812)."""
    listed: dict[str, str] = {}
    for role, args in _include_calls():
        listed[role] = listed.get(role, "") + " " + str(args["image_pull_images"])
    checked = set()
    for role, images in listed.items():
        templates = _compose_templates(role)
        assert templates, f"{role}: pulls for no Compose template"
        for src in templates:
            for image in _images_pulled(ROLES / role / "templates" / src):
                # A whole name: `runner_image` is inside `act_runner_image`.
                named = re.search(rf"(?<![\w.]){re.escape(image)}(?![\w.])", images)
                assert named, f"{role}: {src} fetches {image}, which no call pulls"
                checked.add(image)
    assert {
        "glances_image",
        "gitea_image",
        "runner_image",
        "act_runner_image",
        "coredns_image",
        "pihole_image",
    } <= checked
    assert "agent_stack_mcp_bridge_image" not in checked, "built on the node, never pulled"


def test_a_play_behind_the_edge_that_runs_a_sized_pull_sizes_it():
    networking = _networking()
    sized = {path.parts[-3] for path in ROLES.glob("*/tasks/*.yml") if "_includes/image-pull.yml" in path.read_text()}
    assert sized >= {"agent_stack", "glances", "coredns"}
    unsized = set()
    for name, play in _plays():
        behind = any(_behind_the_edge(node, networking) for node in _nodes(play["hosts"], networking))
        if behind and _roles(play) & sized and "image_pull_down_kbit" not in (play.get("vars") or {}):
            unsized.add(name)
    assert unsized == set(UNSIZED_PLAYS)


def test_a_play_that_sizes_a_pull_gathers_the_architecture_it_estimates_for():
    """The estimate reads the layers for `ansible_architecture`, a fact: a play that
    skips fact gathering fails at the estimate, not at the pull (#2742)."""
    sized = {path.parts[-3] for path in ROLES.glob("*/tasks/*.yml") if "_includes/image-pull.yml" in path.read_text()}
    for name, play in _plays():
        if _roles(play) & sized:
            assert play.get("gather_facts", True) is not False, f"{name}: runs a sized pull without facts"
            subset = play.get("gather_subset")
            assert subset is None or {"all", "min", "platform"} & set(subset), f"{name}: no platform facts"


def test_open_webui_is_pulled_through_the_include():
    text = AGENT_STACK.read_text(encoding="utf-8")
    block = text[text.index("- name: Pull the Open WebUI image") :].split("\n\n")[0]
    assert "_includes/image-pull.yml" in block
    assert 'image_pull_images: ["{{ agent_stack_webui.image }}"]' in block
    assert "compose-webui.yml pull" not in text, "a second, bare pull of the same stack"


def _imports(path: Path) -> list[dict]:
    return [
        task
        for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8")))
        if "_includes/image-pull.yml" in str(task.get("ansible.builtin.import_tasks", ""))
    ]


@pytest.mark.parametrize(
    ("role", "images"),
    [
        ("glances", ["{{ glances_image }}"]),
        ("rpi3_services", ["{{ uptime_kuma_image }}"]),
        (
            "beelink_services",
            "{{ [gitea_image, runner_image] + ([act_runner_image] if act_runner_enabled | bool else []) }}",
        ),
    ],
)
def test_a_stack_role_pulls_before_anything_else(role: str, images) -> None:
    """A refused pull then leaves the node as it was, whatever the role writes (#2812)."""
    path = ROLES / role / "tasks/main.yml"
    (pull,) = _imports(path)
    assert pull["vars"]["image_pull_images"] == images
    assert yaml.safe_load(path.read_text(encoding="utf-8"))[0] == pull


def test_the_hermes_images_are_sized_on_the_agents_own_daemon():
    """Rootless: the daemon that holds them, and that a held image is read from, is the agent's."""
    stack, sandbox = _imports(ROLES / "agent_stack/tasks/hermes.yml")
    declared = _images_pulled(ROLES / "agent_stack/templates/compose-hermes.yml.j2")
    assert {_bare(i) for i in stack["vars"]["image_pull_images"]} == declared, (
        "an image the compose stack fetches unpulled"
    )
    assert sandbox["vars"]["image_pull_images"] == ["{{ agent_stack_hermes.sandbox.image }}"]
    for task in (stack, sandbox):
        assert task["become_user"] == "{{ agent_stack_agent_user }}"
        assert task["environment"] == "{{ agent_stack_agent_daemon_env }}"


def test_the_guard_reads_image_pulls_and_roles_however_they_are_written():
    assert _pulls_bare({"ansible.builtin.command": "docker compose -f x.yml pull"})
    assert _pulls_bare({"command": "docker {{ item }}", "loop": ["pull a:1"]})
    assert _pulls_bare({"community.docker.docker_container": {"name": "x", "pull": True}})
    assert _pulls_bare({"ansible.builtin.command": {"argv": ["docker", "pull", "a:1"]}})
    # The docker modules fetch an image the daemon lacks unless told never to.
    assert _pulls_bare({"community.docker.docker_container": {"name": "x", "image": "a:1"}})
    assert _pulls_bare({"docker_container": {"name": "x", "image": "a:1", "pull": False}})
    assert not _pulls_bare({"community.docker.docker_container": {"name": "x", "image": "a:1", "pull": "never"}})
    assert _pulls_bare({"community.docker.docker_compose_v2": {"project_src": "/opt/x"}})
    assert not _pulls_bare({"community.docker.docker_compose_v2": {"project_src": "/opt/x", "pull": "never"}})
    assert _pulls_bare({"community.docker.docker_image": {"name": "a:1", "source": "pull"}})
    assert not _pulls_bare({"community.docker.docker_image": {"name": "a:1", "source": "local"}})
    assert not _pulls_bare({"ansible.builtin.command": "git -C /opt/x pull --ff-only"})
    play = {"roles": ["../roles/a"], "tasks": [{"block": [{"include_role": {"name": "../roles/b"}}]}]}
    play["pre_tasks"] = [{"ansible.builtin.import_role": {"name": "c"}}]
    assert _roles(play) == {"a", "b", "c"}


#: Roles whose sized pull still comes after a template whose change gates a restart
#: or a recreate, each with the ticket that moves it. **It may only shrink**: a role
#: fixed must leave it, and a role added to it is the reviewable act.
PULL_AFTER_GATED_TEMPLATES: dict[str, str] = {
    "agent_stack": "#2812, once ace2's image store is refilled (#2703)",
}

_INCLUDES = ("import_tasks", "ansible.builtin.import_tasks", "include_tasks", "ansible.builtin.include_tasks")
_WRITES = ("template", "ansible.builtin.template", "copy", "ansible.builtin.copy")
# `x.changed`, `x is changed` and `x is not changed` all make a later task act on the write.
_GATES = re.compile(r"\b(\w+)(?:\.changed\b|\s+is\s+(?:not\s+)?changed\b)")


def test_a_sized_pull_runs_before_the_writes_whose_change_a_later_task_acts_on():
    """A refused pull stops the play. Past a write whose change gates a restart, the
    rerun sees no change and skips the restart, so the service keeps the old file
    (#2810). A notified handler is lost the same way: nothing forces handlers here."""
    checked, early = set(), {}
    for path in ROLES.glob("*/tasks/*.yml"):
        tasks = list(_task_list(yaml.safe_load(path.read_text(encoding="utf-8"))))
        pulls = [
            i for i, t in enumerate(tasks) if any("_includes/image-pull.yml" in str(t.get(k, "")) for k in _INCLUDES)
        ]
        if not pulls:
            continue
        role = path.parts[-3]
        acted_on = {m.group(1) for t in tasks for m in _GATES.finditer(str(t))}
        for i, task in enumerate(tasks):
            if any(k in task for k in _WRITES) and (task.get("register") in acted_on or "notify" in task):
                checked.add(role)
                if i < pulls[0]:
                    early.setdefault(role, []).append(task["name"])
    assert {"coredns", "glances", "rpi3_services", "agent_stack", "beelink_services"} <= checked, (
        f"the guard lost a role it was written for: it reads {sorted(checked)}"
    )
    assert set(early) == set(PULL_AFTER_GATED_TEMPLATES), early


def test_the_order_guard_reads_both_ways_a_task_gates_on_a_change():
    assert {m.group(1) for m in _GATES.finditer("a.changed or b is changed and c is not changed")} == {"a", "b", "c"}
