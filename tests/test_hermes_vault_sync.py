"""The host commits and pushes the agent's vault zone (ADR-068 D4 as amended
2026-10-08, spec AI-009 AC6).

The sync script runs against a real bare repository standing in for the vault's
remote, with a second clone as the other writers. These are git's verdicts on
the rendered script, not a reading of it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

from tests.test_agent_stack_role import _environment, _resolved, _tasks

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
HERMES = COMMON["apps"]["services"]["ai"]["hermes_kubelab"]
ZONE = HERMES["vault_zone"]
SYNC = HERMES["vault_sync"]
BRANCH = SYNC["branch"]


def _env() -> Environment:
    return _environment()


def _render(name: str, **overrides: object) -> str:
    env = _env()
    return env.get_template(name).render(**{**_resolved(env), **overrides})


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, env=_git_env())


def _git_env() -> dict[str, str]:
    # The unit's own: no configuration from the home or the system.
    return {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def _write(repo: Path, path: str, text: str = "change\n") -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)


class Vault:
    """A remote, the clone the script owns, and another writer's clone."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.remote = tmp / "origin.git"
        self.clone = tmp / "agent" / "vault"
        self.other = tmp / "other"
        self.bin = tmp / "bin"
        subprocess.run(["git", "init", "-q", "--bare", "-b", BRANCH, str(self.remote)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.other)], check=True, env=_git_env())
        for key, value in (("user.name", "operator"), ("user.email", "op@example.test"), ("commit.gpgsign", "false")):
            _git(self.other, "config", key, value)
        _write(self.other, "10_projects/kubelab/roadmap.md", "seed\n")
        _write(self.other, f"{ZONE}/notes.md", "seed\n")
        self.other_commit("seed")
        self.clone.parent.mkdir()
        self.clone.mkdir(mode=0o700)  # what the role creates for ReadWritePaths
        hooks = tmp / "hooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text(_render("pre-commit-zone.sh.j2", agent_stack_vault_zone=ZONE))
        (hooks / "pre-commit").chmod(0o755)
        libexec = tmp / "libexec"
        libexec.mkdir()
        self.script = libexec / "vault-sync"
        self.script.write_text(
            _render(
                "vault-sync.sh.j2",
                agent_stack_vault_clone=str(self.clone),
                agent_stack_vault_zone=ZONE,
                agent_stack_vault_hooks=str(hooks),
                agent_stack_vault_libexec=str(libexec),
                agent_stack_hermes={**HERMES, "vault_sync": {**SYNC, "remote": self.remote.as_uri()}},
            )
        )
        self.script.chmod(0o755)
        # pgrep would see every git of this user on the machine running the tests.
        self.bin.mkdir()
        self.pgrep(found=False)

    def pgrep(self, *, found: bool) -> None:
        (self.bin / "pgrep").write_text(f"#!/bin/sh\nexit {0 if found else 1}\n")
        (self.bin / "pgrep").chmod(0o755)

    def sync(self) -> subprocess.CompletedProcess[str]:
        env = {**_git_env(), "PATH": f"{self.bin}:{os.environ['PATH']}"}
        return subprocess.run([str(self.script)], capture_output=True, text=True, check=False, env=env)

    def other_commit(self, message: str) -> str:
        _git(self.other, "add", "-A")
        assert _git(self.other, "commit", "-q", "-m", message).returncode == 0
        assert _git(self.other, "push", "-q", "origin", f"HEAD:{BRANCH}").returncode == 0
        return self.head()

    def head(self) -> str:
        return _git(self.remote, "rev-parse", BRANCH).stdout.strip()

    def files(self, rev: str) -> list[str]:
        out = _git(self.remote, "diff-tree", "--no-commit-id", "--name-only", "-r", rev).stdout
        return out.split()


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path)


@pytest.fixture
def synced(vault: Vault) -> Vault:
    assert vault.sync().returncode == 0
    return vault


# --------------------------------------------------------------------------- the run


def test_the_first_run_clones_and_commits_nothing(vault: Vault) -> None:
    seed = vault.head()
    result = vault.sync()
    assert result.returncode == 0, result.stderr
    assert (vault.clone / ZONE).is_dir()
    assert vault.head() == seed


def test_a_change_in_the_zone_is_pushed_as_the_agent(synced: Vault) -> None:
    _write(synced.clone, f"{ZONE}/jobs/digest.md")
    result = synced.sync()
    assert result.returncode == 0, result.stderr
    head = synced.head()
    assert synced.files(head) == [f"{ZONE}/jobs/digest.md"]
    author = _git(synced.remote, "log", "-1", "--format=%an <%ae>", head).stdout.strip()
    assert author == f"{SYNC['author_name']} <{SYNC['author_email']}>"


def test_a_run_with_nothing_to_sync_makes_no_commit(synced: Vault) -> None:
    before = synced.head()
    assert synced.sync().returncode == 0
    assert synced.head() == before


