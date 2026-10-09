"""Every SSOT path an Ansible file reads through Jinja exists (SSOT-030, #2148).

A playbook merges `common.yaml` with an env's values into `config` (and
`gitea_config`, always prod), and the decrypted SOPS files into `secrets` (and
`gitea_secrets`). Its tasks and its roles' templates then name paths in those
trees as Jinja literals, which nothing resolves before a provision renders
them. #2142 renamed `break_glass.open_webui` to `open-webui`; the toolkit's
readers moved and `provision-ace2.yml` did not, so the first prod provision
failed after Authelia had taken the new redirect, and SSO stayed down until
#2145.

This reads every Jinja expression under `infra/ansible` (the `{{ }}` and
`{% %}` blocks, and the bare expressions of `when:`-like keys) and resolves
each literal path rooted at one of those four names. Secrets resolve against
the SOPS files' key names, which are plaintext, so nothing is decrypted.

- A path must exist in at least one env's merged tree. A key only prod
  declares is read only by prod's playbooks, and a rename removes the path
  from every env, which is the defect.
- A guarded read (`| default(...)`, `is defined`, `.get(`) must resolve too,
  because a renamed key it guards does not fail: it renders the default, and
  the provision goes on with an empty token. A guarded secret may instead name
  a `SECRET_CATALOG` entry not minted yet. A key absent from every env on
  purpose is declared in `ABSENT_BY_DESIGN`, with its reason.
- A chain stops at a subscript by variable (`nodes[item]`) or a method call,
  and only its literal prefix is checked.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ANSIBLE = REPO / "infra/ansible"
VALUES = REPO / "infra/config/values"
SECRETS = REPO / "infra/config/secrets"
ENVS = ("dev", "staging", "prod")

CONFIG_ROOTS = ("config", "gitea_config")
SECRET_ROOTS = ("secrets", "gitea_secrets")

JINJA = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.S)
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
# Keys whose string value Ansible evaluates as a bare Jinja expression.
BARE_KEYS = {"when", "that", "failed_when", "changed_when", "until"}

# A root name used as a value: not an attribute of something else, not a
# quoted string, not a mapping key or a call.
ROOT = re.compile(r"(?<![\w.'\"\]])(" + "|".join(CONFIG_ROOTS + SECRET_ROOTS) + r")\b(?!\s*[:=(])")
SEGMENT = re.compile(
    r"""\.(?!get\()([A-Za-z_]\w*)(?![\w(])"""  # .name, not a method call
    r"""|\[\s*['"]([^'"]+)['"]\s*\]"""  # ['name']
    r"""|\.get\(\s*['"]([^'"]+)['"]"""  # .get('name' ...), optional
)
GUARDED = re.compile(r"\s*(\|\s*(default|d)\b|is\s+(not\s+)?defined\b)")

# Guarded reads of keys no env declares, on purpose. Each is an override knob
# whose default is the real value.
ABSENT_BY_DESIGN = {
    # The toolkit's loader derives it from `apps.contact.email`
    # (`configuration.py`); a playbook reads the raw values, so it falls back
    # to the same key.
    "config.edge.traefik.acme_email",
}


@dataclass(frozen=True)
class Read:
    path: str
    root: str
    segments: tuple[str, ...]
    optional: bool
    hyphen_attr: bool = False

    def __str__(self) -> str:
        return f"{self.path}: {self.root}.{'.'.join(self.segments)}"


def _yaml_expressions(node: Any, key: str | None = None) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _yaml_expressions(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _yaml_expressions(v, key)
    elif isinstance(node, str):
        if key in BARE_KEYS:
            yield node
        for m in JINJA.finditer(node):
            yield m.group(1) or m.group(2)


def expressions(path: Path) -> Iterator[str]:
    text = path.read_text()
    if path.suffix == ".j2":
        for m in JINJA.finditer(JINJA_COMMENT.sub("", text)):
            yield m.group(1) or m.group(2)
        return
    for doc in yaml.safe_load_all(text):
        yield from _yaml_expressions(doc)


def reads_in(expression: str, path: str = "") -> Iterator[Read]:
    for root in ROOT.finditer(expression):
        pos, segments, optional = root.end(), [], False
        while seg := SEGMENT.match(expression, pos):
            segments.append(seg.group(1) or seg.group(2) or seg.group(3))
            pos = seg.end()
            if seg.group(3):
                optional = True
                break
        optional = optional or bool(GUARDED.match(expression, pos))
        hyphen = bool(segments) and bool(re.match(r"-[A-Za-z_]", expression[pos:]))
        yield Read(path, root.group(1), tuple(segments), optional, hyphen)


def _files() -> list[Path]:
    return [p for p in sorted(ANSIBLE.rglob("*")) if p.suffix in {".yml", ".yaml", ".j2"} and p.is_file()]


def _reads() -> list[Read]:
    return [
        read
        for path in _files()
        for expression in expressions(path)
        for read in reads_in(expression, str(path.relative_to(REPO)))
    ]


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        return {**base, **{k: _merge(base[k], v) if k in base else v for k, v in over.items()}}
    return over


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _trees(root: str) -> list[dict]:
    if root in SECRET_ROOTS:
        return [_merge(_load(SECRETS / "common.enc.yaml"), _load(SECRETS / f"{env}.enc.yaml")) for env in ENVS]
    return [_merge(_load(VALUES / "common.yaml"), _load(VALUES / f"{env}.yaml")) for env in ENVS]


def resolves(tree: Any, segments: tuple[str, ...]) -> bool:
    node = tree
    for segment in segments:
        if not isinstance(node, dict):
            return True  # a string or list: the literal path ends here
        if segment not in node:
            return False
        node = node[segment]
    return True


def _catalogued(segments: tuple[str, ...]) -> bool:
    from toolkit.features.secrets_manager import SECRET_CATALOG

    return any(tuple(spec.key_path.split("."))[: len(segments)] == segments for spec in SECRET_CATALOG)


def _key(read: Read) -> str:
    return f"{read.root}.{'.'.join(read.segments)}"


def unresolved(reads: list[Read]) -> list[str]:
    trees = {root: _trees(root) for root in CONFIG_ROOTS + SECRET_ROOTS}
    missing = []
    for read in reads:
        if any(resolves(tree, read.segments) for tree in trees[read.root]):
            continue
        if read.optional and (
            _key(read) in ABSENT_BY_DESIGN or (read.root in SECRET_ROOTS and _catalogued(read.segments))
        ):
            continue
        missing.append(str(read))
    return missing


# --------------------------------------------------------------------------- the extractor


def _paths(expression: str) -> list[tuple[str, str, bool]]:
    return [(r.root, ".".join(r.segments), r.optional) for r in reads_in(expression)]


def test_every_accessor_form_is_read() -> None:
    assert _paths(" gitea_config.apps.services.security.authelia.break_glass['open-webui'].email ") == [
        ("gitea_config", "apps.services.security.authelia.break_glass.open-webui.email", False)
    ]
    assert _paths(" config.networking.nodes.ace2.get('tailscale_ip', '') ") == [
        ("config", "networking.nodes.ace2.tailscale_ip", True)
    ]
    assert _paths(" secrets.backup.r2.access_key_id | default('') ") == [("secrets", "backup.r2.access_key_id", True)]
    assert _paths(" config.edge.traefik.acme_email is defined ") == [("config", "edge.traefik.acme_email", True)]


def test_a_chain_stops_at_a_variable_subscript_or_a_method() -> None:
    assert _paths(" config.networking.nodes[item].location ") == [("config", "networking.nodes", False)]
    assert _paths(" config.apps.services.items() ") == [("config", "apps.services", False)]


def test_what_is_not_a_root_read_is_skipped() -> None:
    assert _paths(" hostvars.localhost.config.apps ") == []
    assert _paths(" _node_config.apps ") == []
    assert _paths(" 'config.yaml' ") == []


def test_a_jinja_comment_and_a_yaml_comment_are_not_read(tmp_path: Path) -> None:
    template = tmp_path / "t.j2"
    template.write_text("{# config.gone.away #}{{ config.apps.x }}\n")
    playbook = tmp_path / "p.yml"
    playbook.write_text("# {{ config.gone.away }}\n- when: config.global.y\n  debug: {msg: '{{ secrets.z }}'}\n")
    assert list(expressions(template)) == [" config.apps.x "]
    assert sorted(expressions(playbook)) == [" secrets.z ", "config.global.y"]


def test_a_renamed_path_is_reported_and_a_guarded_leaf_is_not() -> None:
    def read(expression: str) -> list[Read]:
        return list(reads_in(expression, "fixture"))

    assert unresolved(read(" config.apps.services.security.authelia.break_glass['open_webui'].email ")) == [
        "fixture: config.apps.services.security.authelia.break_glass.open_webui.email"
    ]
    # A guard does not excuse a rename: it would render the default.
    assert unresolved(read(" secrets.apps.services.core.gitea.review_token | default('') ")) != []
    assert unresolved(read(" config.edge.traefik.no_such_leaf | default('x') ")) != []
    assert unresolved(read(" config.edge.traefik.acme_email | default('x') ")) == []
    # Declared absent is not a licence to read it unguarded.
    assert unresolved(read(" config.edge.traefik.acme_email ")) != []
    assert unresolved(read(" secrets.apps.services.ai.hermes_kubelab.slack_bot_tokn ")) != []


# --------------------------------------------------------------------------- the repository


@pytest.fixture(scope="module")
def reads() -> list[Read]:
    return _reads()


def test_the_scan_finds_the_reads_it_exists_for(reads: list[Read]) -> None:
    found = {(r.root, ".".join(r.segments)) for r in reads}
    assert ("gitea_config", "apps.services.security.authelia.break_glass.open-webui.email") in found
    assert ("gitea_secrets", "apps.services.core.gitea.bot_token") in found
    assert any(r.root == "secrets" for r in reads)
    assert len(reads) > 300, len(reads)


def test_every_ssot_path_ansible_reads_exists(reads: list[Read]) -> None:
    missing = unresolved(reads)
    assert not missing, f"SSOT paths no env declares: {missing}"


def test_a_hyphenated_key_is_never_read_by_attribute(reads: list[Read]) -> None:
    """`x.open-webui` parses as a subtraction, so the read stops at `x`."""
    offending = [str(r) for r in reads if r.hyphen_attr]
    assert not offending, offending


def test_each_declared_absence_is_still_read_and_still_absent(reads: list[Read]) -> None:
    """An exemption nobody reads, or for a key some env now declares, is stale."""
    read_keys = {_key(r) for r in reads if r.optional}
    trees = _trees("config")
    for key in ABSENT_BY_DESIGN:
        assert key in read_keys, f"{key} is exempt but nothing reads it"
        segments = tuple(key.split(".")[1:])
        assert not any(resolves(tree, segments) for tree in trees), f"{key} is declared now; drop the exemption"
