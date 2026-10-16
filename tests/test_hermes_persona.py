"""hermes-kubelab's persona (spec AI-012 AC3).

The public part is rendered by the role from a template; the operator's private
profile is joined on the node from the root-owned vault mirror, so it never enters the
repository and never passes through the controller. The result is mounted read-only over
the data directory's `SOUL.md`, so the agent cannot rewrite who it is.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests.test_hermes_config import HERMES, _render

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/agent_stack"
RETIRED = ("nan", "telegram", "kubernetes", " pod", "tirith", "openrouter", "bright data", "100.64.0.9")


def _flat(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for task in items:
        out.append(task)
        out.extend(_flat(task.get("block", [])))
    return out


def _tasks() -> list[dict]:
    return _flat(yaml.safe_load((ROLE / "tasks/hermes.yml").read_text()))


def _task(name: str) -> dict:
    [task] = [t for t in _tasks() if t.get("name") == name]
    return task


def _soul() -> str:
    return _render("hermes-soul.md.j2")


def test_the_persona_names_what_the_agent_is_and_where_it_may_write() -> None:
    soul = _soul()
    assert soul.startswith("# hermes-kubelab")
    assert f"80_agents/{HERMES['user']}/" in soul, "its zone is the boundary it is told about"
    assert HERMES["slack"]["home_channel"]["name"] in soul


def test_the_persona_carries_nothing_from_the_retired_instance() -> None:
    """Adapted from hermes-nan's persona without its platform: no NaN, Telegram or pod."""
    soul = _soul().lower()
    assert not [word for word in RETIRED if re.search(rf"(?<![a-z]){re.escape(word.strip())}(?![a-z])", soul)]


def test_the_persona_holds_no_operator_detail_the_repository_must_not_carry() -> None:
    """The private profile is the vault's. The public text says how to talk, not who the operator is."""
    soul = _soul().lower()
    for private in ("manu", "mlorente", "@", "denver", "schedule"):
        assert private not in soul, f"{private!r} belongs in the profile, not in the repository"


def test_the_profile_is_read_on_the_node_and_never_through_the_controller() -> None:
    text = (ROLE / "tasks/hermes.yml").read_text()
    assert "slurp" not in text
    assert "lookup('file'" not in text and "lookup('ansible.builtin.file'" not in text
    assert (ROLE / "defaults/main.yml").read_text().count("80_agents/operator/hermes-kubelab/profile.md") == 1


def test_no_task_that_touches_the_profile_prints_it() -> None:
    names = (
        "Take the profile without its frontmatter",
        "Install the profile fragment",
        "Join the persona",
    )
    for name in names:
        assert _task(name)["diff"] is False, f"{name}: a diff would print the profile into the run's output"


def test_the_profile_joins_from_the_vault_mirror_not_the_agents_clone() -> None:
    """The agent writes its zone and holds the clone's token; the mirror is root's."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["agent_stack_hermes_profile_source"].startswith("{{ agent_stack_vault_mirror }}/")


def test_the_persona_is_joined_on_the_node_from_fragments_in_order() -> None:
    joined = _task("Join the persona")["ansible.builtin.assemble"]
    assert joined["remote_src"] is True
    assert joined["owner"] == "root"
    assert joined["dest"].endswith("/SOUL.md")
    pattern = re.compile(joined["regexp"])
    assert pattern.match("00-public.md") and pattern.match("10-operator.md")
    assert not pattern.match(".10-operator.new"), "the staging copy is never joined"


def test_without_a_profile_the_persona_is_the_public_part_alone() -> None:
    removed = _task("Remove the profile fragment when the mirror has none")
    assert removed["ansible.builtin.file"]["state"] == "absent"
    assert "stat.exists" in removed["when"]
    assert "default(false)" in removed["when"], "a node without the vault still renders"


def test_the_persona_is_root_owned_so_the_agent_cannot_rewrite_it() -> None:
    for name in ("Create the persona directories", "Render the public persona", "Install the profile fragment"):
        spec = next(v for k, v in _task(name).items() if k.startswith("ansible.builtin."))
        assert spec["owner"] == "root" and spec["group"] == "root", name


def test_the_persona_is_mounted_read_only_over_the_data_directorys_copy() -> None:
    compose = _render("compose-hermes.yml.j2")
    assert re.search(r"- \S+/hermes-persona/SOUL\.md:\S+/SOUL\.md:ro\n", compose)


def test_a_changed_persona_recreates_the_gateway() -> None:
    """A rename leaves a single-file bind mount on the old file."""
    start = _task("Start hermes-kubelab")["ansible.builtin.command"]
    assert "_agent_stack_hermes_soul.changed" in start


def test_the_persona_is_joined_before_the_gateway_is_started() -> None:
    names = [t.get("name") for t in _tasks()]
    assert names.index("Join the persona") < names.index("Start hermes-kubelab")