def test_others_writing_elsewhere_are_fast_forwarded_never_merged(synced: Vault) -> None:
    _write(synced.other, "10_projects/kubelab/roadmap.md", "theirs\n")
    theirs = synced.other_commit("theirs")
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    assert synced.sync().returncode == 0
    head = synced.head()
    assert _git(synced.remote, "rev-parse", f"{head}^").stdout.strip() == theirs
    assert _git(synced.remote, "rev-list", "--merges", BRANCH).stdout == ""


def test_a_commit_a_dead_run_left_unpushed_is_made_again_on_the_new_tip(synced: Vault) -> None:
    """Power cut between commit and push, then others moved the remote: a pull
    --ff-only alone would be stuck on that commit for good."""
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    _git(synced.clone, "add", "-A")
    _git(synced.clone, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "-m", "unpushed")
    _write(synced.other, "10_projects/kubelab/roadmap.md", "theirs\n")
    theirs = synced.other_commit("theirs")
    result = synced.sync()
    assert result.returncode == 0, result.stderr
    head = synced.head()
    assert _git(synced.remote, "rev-parse", f"{head}^").stdout.strip() == theirs
    assert synced.files(head) == [f"{ZONE}/notes.md"]


def test_a_stale_index_lock_is_removed(synced: Vault) -> None:
    (synced.clone / ".git/index.lock").touch()
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    assert synced.sync().returncode == 0
    assert synced.files(synced.head()) == [f"{ZONE}/notes.md"]


def test_a_lock_is_left_while_a_git_of_this_user_runs(synced: Vault) -> None:
    (synced.clone / ".git/index.lock").touch()
    synced.pgrep(found=True)
    assert synced.sync().returncode == 75
    assert (synced.clone / ".git/index.lock").exists()


# --------------------------------------------------------------------------- the boundary


def test_a_change_outside_the_zone_fails_and_pushes_nothing(synced: Vault) -> None:
    before = synced.head()
    _write(synced.clone, "10_projects/kubelab/roadmap.md", "ours\n")
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    result = synced.sync()
    assert result.returncode == 1
    assert "10_projects/kubelab/roadmap.md" in result.stderr
    assert synced.head() == before


