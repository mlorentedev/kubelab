"""`toolkit infra ansible run` generates the inventory it runs against (TOOL-090, #1941).

The inventory is gitignored, so on disk it is either missing (a fresh worktree)
or generated from an older common.yaml. Generating before the run was a
per-target Makefile convention, and seven targets had not followed it. A stale
inventory does not fail: a play whose pattern no longer matches is a warning and
exit 0 (lesson-356). So `run` now generates first, in the mode it is given, and
a failed generation stops it before ansible-playbook is invoked. After a
bootstrap or bastion run it puts the mesh inventory back, failed run or not.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer
import yaml

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


# --------------------------------------------- the mesh inventory comes back
#
# A bootstrap (LAN IPs) or bastion run leaves its inventory on disk, and whatever
# reads the file without running would address every node that way. Restoring it
# was a branch of `make provision`: TOOL-036 found that branch exiting 0 after a
# failed run, and `make reboot` had no branch at all, so it could not reach a node
# off the tailnet (the edge with its uplink down, NET-005's hard-reset test).
# `run` now restores after any such run, failed or not.

MESH = ("generate", ("prod", False, "mesh"))


@pytest.mark.parametrize(
    ("mode", "first"),
    [({"bootstrap": True}, ("prod", True, "mesh")), ({"transport": "bastion"}, ("prod", False, "bastion"))],
)
def test_a_bootstrap_or_bastion_run_restores_the_mesh_inventory(
    ansible_dir: Path, calls: list, mode: dict, first: tuple
) -> None:
    _run(**mode)
    assert [name for name, _ in calls] == ["generate", "ansible-playbook", "generate"]
    assert calls[0][1] == first
    assert calls[2] == MESH


def test_a_mesh_run_restores_nothing(ansible_dir: Path, calls: list) -> None:
    _run()
    assert calls.count(MESH) == 1 and calls[-1][0] == "ansible-playbook"


def test_skip_generate_restores_nothing(ansible_dir: Path, calls: list) -> None:
    """Nothing was generated for the run, so the inventory on disk is the operator's."""
    _run(bootstrap=True, skip_generate=True)
    assert [name for name, _ in calls] == ["ansible-playbook"]


