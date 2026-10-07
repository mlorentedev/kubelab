"""A secret must be read from the SOPS store that holds it.

Two nodes hold TWO secret stores at once, for a reason ADR-061 makes deliberate:
Gitea's *environment identity* is prod while the node's `deploy_env` is staging.
So `provision-bee.yml` and `provision-ace2.yml` (ANSIBLE-037) each build `secrets`
from `common + deploy_env` and `gitea_secrets` from `common + gitea_identity_env`,
and which one a variable reads is a real choice. The tests below find every such
playbook rather than naming these two.

Two checks, because the nodes differ. On the Beelink a role writes secrets, so a
read must match the store its write went to. On ace2 nothing writes: a read must
use a store that holds the key, in `common.enc.yaml` or in that store's own env
file (#1975). SOPS encrypts values, not key names, so this needs no decryption.
`SecretSpec.envs` is not that answer: it says which environments must have a key,
not which file holds it, and a key stored in common resolves from every store
(ANSIBLE-033).

**Reading the wrong one does not fail.** It resolves to `''` through the
`| default('', true)` every one of these reads carries, and an empty string is a
perfectly good value. Nothing raises, nothing warns, and the playbook goes green.

The measured consequence, found on `act_runner_token` before its first deploy:

- the role writes the runner's registration token with `--env {{ gitea_identity_env }}`,
  so it lands in `prod.enc.yaml`;
- the playbook read it from `secrets`, which is `common + staging`;
- so the value was never found, and the mint's `when: not act_runner_token` gate was
  true on **every** provision;
- and `gitea actions generate-runner-token` "reuses the latest active token or creates
  a new one, **invalidating all prior tokens for the same scope**"
  (`models/actions/runner_token.go`) — so each re-provision would revoke the token its
  own running runner had registered with, deregistering it silently.

CI would have stopped picking up jobs, and a job matching no runner is QUEUED rather
than failed, so nothing would have reported it. The cause would have been a token mint
several tasks earlier that nobody associates with a runner going offline.

**Why the existing gate test could not see it.**
`test_the_mint_is_gated_on_the_secret_being_absent` asserts the mint task *has* a
`when:`. It does — and a gate that can never be satisfied is indistinguishable from a
working one to that assertion. The reading is the same under both hypotheses, which is
the defect class #1589 names: an instrument is useless here not because it was read
carelessly but because it returns one value in both worlds.

So this file asserts the property that actually matters, and derives BOTH sides from
the files rather than listing known pairs. A hand-maintained list would have to be
updated by the same person who introduces the next mismatch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PLAYBOOKS = REPO / "infra/ansible/playbooks"
SECRETS = REPO / "infra/config/secrets"
PLAYBOOK = PLAYBOOKS / "provision-bee.yml"
ROLE_TASKS = REPO / "infra/ansible/roles/beelink_services/tasks/main.yml"

#: `toolkit secrets set <dotted.path> --env {{ <var> }}` — the write side.
WRITE = re.compile(r"toolkit secrets set\s+(\S+)\s+--env\s+\{\{\s*(\w+)\s*\}\}")

#: `sops -d .../{{ <var> }}.enc.yaml` — binds a decrypt task to an environment.
#: `.*?` and not `\S*` for the path: it contains `{{ playbook_dir }}`, whose inner
#: spaces end a non-whitespace run. That version matched nothing, and every check
#: here loops over the result — so it failed open until the anti-vacuity test below
#: refused an empty store map. Which is the point of having that test.
DECRYPT = re.compile(r"sops -d\s+.*?\{\{\s*(\w+)\s*\}\}\.enc\.yaml")

#: `{{ <store>.<dotted.path> ...` — the read side, in the playbook's `vars:`.
READ = re.compile(r"\{\{\s*(\w+)\.((?:\w+\.)+\w+)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _writes() -> dict[str, str]:
    """Every secret the role writes, mapped to the env VARIABLE it writes under.

    The variable name, not its value: the point is to follow the same indirection
    the playbook follows, so a rename of `gitea_identity_env` moves both sides
    together instead of quietly decoupling them.
    """
    return {path: env_var for path, env_var in WRITE.findall(_text(ROLE_TASKS))}


def _store_for_env_var() -> dict[str, str]:
    """Which merged fact holds which environment's secrets.

    Derived by following the playbook's own chain: a `sops -d {{ VAR }}.enc.yaml`
    task registers a result, and a later `set_fact` combines that register into a
    named store. Hardcoding `secrets`/`gitea_secrets` here would make this file
    agree with today's names rather than with the playbook.
    """
    doc = yaml.safe_load(_text(PLAYBOOK))
    tasks = [t for play in doc for t in (play.get("pre_tasks") or []) + (play.get("tasks") or [])]

    register_for_env: dict[str, str] = {}
    for task in tasks:
        command = task.get("command")
        if isinstance(command, str) and (found := DECRYPT.search(command)) and task.get("register"):
            register_for_env[found.group(1)] = task["register"]

    store_for_env: dict[str, str] = {}
    for task in tasks:
        fact = task.get("set_fact")
        if not isinstance(fact, dict):
            continue
        for store, expression in fact.items():
            for env_var, register in register_for_env.items():
                if f"{register}.stdout" in str(expression):
                    store_for_env[env_var] = store
    return store_for_env


def _reads() -> dict[str, set[str]]:
    """Every `<store>.<path>` dereference in the playbook, path -> stores used."""
    found: dict[str, set[str]] = {}
    for store, path in READ.findall(_text(PLAYBOOK)):
        found.setdefault(path, set()).add(store)
    return found


def test_the_parsers_find_something_to_compare() -> None:
    """Guard the guard, on the values the assertion below actually consumes.

    Every check underneath is a loop over a parsed collection, and an empty
    collection satisfies all of them — an empty expectation is not a weak
    expectation, it matches everything (lesson-416). The floor names one known
    member of each side rather than the whole set, so adding a secret does not
    fail here.
    """
    writes, stores, reads = _writes(), _store_for_env_var(), _reads()

    assert "apps.services.automation.gitea_runner.registration_token" in writes, (
        f"the write parser found {sorted(writes)} and not the runner token, so it is "
        "reading the role differently than intended."
    )
    assert len(stores) >= 2, (
        f"only {stores} resolved; this node's whole point is that it holds TWO stores, "
        "so fewer than two means the decrypt/set_fact chain stopped being followed."
    )
    assert "apps.services.core.gitea.bot_token" in reads, (
        f"the read parser found {len(reads)} dereferences but not a known one, so the "
        "playbook's `vars:` are not being scanned."
    )


def test_every_written_secret_is_read_from_the_store_it_was_written_to() -> None:
    """The property. Written under env X, therefore read from the store built from X."""
    stores = _store_for_env_var()
    reads = _reads()

    wrong: list[str] = []
    for path, env_var in _writes().items():
        expected = stores.get(env_var)
        if expected is None:
            continue  # no store is built from that env var; the test below catches it
        used = reads.get(path)
        if used and expected not in used:
            wrong.append(f"{path}: written under `{env_var}` (store `{expected}`), read from {sorted(used)}")

    assert not wrong, (
        "secrets read from a different store than the one they are written to:\n  "
        + "\n  ".join(wrong)
        + "\n\nThis does not raise. The read resolves to '' through its `default('', true)`, "
        "so any `when: not <var>` gate on it is true forever and the value is re-minted on "
        "every provision. For a Gitea token that is not idle churn — minting invalidates "
        "the previous token, so the node deregisters its own runner while reporting success."
    )


def test_every_write_names_an_environment_the_playbook_builds_a_store_from() -> None:
    """A write under an env nothing reads back is unreachable by construction.

    Weaker than the test above and it catches a different mistake: writing under a
    literal, or under a variable the playbook never turns into a store. There the
    read side is not wrong, it is absent, and the loop above would skip the entry
    entirely rather than fail on it.
    """
    stores = _store_for_env_var()
    orphans = sorted({f"{path} (--env {{{{ {env} }}}})" for path, env in _writes().items() if env not in stores})

    assert not orphans, (
        f"written under an environment variable the playbook builds no secret store from: "
        f"{orphans}.\nKnown stores: {stores}. Nothing will ever read these back, so their "
        "presence gates are permanently open."
    )


@pytest.mark.parametrize("path", sorted(_writes()))
def test_every_written_secret_is_read_back_somewhere(path: str) -> None:
    """Parametrised so a new unread secret is named, not folded into a list.

    A secret the role writes and nobody reads is a mint with no consumer: it runs,
    it reports changed, and its only observable effect is invalidating whatever the
    previous mint produced.
    """
    assert path in _reads(), (
        f"`{path}` is written by the role and dereferenced nowhere in {PLAYBOOK.name}. "
        "Either wire it into the play's `vars:` or stop minting it — an unread secret "
        "still gets re-minted, and for a Gitea token minting revokes the live one."
    )


# ── every playbook with more than one store, judged against what each store holds (#1975) ──


def _holds(env: str, dotted: str) -> bool:
    """Whether `common + env` carries the key, read from the committed SOPS files."""
    for name in ("common", env):
        node = yaml.safe_load((SECRETS / f"{name}.enc.yaml").read_text(encoding="utf-8"))
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            return True
    return False


def _stores(play: dict) -> dict[str, str]:
    """store fact -> the play variable naming its environment, by the same
    decrypt-register-set_fact chain `_store_for_env_var` follows."""
    tasks = (play.get("pre_tasks") or []) + (play.get("tasks") or [])
    register_for_env: dict[str, str] = {}
    for task in tasks:
        command = task.get("command") or task.get("ansible.builtin.command")
        if isinstance(command, str) and (found := DECRYPT.search(command)) and task.get("register"):
            register_for_env[found.group(1)] = task["register"]
    stores: dict[str, str] = {}
    for task in tasks:
        fact = task.get("set_fact") or task.get("ansible.builtin.set_fact")
        if isinstance(fact, dict):
            for store, expression in fact.items():
                for env_var, register in register_for_env.items():
                    if f"{register}.stdout" in str(expression):
                        stores[store] = env_var
    return stores


def _multi_store_plays() -> list[tuple[str, dict, dict[str, str]]]:
    found = []
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(_text(path)) or []:
            if len(stores := _stores(play)) >= 2:
                found.append((path.name, play, stores))
    return found


def test_the_two_store_nodes_are_found() -> None:
    """Anti-vacuity: the parametrised test below runs on what this finds."""
    names = {name for name, _, _ in _multi_store_plays()}
    assert {"provision-bee.yml", "provision-ace2.yml"} <= names, names


@pytest.mark.parametrize(
    ("playbook", "play", "stores"), _multi_store_plays(), ids=[name for name, _, _ in _multi_store_plays()]
)
def test_every_read_uses_a_store_that_holds_that_secret(playbook: str, play: dict, stores: dict[str, str]) -> None:
    """The environment is the play's declared value (`deploy_env: staging`), the one
    the node is documented under. `make provision` passes `-e deploy_env=<ENV>`,
    which overrides it, so a read from `secrets` must hold for the declared one."""
    declared = play.get("vars") or {}
    dumped = yaml.safe_dump(play, width=float("inf"))
    checked = sorted({(store, path) for store, path in READ.findall(dumped) if store in stores})
    assert checked, f"{playbook}: no read from {sorted(stores)} found, so the parser stopped matching"
    wrong: list[str] = []
    for store, path in checked:
        env = declared.get(stores[store])
        if not isinstance(env, str):
            wrong.append(f"{store}.{path}: the play declares no `{stores[store]}` in its vars")
        elif not _holds(env, path):
            wrong.append(f"{store}.{path}: `{store}` is common + {env}, and neither file holds that key")
    assert not wrong, (
        f"{playbook} reads secrets from a store that does not hold them:\n  "
        + "\n  ".join(wrong)
        + "\n\nThis does not raise: the read resolves to '' through `default('')`, and the "
        "node is provisioned with an empty credential while the play reports failed=0."
    )