def test_an_unpushed_commit_outside_the_zone_fails_and_pushes_nothing(synced: Vault) -> None:
    before = synced.head()
    _write(synced.clone, "10_projects/kubelab/roadmap.md", "ours\n")
    _git(synced.clone, "add", "-A")
    _git(synced.clone, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--no-verify", "-m", "stray")
    result = synced.sync()
    assert result.returncode == 1
    assert synced.head() == before


def test_the_push_refuses_outside_the_zone_even_without_the_recovery_step(synced: Vault) -> None:
    """The last check stands alone: with the step that takes unpushed commits
    back edited out of the script, a stray commit still never reaches the remote."""
    script = synced.script.read_text()
    begin = script.index('if [ "$(vgit rev-parse HEAD)" != "$base" ]; then')
    end = script.index("fi\n", begin) + len("fi\n")
    synced.script.write_text(script[:begin] + script[end:])
    before = synced.head()
    _write(synced.clone, "10_projects/kubelab/roadmap.md", "ours\n")
    _git(synced.clone, "add", "-A")
    _git(synced.clone, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--no-verify", "-m", "stray")
    result = synced.sync()
    assert result.returncode == 1
    assert "refusing to push" in result.stderr
    assert synced.head() == before


def test_upstream_changing_a_file_the_agent_changed_fails_instead_of_merging(synced: Vault) -> None:
    _write(synced.other, f"{ZONE}/notes.md", "theirs\n")
    theirs = synced.other_commit("theirs")
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    assert synced.sync().returncode == 1
    assert synced.head() == theirs
    assert (synced.clone / ZONE / "notes.md").read_text() == "ours\n"


def test_a_remote_that_moved_during_the_push_is_left_to_the_next_run(synced: Vault) -> None:
    _write(synced.other, "10_projects/kubelab/roadmap.md", "theirs\n")
    _git(synced.other, "add", "-A")
    _git(synced.other, "commit", "-q", "-m", "theirs")
    _git(synced.other, "push", "-q", "origin", "HEAD:refs/heads/side")
    # Lands `side` on the branch and refuses this push, as a writer winning the race would.
    hook = synced.remote / "hooks/pre-receive"
    hook.write_text(
        f'#!/bin/sh\nenv -i PATH="$PATH" git --git-dir="$PWD" update-ref refs/heads/{BRANCH} refs/heads/side\nexit 1\n'
    )
    hook.chmod(0o755)
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    assert synced.sync().returncode == 75
    hook.unlink()
    assert synced.sync().returncode == 0
    head = synced.head()
    assert synced.files(head) == [f"{ZONE}/notes.md"]
    assert (
        _git(synced.remote, "rev-parse", f"{head}^").stdout.strip()
        == _git(synced.remote, "rev-parse", "side").stdout.strip()
    )


def test_a_refused_push_with_the_remote_unmoved_fails(synced: Vault) -> None:
    hook = synced.remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    _write(synced.clone, f"{ZONE}/notes.md", "ours\n")
    assert synced.sync().returncode == 1


def test_the_token_is_in_neither_the_remote_url_nor_the_clone_config(synced: Vault) -> None:
    config = (synced.clone / ".git/config").read_text()
    assert "credential" not in config
    assert _git(synced.clone, "remote", "get-url", "origin").stdout.strip() == synced.remote.as_uri()
    assert SYNC["remote"].startswith("https://") and "@" not in SYNC["remote"]


def test_the_credential_helper_answers_get_from_systemds_credential(tmp_path: Path) -> None:
    helper = tmp_path / "vault-credential"
    helper.write_text(_render("vault-credential.sh.j2"))
    helper.chmod(0o755)
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "vault-token").write_text("token-sentinel\n")
    env = {**os.environ, "CREDENTIALS_DIRECTORY": str(creds)}
    get = subprocess.run([str(helper), "get"], capture_output=True, text=True, env=env, check=True)
    assert get.stdout == "username=x-access-token\npassword=token-sentinel\n"
    for op in ("store", "erase"):
        out = subprocess.run([str(helper), op], capture_output=True, text=True, env=env, check=True)
        assert out.stdout == ""


# --------------------------------------------------------------------------- the role


def _unit(name: str) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in _render(name).splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            keys.setdefault(key, []).append(value)
    return keys


def test_the_unit_runs_as_the_agent_and_takes_the_token_from_systemd() -> None:
    context = _resolved(_env())
    unit = _unit("vault-sync.service.j2")
    assert unit["User"] == [context["agent_stack_agent_user"]]
    assert unit["LoadCredential"] == [f"vault-token:{context['agent_stack_vault_token_file']}"]
    assert unit["OnFailure"] == ["kubelab-notify@%n.service"]
    assert unit["SuccessExitStatus"] == ["75"]
    assert "GIT_CONFIG_GLOBAL=/dev/null" in unit["Environment"][0]
    assert unit["ReadWritePaths"] == [context["agent_stack_vault_clone"]]


def test_the_timer_runs_at_boot_and_at_the_declared_interval() -> None:
    timer = _unit("vault-sync.timer.j2")
    assert timer["OnUnitActiveSec"] == [SYNC["interval"]]
    assert "OnBootSec" in timer


def test_the_token_file_is_roots_and_never_logged() -> None:
    task = next(t for t in _tasks() if t.get("name") == "Write the vault token for systemd to hand over")
    copy = task["ansible.builtin.copy"]
    assert (copy["owner"], copy["mode"]) == ("root", "0600")
    assert task["no_log"] is True
    install = next(t for t in _tasks() if t.get("name") == "Install the vault sync and its credential helper")
    assert install["ansible.builtin.template"]["owner"] == "root"
    assert {i["src"] for i in install["loop"]} == {"vault-sync.sh.j2", "vault-credential.sh.j2"}


def test_the_clone_is_outside_the_gateways_data_directory() -> None:
    context = _resolved(_env())
    clone = Path(context["agent_stack_vault_clone"])
    assert Path(context["agent_stack_hermes_home"]) not in (clone, *clone.parents)


def _config(**overrides: object) -> dict:
    return yaml.safe_load(_render("hermes-config.yaml.j2", **overrides))


def test_the_sandbox_mounts_nothing_without_the_vault_token() -> None:
    assert "docker_volumes" not in _config(agent_stack_vault_configured="False")["terminal"]


def test_the_sandbox_sees_the_vault_read_only_and_only_its_zone_writable() -> None:
    context = _resolved(_env())
    clone, mount = context["agent_stack_vault_clone"], SYNC["mount"]
    volumes = _config(agent_stack_vault_configured="True")["terminal"]["docker_volumes"]
    assert volumes == [f"{clone}:{mount}:ro", f"{clone}/{ZONE}:{mount}/{ZONE}:rw"]


def test_the_deny_list_is_evaluated_on_the_path_the_runtime_takes() -> None:
    """A host path in the sandbox turns every guard back on; the evaluator's
    `docker` models the sandbox without one, so it would measure the wrong path."""
    env = _env()
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    expr = defaults["_agent_stack_hermes_env_type"]
    # As Ansible hands it over: the rendered default, a string.
    assert env.from_string(expr).render(agent_stack_vault_configured="True") == "local"
    assert env.from_string(expr).render(agent_stack_vault_configured="False") == "docker"
    assert "{{ _agent_stack_hermes_env_type }}" in defaults["_agent_stack_hermes_evaluate"]


def test_a_changed_config_removes_the_sandboxes_made_from_the_old_one() -> None:
    task = next(t for t in _tasks() if t.get("name") == "Remove the sandboxes made from the previous config")
    assert "label=hermes-agent=1" in task["ansible.builtin.shell"]["cmd"]
    assert task["when"] == "_agent_stack_hermes_config.changed"


def test_the_clone_is_provisioned_before_hermes_mounts_it() -> None:
    main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    imports = [t.get("ansible.builtin.import_tasks") for t in main if "ansible.builtin.import_tasks" in t]
    assert imports.index("vault_zone.yml") < imports.index("hermes.yml")
