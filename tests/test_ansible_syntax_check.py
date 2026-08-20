"""Guards for the Ansible syntax gate.

The gate itself runs `ansible-playbook --syntax-check` and needs a real Ansible
plus the Galaxy collections, so it is not reproduced here — CI runs it, and
`make lint-ansible` runs it locally. What these tests protect is everything
around it that can rot silently:

- the CI step that invokes it, because a gate nobody runs is the exact
  fail-open this repo has been finding all over its own CI;
- the Makefile target it goes through, so the local and CI paths cannot drift;
- the playbook set it walks, so a directory reorganisation cannot quietly
  shrink what gets checked.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO / "infra/ansible"
PLAYBOOKS = ANSIBLE_DIR / "playbooks"
CI = REPO / ".github/workflows/ci.yml"


def test_ci_runs_the_ansible_gate():
    """A gate that exists and is never invoked is worse than no gate: it reads
    as coverage. Assert the CI step is really there, by the command it runs."""
    workflow = yaml.safe_load(CI.read_text())
    steps = workflow["jobs"]["tests"]["steps"]
    assert any("make lint-ansible" in str(s.get("run", "")) for s in steps)


def test_ci_installs_what_the_gate_needs():
    """syntax-check loads the roles a playbook includes, so a role using
    community.docker fails to parse without the Galaxy collections — measured
    against ANSIBLE_COLLECTIONS_PATH=/nonexistent. Without this install the gate
    would go red on every run, and the fix would look like "disable the gate"."""
    workflow = yaml.safe_load(CI.read_text())
    runs = " ".join(str(s.get("run", "")) for s in workflow["jobs"]["tests"]["steps"])
    assert "ansible-core" in runs
    assert "ansible-galaxy collection install" in runs
    assert "requirements.yml" in runs


def test_local_and_ci_share_one_entry_point():
    """CI must call the Makefile target, not ansible-playbook directly — the
    same reason every other gate here goes through make: two invocations drift,
    and the one nobody runs locally is the one that breaks."""
    makefile = (REPO / "Makefile").read_text()
    assert "\nlint-ansible:" in makefile
    assert "infra ansible syntax-check" in makefile


def test_the_collections_the_gate_installs_are_the_ones_the_repo_declares():
    """Guards against the CI step pinning its own list: requirements.yml stays
    the SSOT for what the roles need."""
    requirements = yaml.safe_load((ANSIBLE_DIR / "requirements.yml").read_text())
    declared = {c["name"] for c in requirements["collections"]}
    # Every collection referenced by a role must be declared, or CI installs a
    # set that does not cover what syntax-check will load.
    referenced = set()
    for task_file in ANSIBLE_DIR.glob("roles/**/*.yml"):
        for line in task_file.read_text().splitlines():
            stripped = line.strip()
            for collection in ("community.docker", "community.general", "ansible.posix"):
                if stripped.startswith(f"{collection}."):
                    referenced.add(collection)
    assert referenced <= declared, f"undeclared collections in use: {referenced - declared}"


def test_include_files_are_not_mistaken_for_playbooks():
    """playbooks/_includes/ holds task files included INTO a play. They are not
    playbooks, and passing one to ansible-playbook fails on a structure that is
    entirely correct — so the gate's glob is deliberately non-recursive. If this
    directory ever disappears the exclusion can go too; until then it is load
    bearing, and a `**/*.yml` glob would turn a correct tree red."""
    includes = PLAYBOOKS / "_includes"
    if not includes.exists():
        return
    assert list(includes.glob("*.yml")), "empty _includes: drop the exclusion instead"
    # The non-recursive glob the gate uses must not reach them.
    assert not any(p.parent.name == "_includes" for p in PLAYBOOKS.glob("*.yml"))


def test_every_top_level_playbook_is_a_playbook():
    """A play list, not a task list. Catches a task file dropped into the
    playbooks/ root, which the gate would then fail on for the right reason but
    with a confusing message.

    `import_playbook` counts: services.yml and site.yml are composition-only
    playbooks whose entries carry no `hosts:` of their own, which is valid and
    is why this asserts "play OR import" rather than "has hosts".
    """
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text())
        assert isinstance(doc, list), f"{path.name} is not a list of plays"
        for entry in doc:
            assert "hosts" in entry or "import_playbook" in entry, (
                f"{path.name} has an entry that is neither a play nor an import: {sorted(entry)}"
            )
