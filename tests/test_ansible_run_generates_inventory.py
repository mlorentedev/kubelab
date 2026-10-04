"""`toolkit infra ansible run` generates the inventory it runs against (TOOL-090, #1941).

The inventory is gitignored, so on disk it is either missing (a fresh worktree)
or generated from an older common.yaml. Generating before the run was a
per-target Makefile convention, and seven targets had not followed it. A stale
inventory does not fail: a play whose pattern no longer matches is a warning and
exit 0 (lesson-356). So `run` now generates first, in the mode it is given, and
a failed generation stops it before ansible-playbook is invoked.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
import typer

from toolkit.cli import infra
from toolkit.features import generator_ansible
from toolkit.features.configuration import ConfigurationManager

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ansible_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "playbooks").mkdir()
    (tmp_path / "playbooks" / "site.yml").write_text("---\n")
    (tmp_path / "generated" / "prod").mkdir(parents=True)
    (tmp_path / "generated" / "prod" / "hosts.yml").write_text("---\n")
    monkeypatch.setattr(infra, "settings", SimpleNamespace(ansible_dir=tmp_path))
    return tmp_path


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Records generate and ansible-playbook in the order they happen."""
    log: list[tuple[str, Any]] = []

    def fake_generate(env: str, bootstrap: bool = False, transport: str = "mesh") -> dict[str, Any]:
        log.append(("generate", (env, bootstrap, transport)))
        return {"success": True, "files": []}

    def fake_run(cmd: str, **_kwargs: Any) -> SimpleNamespace:
        log.append(("ansible-playbook", cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(generator_ansible.ansible_generator, "generate", fake_generate)
    monkeypatch.setattr(infra.command, "run", fake_run)
    return log


def _run(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "playbook": "site",
        "env": "prod",
        "limit": None,
        "tags": None,
        "check": False,
        "become_ask_pass": False,
        "extra_vars": None,
        "bootstrap": False,
        "transport": "mesh",
        "skip_generate": False,
    }
    kwargs.update(overrides)
    infra.ansible_run(**kwargs)


def test_the_inventory_is_generated_before_the_playbook_runs(ansible_dir: Path, calls: list) -> None:
    _run()
    assert [name for name, _ in calls] == ["generate", "ansible-playbook"]
    assert calls[0][1] == ("prod", False, "mesh")


def test_the_mode_reaches_the_generator(ansible_dir: Path, calls: list) -> None:
    _run(bootstrap=True, transport="mesh")
    assert calls[0] == ("generate", ("prod", True, "mesh"))


def test_a_failed_generation_stops_the_run(ansible_dir: Path, calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generator_ansible.ansible_generator,
        "generate",
        lambda *_a, **_k: {"success": False, "error": "backup.sources.x names no inventory host"},
    )
    with pytest.raises(typer.Exit) as exited:
        _run()
    assert exited.value.exit_code == 1
    assert not any(name == "ansible-playbook" for name, _ in calls)


def test_skip_generate_uses_the_inventory_on_disk(ansible_dir: Path, calls: list) -> None:
    _run(skip_generate=True)
    assert [name for name, _ in calls] == ["ansible-playbook"]


def test_skip_generate_without_an_inventory_fails_loudly(ansible_dir: Path, calls: list) -> None:
    (ansible_dir / "generated" / "prod" / "hosts.yml").unlink()
    with pytest.raises(typer.Exit):
        _run(skip_generate=True)
    assert calls == []


def test_an_unknown_playbook_generates_nothing(ansible_dir: Path, calls: list) -> None:
    with pytest.raises(typer.Exit):
        _run(playbook="nope")
    assert calls == []


def test_generation_needs_no_decryption_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every run generates now, so generation must not require the age key.

    Nothing in the inventory is secret: built from the decrypted merge and from
    the plaintext values it came out identical for staging and prod (measured
    for TOOL-090). The generator reads the plaintext values only.
    """

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("inventory generation decrypted a SOPS file")

    monkeypatch.setattr(ConfigurationManager, "_decrypt_sops", refuse)
    # A scratch project root: the real config, and an empty ansible dir to write into.
    (tmp_path / "infra" / "ansible").mkdir(parents=True)
    (tmp_path / "infra" / "config").symlink_to(_ROOT / "infra" / "config")
    generator = generator_ansible.AnsibleGenerator()
    monkeypatch.setattr(generator, "project_root", tmp_path)
    result = generator.generate("prod")
    assert result["success"], result.get("error")
    assert (tmp_path / "infra" / "ansible" / "generated" / "prod" / "hosts.yml").is_file()


def _recipes() -> dict[str, str]:
    """Makefile target -> its recipe text (tab-indented lines under the target)."""
    recipes: dict[str, str] = {}
    current = None
    for line in (_ROOT / "Makefile").read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+):(?!=)", line)
        if match:
            current = match.group(1)
            recipes[current] = ""
        elif current and line.startswith("\t"):
            recipes[current] += line + "\n"
        elif line and not line.startswith("#"):
            current = None
    return recipes


_BRANCH = re.compile(r"(?:else|then|elif|fi)\b")


def _generates_for_a_run(recipe: str) -> bool:
    """True when a generate is the inventory step of a following run: the old form.

    Per command, not per recipe: a recipe is split into shell commands, and a
    generate followed by a run with no branch keyword between them is the old
    convention. `provision`'s restore generate is followed by `else`, so the
    run after it belongs to the other branch.
    """
    joined = recipe.replace("\\\n", " ")
    pending = False
    for command in re.split(r";|&&|\|\||\n", joined):
        command = command.strip().lstrip("@").strip()
        if _BRANCH.match(command):
            pending = False
            command = _BRANCH.sub("", command, count=1).strip()
        if "infra ansible generate" in command:
            pending = True
        elif "infra ansible run" in command:
            if pending:
                return True
            pending = False
    return False


def test_no_make_recipe_generates_the_inventory_for_a_run() -> None:
    """The convention this replaces must not come back one target at a time.

    A generate BEFORE a run is the old form. One after it is allowed:
    `provision` restores the mesh inventory on disk after a bootstrap run.
    """
    offenders = [target for target, recipe in _recipes().items() if _generates_for_a_run(recipe)]
    assert not offenders, f"recipes still generate the inventory for their run: {offenders}"


def test_the_guard_sees_the_old_form_inside_a_recipe_that_restores() -> None:
    """Review of #1951: a per-recipe first-occurrence check exempted `provision` whole.

    Its bootstrap run comes before its restore generate, so re-adding the old
    `generate && run` to its else branch passed. Checked against the real
    recipe with exactly that edit.
    """
    provision = _recipes()["provision"]
    assert not _generates_for_a_run(provision)
    regressed = provision.replace(
        "\telse \\\n",
        "\telse \\\n\t\t$(TOOLKIT) infra ansible generate --env $(_ENV) >/dev/null && \\\n",
        1,
    )
    assert regressed != provision, "the provision recipe changed shape; update this mutation"
    assert _generates_for_a_run(regressed)


def test_the_recipe_parser_sees_every_run() -> None:
    """Guards the guard: a recipe the parser drops is a recipe the test above never checks.

    Counted against the raw file rather than a list of target names, so a new
    target, or one the parser splits or skips, cannot fall outside the check.
    """
    lines = (_ROOT / "Makefile").read_text().splitlines()
    in_file = sum(1 for line in lines if line.startswith("\t") and "infra ansible run" in line)
    parsed = sum(recipe.count("infra ansible run") for recipe in _recipes().values())
    assert in_file > 0, "no recipe runs a playbook: the Makefile moved or the pattern is stale"
    assert parsed == in_file, f"the parser saw {parsed} of the {in_file} recipe lines that run a playbook"


# What the inventory generator reads from the merged config. Plaintext is enough
# only while no SOPS file declares a key under these (review of #1951): a node
# override or a backup source added to an `*.enc.yaml` would be invisible to the
# generator, and `make backup-node NODE=all` would target a thinner group and
# exit 0 (lesson-356).
_GENERATOR_READS = ("networking", "backup.sources")


def test_the_generator_reads_only_the_subtrees_listed_here() -> None:
    source = (_ROOT / "toolkit" / "features" / "generator_ansible.py").read_text()
    top_level = set(re.findall(r"\bconfig\.get\(\"([a-z_]+)\"", source))
    assert top_level == {path.split(".")[0] for path in _GENERATOR_READS}, (
        f"the generator reads {sorted(top_level)} from the config; list each subtree in "
        "_GENERATOR_READS so the SOPS check below covers it"
    )


@pytest.mark.parametrize(
    "path", sorted((_ROOT / "infra" / "config" / "secrets").glob("*.enc.yaml")), ids=lambda p: p.name
)
def test_no_sops_file_declares_what_the_inventory_is_built_from(path: Path) -> None:
    """Key names are plaintext in a SOPS file, so this needs no decryption key."""
    doc = yaml.safe_load(path.read_text()) or {}
    declared = []
    for dotted in _GENERATOR_READS:
        node = doc
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            declared.append(dotted)
    assert not declared, (
        f"{path.name} declares {declared}. The inventory is generated from plaintext values "
        "only, so these keys would never reach it. Keep them in common.yaml / <env>.yaml."
    )