def test_a_failed_run_restores_and_exits_non_zero(
    ansible_dir: Path, calls: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(cmd: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(("ansible-playbook", cmd))
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(infra.command, "run", failed)
    with pytest.raises(typer.Exit) as exited:
        _run(bootstrap=True)
    assert exited.value.exit_code == 1
    assert calls[-1] == MESH


def test_an_interrupted_run_still_restores(ansible_dir: Path, calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(cmd: str, **_kwargs: Any) -> SimpleNamespace:
        raise KeyboardInterrupt

    monkeypatch.setattr(infra.command, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _run(bootstrap=True)
    assert calls[-1] == MESH


def test_a_failed_restore_after_a_good_run_exits_non_zero(
    ansible_dir: Path, calls: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A success would hide that the inventory on disk is still the LAN one."""
    results = iter([{"success": True}, {"success": False, "error": "boom"}])

    def generate(env: str, bootstrap: bool = False, transport: str = "mesh") -> dict[str, Any]:
        calls.append(("generate", (env, bootstrap, transport)))
        return next(results)

    monkeypatch.setattr(generator_ansible.ansible_generator, "generate", generate)
    with pytest.raises(typer.Exit) as exited:
        _run(bootstrap=True)
    assert exited.value.exit_code == 1
    assert [name for name, _ in calls] == ["generate", "ansible-playbook", "generate"]


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


def _generates_and_runs(recipe: str) -> bool:
    """True when a recipe both generates the inventory and runs a playbook.

    Before the run is the convention TOOL-090 replaced; after it is the mesh
    restore `run` now does itself. Either way the generate is `run`'s job.
    """
    return "infra ansible generate" in recipe and "infra ansible run" in recipe


def test_no_make_recipe_generates_the_inventory_around_a_run() -> None:
    """The conventions `run` absorbed must not come back one target at a time."""
    offenders = [target for target, recipe in _recipes().items() if _generates_and_runs(recipe)]
    assert not offenders, f"recipes still generate the inventory around their run: {offenders}"


@pytest.mark.parametrize("where", ["before", "after"])
def test_the_guard_sees_a_generate_on_either_side_of_a_run(where: str) -> None:
    """Checked against a real recipe with the edit made, so the guard cannot pass vacuously."""
    reboot = _recipes()["reboot"]
    run = next(line for line in reboot.splitlines() if "infra ansible run" in line)
    generate = "\t@$(TOOLKIT) infra ansible generate --env $(_ENV)"
    edited = reboot.replace(run, f"{generate}\n{run}" if where == "before" else f"{run}\n{generate}", 1)
    assert not _generates_and_runs(reboot)
    assert _generates_and_runs(edited)


def _offers(flag: str) -> list[str]:
    return [target for target, recipe in _recipes().items() if f"[{flag}=" in recipe and "infra ansible run" in recipe]


def test_bootstrap_and_transport_reach_run_from_every_target_that_offers_them() -> None:
    """Expanded with `make -n`, so a flag the usage line offers but the run line drops fails here."""
    targets = _offers("BOOTSTRAP")
    assert {"provision", "reboot"} <= set(targets)
    for target in targets:
        dry = subprocess.run(
            ["make", "-n", target, "NODE=rpi4", "ENV=prod", "BOOTSTRAP=1", "TRANSPORT=bastion"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        run = next(line for line in dry.splitlines() if "infra ansible run" in line)
        assert "--bootstrap" in run and "--transport bastion" in run, (target, run)


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
# exit 0 (lesson-356). `networking` is guarded key by key, derived from the
# generator's own reads, because SOPS does hold a part of it the generator never
# reads: the lab edge's site secrets at `networking.edge`, which the rpi4 play
# takes from SOPS itself (#2665).
_GENERATOR_SOURCE = (_ROOT / "toolkit" / "features" / "generator_ansible.py").read_text()


def _networking_reads(source: str) -> tuple[set[str], list[int]]:
    """The keys `source` reads from `networking`, and the lines that use it any other way.

    Parsed rather than matched, so the form of a read cannot hide it: every load
    of the name is a constant-key read (`networking["k"]`, `networking.get("k")`),
    a hand-off to a function of this module whose parameter keeps the name, by
    position or by keyword (its reads are then reads of the same name), or a
    line in the second list.
    """
    tree = ast.parse(source)
    functions = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    keys: set[str] = set()
    other: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id == "networking" and isinstance(node.ctx, ast.Load)):
            continue
        parent = parents[node]
        call = parents.get(parent)
        if isinstance(parent, ast.Subscript) and isinstance(parent.slice, ast.Constant):
            keys.add(parent.slice.value)
        elif (
            isinstance(parent, ast.Attribute)
            and parent.attr == "get"
            and isinstance(call, ast.Call)
            and call.args
            and isinstance(call.args[0], ast.Constant)
        ):
            keys.add(call.args[0].value)
        elif isinstance(parent, ast.Call) and node in parent.args and _keeps_the_name(parent, node, functions):
            continue
        elif isinstance(parent, ast.keyword) and parent.arg == "networking" and _takes_networking(call, functions):
            continue
        else:
            other.append(node.lineno)
    return keys, other


def _callee(call: ast.Call, functions: dict[str, ast.FunctionDef]) -> ast.FunctionDef | None:
    name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
    return functions.get(name)


def _keeps_the_name(call: ast.Call, arg: ast.Name, functions: dict[str, ast.FunctionDef]) -> bool:
    target = _callee(call, functions)
    if target is None:
        return False
    params = [a.arg for a in target.args.args if a.arg not in ("self", "cls")]
    index = call.args.index(arg)
    return index < len(params) and params[index] == "networking"


def _takes_networking(call: ast.AST | None, functions: dict[str, ast.FunctionDef]) -> bool:
    target = _callee(call, functions) if isinstance(call, ast.Call) else None
    return target is not None and "networking" in [a.arg for a in (*target.args.args, *target.args.kwonlyargs)]


_NETWORKING_KEYS, _NETWORKING_OTHER_USES = _networking_reads(_GENERATOR_SOURCE)
_GENERATOR_READS = (*sorted(f"networking.{key}" for key in _NETWORKING_KEYS), "backup.sources")


def test_the_generator_reads_only_the_subtrees_listed_here() -> None:
    top_level = set(re.findall(r"\bconfig\.get\(\"([a-z_]+)\"", _GENERATOR_SOURCE))
    assert top_level == {path.split(".")[0] for path in _GENERATOR_READS}, (
        f"the generator reads {sorted(top_level)} from the config; list each subtree in "
        "_GENERATOR_READS so the SOPS check below covers it"
    )


def test_the_generator_reads_networking_key_by_key() -> None:
    """Any other use (iterating it, handing it on under another name) hides keys from the list above."""
    assert "nodes" in _NETWORKING_KEYS, "the generator no longer reads networking.nodes: the parse is stale"
    assert not _NETWORKING_OTHER_USES, (
        f"generator_ansible.py uses `networking` other than by key on lines {_NETWORKING_OTHER_USES}: "
        "read each key by name, or hand it to a function whose parameter is also named `networking`"
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("nw = networking", id="renamed"),
        pytest.param("nw = networking  # site secrets", id="renamed-with-a-comment"),
        pytest.param("def f():\n    return networking", id="returned"),
        pytest.param("for key in networking:\n    pass", id="iterated"),
        pytest.param("networking.items()", id="items"),
        pytest.param("merged = {**networking}", id="unpacked"),
        pytest.param("def helper(cfg):\n    return cfg['vps']\nhelper(networking)", id="handed-on-renamed"),
        pytest.param("external(networking)", id="handed-outside-the-module"),
        pytest.param("def helper(cfg):\n    return cfg['vps']\nhelper(cfg=networking)", id="keyword-renamed"),
        pytest.param("external(networking=networking)", id="keyword-outside-the-module"),
        pytest.param("networking.get(name)", id="a-key-that-is-not-a-constant"),
    ],
)
def test_a_use_that_is_not_a_key_read_is_reported(source: str) -> None:
    assert _networking_reads(source)[1], source


def test_a_key_read_in_any_form_is_found_and_a_hand_off_that_keeps_the_name_is_followed() -> None:
    source = (
        "def helper(node, networking):\n    return networking['ssh_users']\n"
        "a = networking['nodes']\nb = networking.get('vps', {})\nc = networking.get(\"lan_cidr\")\n"
        "helper(a, networking)\nhelper(node=a, networking=networking)\n"
    )
    assert _networking_reads(source) == ({"nodes", "vps", "lan_cidr", "ssh_users"}, [])


def _declared(doc: dict[str, Any]) -> list[str]:
    """The guarded paths a SOPS document declares."""
    declared = []
    for dotted in _GENERATOR_READS:
        node: Any = doc
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            declared.append(dotted)
    return declared


def test_a_secret_under_networking_the_generator_never_reads_is_allowed() -> None:
    """The lab edge's site secrets live at `networking.edge` (#2665); a node override there would not."""
    assert _declared({"networking": {"edge": {"uplink": {"mac": "ENC[...]"}}}}) == []
    assert _declared({"networking": {"nodes": {"rpi4": {"lan_ip": "ENC[...]"}}}}) == ["networking.nodes"]


@pytest.mark.parametrize(
    "path", sorted((_ROOT / "infra" / "config" / "secrets").glob("*.enc.yaml")), ids=lambda p: p.name
)
def test_no_sops_file_declares_what_the_inventory_is_built_from(path: Path) -> None:
    """Key names are plaintext in a SOPS file, so this needs no decryption key."""
    declared = _declared(yaml.safe_load(path.read_text()) or {})
    assert not declared, (
        f"{path.name} declares {declared}. The inventory is generated from plaintext values "
        "only, so these keys would never reach it. Keep them in common.yaml / <env>.yaml."
    )
