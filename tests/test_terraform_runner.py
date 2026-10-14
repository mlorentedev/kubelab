"""Every Terraform invocation goes through one runner (TF-007, #558).

Before the runner, each `tf-*` Make target carried its own copy of the same
sequence: render a tfvars into the module directory, export a token, `cd`,
`terraform init`, the verb, then remove the file in the same shell line so a
failed plan could not leave it behind (TOOL-039). Nine copies of that sequence
drifted the way copies do. The remote backend (TF-007 PR 1b) adds two more
things to every invocation, the backend file and its credentials, and an eleventh
copy of anything is the wrong place to add them.

These tests drive the runner with a recording fake in place of `terraform`, so
what is asserted is the command line, the child's environment and the files on
disk at the moment terraform runs. None of it needs the binary or a credential.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import terraform_runner as tr

REPO = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO / "infra" / "terraform"

SECRET = "secret-sentinel-value"

SECRET_PATHS = (
    "cloudflare.api_token",
    "cloudflare.r2_admin_token",
    "hetzner.api_key",
    "aws.access_key_id",
    "aws.secret_access_key",
    "aws.headscale_preauth_key",
    "aws.headscale_api_key",
    "gcp.billing_account_id",
    "terraform.state.access_key_id",
    "terraform.state.secret_access_key",
)


def _config() -> dict[str, Any]:
    """The real plaintext SSOT, with every secret the roots read set to SECRET."""
    config = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))
    for path in SECRET_PATHS:
        node = config
        *parents, leaf = path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = SECRET
    return config


CONFIG = _config()


def _without(config: dict[str, Any], dotted: str) -> dict[str, Any]:
    """A deep copy of `config` with one key removed."""
    copy = json.loads(json.dumps(config))
    node = copy
    *parents, leaf = dotted.split(".")
    for part in parents:
        node = node[part]
    del node[leaf]
    return copy


# The modules, copied without any state, plan or `.terraform/`: a checkout that
# still holds a local state (msi, before its migration) would otherwise trip the
# local-state guard in every test that is not about it.
TREE = TERRAFORM_DIR


@pytest.fixture(autouse=True, scope="module")
def _tree(tmp_path_factory: pytest.TempPathFactory) -> None:
    global TREE
    TREE = tmp_path_factory.mktemp("terraform")
    shutil.copytree(
        TERRAFORM_DIR,
        TREE,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("*.tfstate", "*.tfstate.*", ".terraform", "*.tfplan"),
    )


def _on_disk(path: Path) -> tuple[bool, int | None]:
    return (True, path.stat().st_mode & 0o777) if path.exists() else (False, None)


class FakeTerraform:
    """Records each call and answers with a scripted exit code per subcommand."""

    def __init__(
        self,
        fail: dict[str, int] | None = None,
        plan_json: dict | None = None,
        stdout: str = "",
        pulls: list[dict | None] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail or {}
        self.plan_json = plan_json if plan_json is not None else {"resource_changes": []}
        self.stdout = stdout
        # What each `state pull` answers, in order; the last one repeats. None
        # is a backend that holds no state yet.
        self.pulls = list(pulls) if pulls is not None else [None]

    def __call__(self, args: list[str], *, env: dict[str, str], capture: bool, quiet: bool) -> tr.Result:
        rest = args[1:] if args[0].startswith("-chdir=") else args
        verb = f"state {rest[1]}" if rest[0] == "state" else rest[0]
        # What exists on disk WHILE terraform runs, for the files the runner
        # promised to remove afterwards.
        var_files = [a.split("=", 1)[1] for a in args if a.startswith("-var-file=")]
        self.calls.append(
            {
                "args": list(args),
                "verb": verb,
                "env": dict(env),
                "capture": capture,
                "quiet": quiet,
                "var_files": {p: _on_disk(Path(p)) for p in var_files},
            }
        )
        rc = self.fail.get(verb, 0)
        # What the real binary does (measured on msi, 2026-10-13): an init that
        # finds a local terraform.tfstate next to a new backend wants to ask
        # whether to copy it, and with -input=false it refuses instead.
        if verb == "init" and args[0].startswith("-chdir="):
            if (Path(args[0].split("=", 1)[1]) / "terraform.tfstate").exists():
                return tr.Result(1, "")
        if verb == "show":
            return tr.Result(rc, json.dumps(self.plan_json))
        if verb == "state pull":
            state = self.pulls.pop(0) if len(self.pulls) > 1 else self.pulls[0]
            return tr.Result(rc, json.dumps(state) if state is not None else "")
        return tr.Result(rc, self.stdout if capture else "")

    def verbs(self) -> list[str]:
        return [c["verb"] for c in self.calls]

    def call(self, verb: str) -> dict[str, Any]:
        [match] = [c for c in self.calls if c["verb"] == verb]
        return match

    def work(self) -> list[str]:
        """The verbs, without the history snapshot's reads."""
        return [v for v in self.verbs() if v != "state pull"]


class FakeAws:
    """Records each aws CLI call, the body file's state at that moment included.

    `objects` is the history a get-object reads from, by key.
    """

    def __init__(self, rc: int = 0, out: str = "", objects: dict[str, dict] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.rc, self.out = rc, out
        self.objects = objects or {}

    def __call__(self, args: list[str], *, env: dict[str, str]) -> tr.Result:
        op = args[args.index("s3api") + 1]
        call: dict[str, Any] = {"args": list(args), "env": dict(env), "op": op}
        self.calls.append(call)
        if op == "get-object":
            key = call["key"] = args[args.index("--key") + 1]
            # The download target as the CLI finds it: it writes into it and keeps its mode.
            call["target_mode"] = _on_disk(Path(args[-1]))[1]
            if key not in self.objects:
                return tr.Result(254, "An error occurred (NoSuchKey) when calling the GetObject operation")
            Path(args[-1]).write_text(json.dumps(self.objects[key]))
            return tr.Result(0, "")
        if op == "put-object":
            body = Path(args[args.index("--body") + 1])
            call.update(
                key=args[args.index("--key") + 1],
                body=(body.stat().st_mode & 0o777, json.loads(body.read_text())) if body.exists() else None,
                body_path=body,
            )
        return tr.Result(self.rc, self.out)

    def puts(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["op"] == "put-object"]


def _run(root: str, action: str, fake: FakeTerraform, tmp_path: Path | None = None, **kwargs: Any) -> int:
    terraform_dir = kwargs.pop("terraform_dir", TREE)
    config = kwargs.pop("config", CONFIG)
    kwargs.setdefault("aws", FakeAws())
    return tr.run(
        root,
        action,
        terraform_dir=terraform_dir,
        load_config=lambda: config,
        terraform=fake,
        **kwargs,
    )


# --------------------------------------------------------------------------- the registry


def test_every_registered_root_is_a_module_on_disk() -> None:
    for name in tr.ROOTS:
        assert (TERRAFORM_DIR / name / "main.tf").is_file(), name


def test_every_module_on_disk_is_a_registered_root() -> None:
    """The other direction. compute/ had no root, so the only way to run the DR
    module was by hand, around the secret handling (review of #2236)."""
    on_disk = {p.parent.name for p in TERRAFORM_DIR.glob("*/main.tf")}
    assert on_disk == set(tr.ROOTS), on_disk ^ set(tr.ROOTS)


@pytest.mark.parametrize("name", sorted(tr.ROOTS))
def test_every_injected_secret_is_a_declared_variable(name: str) -> None:
    """A `TF_VAR_x` with no `variable "x"` is ignored by Terraform without a word."""
    declared = set(re.findall(r'^variable\s+"(\w+)"', (TERRAFORM_DIR / name / "variables.tf").read_text(), re.M))
    assert set(tr.ROOTS[name].secrets) <= declared, set(tr.ROOTS[name].secrets) - declared


@pytest.mark.parametrize("name", sorted(tr.ROOTS))
def test_every_committed_var_file_exists(name: str) -> None:
    """A missing `-var-file` stops the plan before it reads anything; catch it here instead."""
    for var_file in tr.ROOTS[name].var_files:
        assert (TERRAFORM_DIR / name / var_file).is_file(), var_file


def test_an_unknown_root_is_refused_before_anything_runs() -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="unknown root"):
        _run("nope", "plan", fake)
    assert fake.calls == []


def test_an_unknown_action_is_refused_before_anything_runs() -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="unknown action"):
        _run("dns", "taint", fake)
    assert fake.calls == []


# --------------------------------------------------------------------------- init, every time


@pytest.mark.parametrize("action", ["plan", "apply", "destroy", "output", "untaint"])
def test_init_runs_first_and_quietly(action: str) -> None:
    """A fresh clone or worktree has no `.terraform/`; the verb alone fails there."""
    fake = FakeTerraform()
    _run("dns", action, fake, extra=["x"] if action == "untaint" else [])
    assert fake.verbs()[0] == "init"
    assert fake.calls[0]["quiet"]
    assert "-input=false" in fake.calls[0]["args"]


@pytest.mark.parametrize("action", ["plan", "apply", "output", "untaint", "state-list"])
def test_init_always_takes_the_shared_backend_file(action: str) -> None:
    """Without it, init stops and asks for the bucket; `-reconfigure` ignores a
    previous checkout's cached backend and never prompts to migrate."""
    fake = FakeTerraform()
    _run("dns", action, fake, extra=["x"] if action == "untaint" else [])
    args = fake.call("init")["args"]
    assert "-reconfigure" in args
    assert f"-backend-config={(TREE / 'backend.s3.tfbackend').resolve()}" in args


def test_a_failed_init_stops_the_run_and_its_code_reaches_the_caller() -> None:
    fake = FakeTerraform(fail={"init": 3})
    assert _run("gcp", "plan", fake) == 3
    assert fake.verbs() == ["init"]


def test_every_call_targets_the_module_directory() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    for call in fake.calls:
        assert call["args"][0] == f"-chdir={TREE / 'dns'}"


# --------------------------------------------------------------------------- secrets


def test_secrets_reach_the_child_environment_and_never_argv() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    plan = fake.call("plan")
    assert plan["env"]["TF_VAR_cloudflare_api_token"] == SECRET
    assert not any(SECRET in a for a in plan["args"])


def test_r2_uses_the_r2_token_not_the_dns_one() -> None:
    """The DNS token is refused by the R2 bucket API (2026-10-02)."""
    assert tr.ROOTS["r2"].secrets == {"cloudflare_api_token": "cloudflare.r2_admin_token"}
    assert tr.ROOTS["dns"].secrets == {"cloudflare_api_token": "cloudflare.api_token"}


def test_a_missing_secret_is_named_and_nothing_runs() -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match=r"cloudflare\.api_token"):
        _run("dns", "plan", fake, config=_without(CONFIG, "cloudflare.api_token"))
    assert fake.calls == []


# --------------------------------------------------------------------------- the backend's credentials


@pytest.mark.parametrize("action", ["plan", "apply", "output", "state-list"])
def test_the_state_credentials_reach_every_action_as_aws_variables(action: str) -> None:
    fake = FakeTerraform()
    _run("dns", action, fake)
    for call in fake.calls:
        assert call["env"]["AWS_ACCESS_KEY_ID"] == SECRET
        assert call["env"]["AWS_SECRET_ACCESS_KEY"] == SECRET


@pytest.mark.parametrize("path", sorted(tr.STATE_CREDENTIALS.values()))
def test_missing_state_credentials_name_the_bootstrap_and_nothing_runs(path: str) -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match=r"tf-state-bootstrap"):
        _run("dns", "output", fake, config=_without(CONFIG, path))
    assert fake.calls == []


def test_the_aws_provider_takes_its_keys_explicitly_never_from_the_environment() -> None:
    """The backend's R2 pair is in the child's environment as AWS_*; a provider
    reading the environment would present it to AWS."""
    main = (TERRAFORM_DIR / "aws" / "main.tf").read_text(encoding="utf-8")
    provider = re.search(r'^provider "aws" \{(.*?)^\}', main, re.M | re.S)
    assert provider, "no aws provider block"
    body = provider.group(1)
    assert re.search(r"^\s*access_key\s*=\s*var\.aws_access_key_id", body, re.M)
    assert re.search(r"^\s*secret_key\s*=\s*var\.aws_secret_access_key", body, re.M)
    assert "profile" not in body
    assert tr.ROOTS["aws"].secrets == {
        "aws_access_key_id": "aws.access_key_id",
        "aws_secret_access_key": "aws.secret_access_key",
    }


def test_a_plan_of_aws_runs_without_the_retired_headscale_keys() -> None:
    """Retired with aws1 (#1353): the dormant root still plans."""
    config = _without(_without(CONFIG, "aws.headscale_preauth_key"), "aws.headscale_api_key")
    fake = FakeTerraform()
    assert _run("aws", "plan", fake, config=config) == 0
    assert "TF_VAR_tailscale_authkey" not in fake.call("plan")["env"]


def test_an_apply_of_aws_refuses_to_start_without_them() -> None:
    config = _without(CONFIG, "aws.headscale_preauth_key")
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match=r"aws\.headscale_preauth_key.*an apply does not"):
        _run("aws", "apply", fake, config=config)
    assert fake.calls == []


def test_an_apply_of_aws_with_them_passes_them_on() -> None:
    fake = FakeTerraform()
    _run("aws", "apply", fake)
    assert fake.call("plan")["env"]["TF_VAR_tailscale_authkey"] == SECRET


@pytest.mark.parametrize("name", sorted(tr.ROOTS))
def test_every_apply_only_secret_is_a_variable_with_a_default(name: str) -> None:
    """Without a default, a plan that runs without it stops and asks."""
    text = (TERRAFORM_DIR / name / "variables.tf").read_text(encoding="utf-8")
    for variable in tr.ROOTS[name].apply_secrets:
        block = re.search(rf'^variable\s+"{variable}"\s*\{{(.*?)^\}}', text, re.M | re.S)
        assert block and re.search(r"^\s*default\s*=", block.group(1), re.M), variable


SOPS_FILE = REPO / "infra" / "config" / "secrets" / "common.enc.yaml"


def _sops_has(path: str) -> bool:
    node: Any = yaml.safe_load(SOPS_FILE.read_text(encoding="utf-8"))
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


@pytest.mark.parametrize(
    "path",
    sorted({p for r in tr.ROOTS.values() for p in r.secrets.values()} | set(tr.STATE_CREDENTIALS.values())),
)
def test_every_secret_a_run_requires_exists_in_sops(path: str) -> None:
    """The runner reads the merged `common` config. A required path that SOPS
    does not hold fails every run of its root, which is how the aws root's plan
    stayed broken for six weeks after #1353 retired its Headscale keys. Key
    names are plaintext in a SOPS file, so this needs no decryption."""
    assert _sops_has(path), f"{path} is not in {SOPS_FILE.name}"


def test_inherited_aws_and_tf_var_variables_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inputs come from the SSOT only. A shell's `AWS_PROFILE` or a stale
    `TF_VAR_x` would otherwise outrank it without anything saying so."""
    monkeypatch.setenv("AWS_PROFILE", "someone-else")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "stale")
    monkeypatch.setenv("TF_VAR_region", "us-east-1")
    monkeypatch.setenv("KEEP_ME", "1")
    fake = FakeTerraform()
    _run("gcp", "plan", fake)
    env = fake.call("plan")["env"]
    # The only AWS_* left are the state bucket's, from SOPS.
    assert {k for k in env if k.startswith("AWS_")} == set(tr.STATE_CREDENTIALS)
    assert not [k for k in env if k.startswith("TF_VAR_")]
    assert env["KEEP_ME"] == "1"


@pytest.mark.parametrize(
    "name",
    [
        "TF_CLI_ARGS_apply",  # `-auto-approve` here would apply past the plan guard
        "TF_CLI_ARGS",
        "TF_LOG",  # trace logging prints the injected TF_VAR_ values
        "TF_LOG_PATH",
        "TF_WORKSPACE",  # a different state than the one the plan was read against
        "TF_DATA_DIR",
    ],
)
def test_no_inherited_tf_variable_changes_what_terraform_does(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "-auto-approve")
    fake = FakeTerraform()
    _run("dns", "apply", fake)
    assert all(name not in c["env"] for c in fake.calls)


def test_the_plugin_cache_is_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    """It only makes init faster; dropping it would download every provider again."""
    monkeypatch.setenv("TF_PLUGIN_CACHE_DIR", "/cache")
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    assert fake.call("init")["env"]["TF_PLUGIN_CACHE_DIR"] == "/cache"


# --------------------------------------------------------------------------- rendered tfvars


def test_the_rendered_tfvars_exists_while_terraform_runs_private_and_outside_the_module() -> None:
    fake = FakeTerraform()
    _run("gcp", "plan", fake)
    [(path, (existed, mode))] = fake.call("plan")["var_files"].items()
    assert existed and mode == 0o600
    assert not Path(path).is_relative_to(TREE)


@pytest.mark.parametrize(
    ("action", "fake"),
    [
        ("plan", FakeTerraform()),
        ("plan", FakeTerraform(fail={"plan": 1})),
        ("plan", FakeTerraform(fail={"init": 1})),
        ("apply", FakeTerraform()),
        ("apply", FakeTerraform(fail={"apply": 1})),
        (
            "apply",
            FakeTerraform(plan_json={"resource_changes": [{"address": "x.y", "change": {"actions": ["delete"]}}]}),
        ),
    ],
    ids=["plan", "plan-fails", "init-fails", "apply", "apply-fails", "guard-refuses"],
)
def test_the_private_directory_never_outlives_the_run(
    monkeypatch: pytest.MonkeyPatch, action: str, fake: FakeTerraform
) -> None:
    """The directory, not a file in it: it holds the render AND the saved plan,
    and the plan carries the token. Checked even when init fails, where no
    terraform call ever names the file."""
    made: list[Path] = []

    class Recording(tr.tempfile.TemporaryDirectory):  # type: ignore[type-arg]
        def __enter__(self) -> str:
            made.append(Path(self.name))
            return super().__enter__()

    monkeypatch.setattr(tr.tempfile, "TemporaryDirectory", Recording)
    _run("dns", action, fake)
    assert made and not any(p.exists() for p in made), made


def test_the_rendered_tfvars_is_removed_when_terraform_raises() -> None:
    seen: list[str] = []

    def boom(args: list[str], **_: Any) -> tr.Result:
        seen.extend(a.split("=", 1)[1] for a in args if a.startswith("-var-file="))
        if args[1] == "plan":
            raise KeyboardInterrupt
        return tr.Result(0, "")

    with pytest.raises(KeyboardInterrupt):
        tr.run("gcp", "plan", terraform_dir=TREE, load_config=lambda: CONFIG, terraform=boom)
    assert seen and not any(Path(p).exists() for p in seen)


def test_the_dns_root_reads_the_vps_address_from_the_ssot() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    rendered = [p for p in fake.call("plan")["var_files"] if not Path(p).is_relative_to(TREE)]
    assert len(rendered) == 1
    assert tr.ROOTS["dns"].render is not None
    content = tr.ROOTS["dns"].render(tr.Context(CONFIG, TREE / "dns", lambda *_: ""))
    assert content == f'vps_ip = "{CONFIG["networking"]["vps"]["public_ip"]}"\n'


def test_no_committed_var_file_sets_a_rendered_variable() -> None:
    """Two -var-files setting one variable: the last wins, silently, and the
    copy that loses goes stale without anything reading it."""
    dns = (TERRAFORM_DIR / "dns" / "dns.tfvars").read_text(encoding="utf-8")
    assert not re.search(r"^\s*vps_ip\s*=", dns, re.M)


def test_a_renderer_refusing_the_ssot_names_the_key_and_nothing_runs() -> None:
    fake = FakeTerraform()
    config = {**CONFIG, "networking": {}}
    with pytest.raises(tr.RunnerError, match=r"cannot render the dns inputs.*vps"):
        _run("dns", "plan", fake, config=config)
    assert fake.calls == []


def test_committed_var_files_are_passed_from_the_module() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    committed = str(TREE / "dns" / "dns.tfvars")
    assert f"-var-file={committed}" in fake.call("plan")["args"]
    # The render shares its name; the legacy-render cleanup must not take the committed one.
    assert fake.call("plan")["var_files"][committed][0]
    assert Path(committed).is_file()


def test_a_stale_rendered_file_in_the_module_is_removed_first(tmp_path: Path) -> None:
    """Terraform auto-loads `*.auto.tfvars`, so a leftover from the old Make
    targets would still be read, silently, next to the fresh render."""
    module = tmp_path / "vps-firewall"
    module.mkdir()
    stale = module / "vps-firewall.auto.tfvars"
    stale.write_text("inbound_rules = []\n")
    fake = FakeTerraform()
    _run("vps-firewall", "plan", fake, terraform_dir=tmp_path, config=_firewall_config())
    assert not stale.exists()


def _firewall_config() -> dict[str, Any]:
    return {
        **CONFIG,
        "networking": {
            "firewall": {"vps_inbound": [{"port": 22, "proto": "tcp", "description": "ssh"}]},
            "vps": {"hetzner_server_name": "vps", "public_ip": "192.0.2.1"},
        },
    }


# --------------------------------------------------------------------------- apply modes


def test_a_guarded_apply_saves_the_plan_checks_it_and_applies_that_file() -> None:
    fake = FakeTerraform()
    assert _run("dns", "apply", fake) == 0
    assert fake.work() == ["init", "plan", "show", "apply"]
    out = next(a for a in fake.call("plan")["args"] if a.startswith("-out="))
    planfile = out.split("=", 1)[1]
    assert fake.call("show")["args"][-1] == planfile
    assert fake.call("show")["capture"]
    assert fake.call("apply")["args"][-1] == planfile
    assert "-input=false" in fake.call("apply")["args"]
    assert not Path(planfile).exists(), "the saved plan holds the token; it must not outlive the run"


DELETE_PLAN = {
    "resource_changes": [
        {"address": 'cloudflare_record.kubelab_svc["old"]', "change": {"actions": ["delete"]}},
    ]
}


def test_a_guarded_apply_refuses_a_delete_and_never_applies() -> None:
    fake = FakeTerraform(plan_json=DELETE_PLAN)
    assert _run("dns", "apply", fake) == 1
    assert "apply" not in fake.verbs()


def test_allow_destroy_and_a_named_address_open_the_guard() -> None:
    fake = FakeTerraform(plan_json=DELETE_PLAN)
    assert _run("dns", "apply", fake, allow_destroy=True) == 0
    fake = FakeTerraform(plan_json=DELETE_PLAN)
    assert _run("dns", "apply", fake, allowed=['cloudflare_record.kubelab_svc["old"]']) == 0
    assert fake.work()[-1] == "apply"


def test_a_show_without_plan_json_applies_nothing() -> None:
    class NoJson(FakeTerraform):
        def __call__(self, args: list[str], **kw: Any) -> tr.Result:
            result = super().__call__(args, **kw)
            return tr.Result(0, "") if self.calls[-1]["verb"] == "show" else result

    fake = NoJson()
    assert _run("dns", "apply", fake) == 1
    assert "apply" not in fake.verbs()


def test_a_failed_plan_never_reaches_the_guard_or_the_apply() -> None:
    fake = FakeTerraform(fail={"plan": 1})
    assert _run("dns", "apply", fake) == 1
    assert fake.work() == ["init", "plan"]


@pytest.mark.parametrize("name", ["r2", "vps-firewall", "gcp-bootstrap"])
def test_an_interactive_root_asks_before_applying(name: str) -> None:
    """vps-firewall can lock the operator out of the VPS; r2's lock rules cannot
    be lifted by a node; gcp-bootstrap holds the billing guardrails."""
    assert tr.ROOTS[name].apply == "interactive"


def test_an_interactive_apply_leaves_the_prompt_to_terraform() -> None:
    fake = FakeTerraform()
    _run("r2", "apply", fake)
    args = fake.call("apply")["args"]
    assert "-auto-approve" not in args and "-input=false" not in args


def test_only_the_disposable_fixture_applies_and_destroys_unattended() -> None:
    assert {n for n, r in tr.ROOTS.items() if r.apply == "auto"} == {"gcp-killswitch-test"}


def test_the_disposable_fixture_auto_approves() -> None:
    fake = FakeTerraform()
    _run("gcp-killswitch-test", "apply", fake, outputs=lambda root, name: "sa@example.iam.gserviceaccount.com")
    assert "-auto-approve" in fake.call("apply")["args"]


@pytest.mark.parametrize("name", ["dns", "aws", "r2"])
def test_destroy_always_asks_outside_the_fixture(name: str) -> None:
    fake = FakeTerraform()
    _run(name, "destroy", fake)
    assert "-auto-approve" not in fake.call("destroy")["args"]


def test_extra_arguments_reach_the_plan_of_a_guarded_apply() -> None:
    """aws1-replace names its replace; the guard lets exactly that one through."""
    fake = FakeTerraform()
    _run("aws", "apply", fake, extra=["-replace=aws_instance.argo_hub"], allowed=["aws_instance.argo_hub"])
    assert "-replace=aws_instance.argo_hub" in fake.call("plan")["args"]
    assert "-replace=aws_instance.argo_hub" not in fake.call("apply")["args"]


def test_extra_arguments_reach_an_interactive_apply() -> None:
    fake = FakeTerraform()
    _run("r2", "plan", fake, extra=["-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"])
    assert fake.call("plan")["args"][-2:] == ["-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"]


# --------------------------------------------------------------------------- state-only verbs


def test_output_passes_no_var_file_and_its_stdout_is_terraforms_alone() -> None:
    """`$(...)` captures it in Make, so nothing else may print on stdout."""
    fake = FakeTerraform()
    _run("aws", "output", fake, extra=["-raw", "spot_request_id"])
    call = fake.call("output")
    assert call["args"][1:] == ["output", "-raw", "spot_request_id"]
    assert not call["quiet"]


def test_untaint_needs_an_address() -> None:
    with pytest.raises(tr.RunnerError, match="address"):
        _run("dns", "untaint", FakeTerraform())


def test_untaint_touches_state_only() -> None:
    fake = FakeTerraform()
    _run("dns", "untaint", fake, extra=['cloudflare_record.kubelab_svc["chat"]'])
    assert fake.work() == ["init", "untaint"]
    assert not [k for k in fake.call("untaint")["env"] if k.startswith("TF_VAR_")]


def test_output_reads_another_root_through_the_runner() -> None:
    """The fixture's tfvars needs the bootstrap root's service account."""
    fake = FakeTerraform(stdout="sa@example.iam.gserviceaccount.com\n")
    value = tr.output(
        "gcp-bootstrap", "kill_switch_service_account", terraform_dir=TREE, terraform=fake, load_config=lambda: CONFIG
    )
    assert value == "sa@example.iam.gserviceaccount.com"
    assert fake.call("output")["args"][1:] == ["output", "-raw", "kill_switch_service_account"]
    # Another root's state is in R2 as well.
    assert "-reconfigure" in fake.call("init")["args"]
    assert fake.call("output")["env"]["AWS_ACCESS_KEY_ID"] == SECRET


# --------------------------------------------------------------------------- no state the backend does not hold


def _module_copy(tmp_path: Path, root: str) -> Path:
    shutil.copytree(TREE / root, tmp_path / root)
    shutil.copy(TREE / "backend.s3.tfbackend", tmp_path / "backend.s3.tfbackend")
    return tmp_path / root


STATE = {
    "version": 4,
    "lineage": "11111111-aaaa",
    "serial": 7,
    "resources": [
        {"mode": "managed", "type": "cloudflare_record", "name": "a"},
        {"mode": "managed", "type": "cloudflare_record", "name": "b"},
    ],
}


@pytest.mark.parametrize("action", ["plan", "apply", "output", "state-list"])
def test_a_local_state_left_in_a_module_refuses_every_action_but_migrate(tmp_path: Path, action: str) -> None:
    """Against R2 the run would never read it, and a plan would propose
    recreating everything it holds (#1499)."""
    (_module_copy(tmp_path, "dns") / "terraform.tfstate").write_text(json.dumps(STATE))
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match=r"make tf-state-migrate ROOT=dns"):
        _run("dns", action, fake, terraform_dir=tmp_path)
    assert fake.calls == []


def test_the_roots_whose_state_was_lost_are_declared() -> None:
    assert {n for n, r in tr.ROOTS.items() if r.unrecovered} == {"gcp", "gcp-bootstrap", "vps-firewall"}


@pytest.mark.parametrize("action", ["apply", "destroy", "untaint", "restore"])
def test_a_lost_state_refuses_every_write_and_names_its_ticket(action: str) -> None:
    fake = FakeTerraform()
    extra = {"untaint": ["x"], "restore": ["11111111-aaaa/7"]}.get(action, [])
    with pytest.raises(tr.RunnerError, match=r"#2226"):
        _run("gcp", action, fake, extra=extra)
    assert fake.calls == []


def test_a_lost_state_still_plans() -> None:
    fake = FakeTerraform()
    assert _run("gcp", "plan", fake) == 0
    assert "plan" in fake.verbs()


# --------------------------------------------------------------------------- history


def test_a_write_copies_the_state_to_history_before_and_after() -> None:
    before, after = STATE, {**STATE, "serial": 8}
    fake, aws = FakeTerraform(pulls=[before, after]), FakeAws()
    assert _run("dns", "apply", fake, aws=aws) == 0
    verbs = fake.verbs()
    assert verbs.index("state pull") < verbs.index("plan") and verbs[-1] == "state pull"
    assert [c["key"] for c in aws.calls] == [
        "history/dns/11111111-aaaa/7.tfstate",
        "history/dns/11111111-aaaa/8.tfstate",
    ]
    for call, state in zip(aws.calls, (before, after), strict=True):
        assert call["args"][call["args"].index("--if-none-match") + 1] == "*"
        assert call["args"][call["args"].index("--bucket") + 1] == CONFIG["terraform"]["state"]["bucket"]
        assert call["body"] == (0o600, state)
        assert not call["body_path"].exists()
        assert call["env"]["AWS_ACCESS_KEY_ID"] == SECRET
        assert call["env"]["AWS_REQUEST_CHECKSUM_CALCULATION"] == "when_required"


def test_the_history_copy_never_sees_the_shells_aws_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """A session token or profile sent with the state pair fails the put."""
    monkeypatch.setenv("AWS_SESSION_TOKEN", "stale")
    monkeypatch.setenv("AWS_PROFILE", "someone-else")
    aws = FakeAws()
    _run("dns", "apply", FakeTerraform(pulls=[STATE]), aws=aws)
    for call in aws.calls:
        assert "AWS_SESSION_TOKEN" not in call["env"] and "AWS_PROFILE" not in call["env"]
        assert not [k for k in call["env"] if k.startswith("TF_VAR_")]


def test_a_read_writes_no_history() -> None:
    fake, aws = FakeTerraform(pulls=[STATE]), FakeAws()
    _run("dns", "plan", fake, aws=aws)
    assert aws.calls == [] and "state pull" not in fake.verbs()


def test_a_snapshot_already_in_history_is_the_same_state() -> None:
    """Lineage and serial name one state; the conditional put refuses a second copy."""
    aws = FakeAws(rc=254, out="An error occurred (PreconditionFailed) when calling the PutObject operation")
    assert _run("dns", "apply", FakeTerraform(pulls=[STATE]), aws=aws) == 0


@pytest.mark.parametrize(
    "answer", [None, {"version": 4, "lineage": "fresh", "serial": 0, "resources": []}], ids=["empty", "serial-0"]
)
def test_a_backend_with_no_state_yet_has_nothing_to_copy(answer: dict | None) -> None:
    """Serial 0 is what the S3 backend answers before anything was written:
    a locked copy of it would sit in history for a year and hold nothing."""
    aws = FakeAws()
    assert _run("dns", "apply", FakeTerraform(pulls=[answer]), aws=aws) == 0
    assert aws.calls == []


def test_a_failed_copy_before_a_write_stops_it() -> None:
    fake = FakeTerraform(pulls=[STATE])
    assert _run("dns", "apply", fake, aws=FakeAws(rc=1, out="AccessDenied")) == 1
    assert "plan" not in fake.verbs()


def test_a_failed_copy_after_a_write_fails_the_run() -> None:
    class AfterFails(FakeAws):
        def __call__(self, args: list[str], *, env: dict[str, str]) -> tr.Result:
            super().__call__(args, env=env)
            return tr.Result(1 if len(self.calls) > 1 else 0, "boom")

    fake = FakeTerraform(pulls=[STATE, {**STATE, "serial": 8}])
    assert _run("dns", "apply", fake, aws=AfterFails()) == 1
    assert "apply" in fake.verbs()


def test_a_failed_write_is_still_copied_and_its_code_kept() -> None:
    """A failed apply can have written a new serial before it stopped."""
    aws = FakeAws()
    fake = FakeTerraform(fail={"apply": 3}, pulls=[STATE, {**STATE, "serial": 8}])
    assert _run("dns", "apply", fake, aws=aws) == 3
    assert [c["key"].rsplit("/", 1)[1] for c in aws.calls] == ["7.tfstate", "8.tfstate"]


def test_a_state_that_is_not_json_is_refused_without_its_content() -> None:
    class Garbage(FakeTerraform):
        def __call__(self, args: list[str], **kw: Any) -> tr.Result:
            result = super().__call__(args, **kw)
            return tr.Result(0, "not json " + SECRET) if self.calls[-1]["verb"] == "state pull" else result

    with pytest.raises(tr.RunnerError) as exc:
        _run("dns", "apply", Garbage())
    assert SECRET not in str(exc.value)


# --------------------------------------------------------------------------- migrate


def _migrate(tmp_path: Path, fake: FakeTerraform, aws: FakeAws | None = None, **kwargs: Any) -> int:
    return _run("dns", "migrate", fake, terraform_dir=tmp_path, aws=aws or FakeAws(), **kwargs)


def test_migrate_pushes_without_force_checks_the_result_and_retires_the_local_file(tmp_path: Path) -> None:
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    aws = FakeAws()
    fake = FakeTerraform(pulls=[None, None, STATE, STATE])
    assert _migrate(tmp_path, fake, aws) == 0
    push = fake.call("state push")
    assert push["args"][1:] == ["state", "push", str(module / "terraform.migrating.tfstate")]
    assert "-force" not in push["args"]
    assert not (module / "terraform.tfstate").exists()
    assert json.loads((module / "terraform.pre-remote.tfstate").read_text()) == STATE
    assert [c["key"] for c in aws.calls] == ["history/dns/11111111-aaaa/7.tfstate"]
    assert not [k for k in push["env"] if k.startswith("TF_VAR_")]


@pytest.mark.parametrize(
    "remote",
    [
        {**STATE, "resources": []},
        {**STATE, "resources": [STATE["resources"][0], {**STATE["resources"][1], "name": "c"}]},
        {**STATE, "resources": [STATE["resources"][0], {**STATE["resources"][1], "instances": [{"x": 1}]}]},
        {**STATE, "outputs": {"zone": {"value": "other"}}},
    ],
    ids=["fewer-resources", "same-count-other-addresses", "same-addresses-other-attributes", "other-outputs"],
)
def test_migrate_keeps_the_local_file_when_r2_holds_something_else(tmp_path: Path, remote: dict) -> None:
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    fake = FakeTerraform(pulls=[None, remote])
    assert _migrate(tmp_path, fake) == 1
    assert (module / "terraform.tfstate").exists()
    assert not (module / "terraform.pre-remote.tfstate").exists()


EMPTY_REMOTE = {"version": 4, "lineage": "6b5c-fresh", "serial": 0, "resources": [], "outputs": {}}


@pytest.mark.parametrize(
    "landed",
    [{**STATE, "serial": 8}, {**STATE, "lineage": "6b5c-fresh", "serial": 1}],
    ids=["serial-bumped", "backend-lineage-kept"],
)
def test_lineage_and_serial_are_terraforms_business_content_is_the_gate(tmp_path: Path, landed: dict) -> None:
    """Measured on msi, 2026-10-13: the S3 backend writes an empty state with a
    lineage of its own the first time it is touched, and `state push` into an
    empty state imports the resources and keeps that lineage, at serial 1."""
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    aws = FakeAws()
    assert _migrate(tmp_path, FakeTerraform(pulls=[EMPTY_REMOTE, EMPTY_REMOTE, landed, landed]), aws) == 0
    assert (module / "terraform.pre-remote.tfstate").exists()
    assert [c["key"] for c in aws.calls] == [f"history/dns/{landed['lineage']}/{landed['serial']}.tfstate"]


def test_a_remote_that_already_holds_the_content_is_not_pushed_again(tmp_path: Path) -> None:
    """A migration whose push landed but whose rename did not (a killed run,
    or an earlier gate that refused it) finishes without a second push, which
    Terraform would refuse across lineages."""
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    there = {**STATE, "lineage": "6b5c-fresh", "serial": 1}
    fake = FakeTerraform(pulls=[there])
    assert _migrate(tmp_path, fake) == 0
    assert "state push" not in fake.verbs()
    assert (module / "terraform.pre-remote.tfstate").exists()


def test_a_content_mismatch_names_addresses_never_values(tmp_path: Path) -> None:
    module = _module_copy(tmp_path, "dns")
    local = {**STATE, "resources": [{**STATE["resources"][0], "instances": [{"token": SECRET}]}]}
    (module / "terraform.tfstate").write_text(json.dumps(local))
    remote = {**local, "resources": [{**STATE["resources"][0], "instances": [{"token": "other"}]}]}
    assert _migrate(tmp_path, FakeTerraform(pulls=[None, remote])) == 1
    assert tr._differing(local, remote) == ["cloudflare_record.a"]


def test_a_refused_push_keeps_the_local_file(tmp_path: Path) -> None:
    """A different lineage or a lower serial in R2: push refuses, nothing moves."""
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    assert _migrate(tmp_path, FakeTerraform(fail={"state push": 1})) == 1
    assert (module / "terraform.tfstate").exists()


def test_init_never_sees_the_local_file_and_a_failure_puts_it_back(tmp_path: Path) -> None:
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    fake = FakeTerraform(fail={"state push": 1})
    assert _migrate(tmp_path, fake) == 1
    assert fake.verbs()[0] == "init"
    assert json.loads((module / "terraform.tfstate").read_text()) == STATE
    assert not (module / "terraform.migrating.tfstate").exists()


def test_a_migration_cut_short_is_resumed_from_its_staged_file(tmp_path: Path) -> None:
    """A killed migrate leaves the file under its staging name; the next one finishes it."""
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.migrating.tfstate").write_text(json.dumps(STATE))
    assert _migrate(tmp_path, FakeTerraform(pulls=[None, STATE, STATE])) == 0
    assert json.loads((module / "terraform.pre-remote.tfstate").read_text()) == STATE
    assert not (module / "terraform.migrating.tfstate").exists()


@pytest.mark.parametrize("action", ["plan", "apply", "state-list"])
def test_a_staged_file_refuses_every_action_but_migrate(tmp_path: Path, action: str) -> None:
    (_module_copy(tmp_path, "dns") / "terraform.migrating.tfstate").write_text(json.dumps(STATE))
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match=r"make tf-state-migrate ROOT=dns"):
        _run("dns", action, fake, terraform_dir=tmp_path)
    assert fake.calls == []


def test_a_local_file_and_a_staged_one_together_are_refused(tmp_path: Path) -> None:
    module = _module_copy(tmp_path, "dns")
    for name in ("terraform.tfstate", "terraform.migrating.tfstate"):
        (module / name).write_text(json.dumps(STATE))
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="both"):
        _migrate(tmp_path, fake)
    assert fake.calls == []
    assert (module / "terraform.tfstate").exists() and (module / "terraform.migrating.tfstate").exists()


def test_migrate_after_success_is_a_no_op(tmp_path: Path) -> None:
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.pre-remote.tfstate").write_text(json.dumps(STATE))
    fake = FakeTerraform(pulls=[STATE])
    assert _migrate(tmp_path, fake) == 0
    assert "state push" not in fake.verbs()


def test_migrate_with_nothing_to_move_says_so(tmp_path: Path) -> None:
    _module_copy(tmp_path, "dns")
    with pytest.raises(tr.RunnerError, match="nothing to migrate"):
        _migrate(tmp_path, FakeTerraform())


def test_migrate_never_overwrites_an_earlier_pre_remote_copy(tmp_path: Path) -> None:
    module = _module_copy(tmp_path, "dns")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    (module / "terraform.pre-remote.tfstate").write_text("{}")
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="already exists"):
        _migrate(tmp_path, fake)
    assert "state push" not in fake.verbs()


def test_migrate_needs_no_secret_of_the_root(tmp_path: Path) -> None:
    """aws's Headscale keys are retired; its state must still move."""
    module = _module_copy(tmp_path, "aws")
    (module / "terraform.tfstate").write_text(json.dumps(STATE))
    config = _without(_without(CONFIG, "aws.access_key_id"), "aws.headscale_api_key")
    fake = FakeTerraform(pulls=[None, STATE, STATE])
    assert _run("aws", "migrate", fake, terraform_dir=tmp_path, config=config) == 0


# --------------------------------------------------------------------------- state-list


def test_state_list_prints_addresses_only() -> None:
    fake = FakeTerraform()
    assert _run("dns", "state-list", fake) == 0
    assert fake.verbs() == ["init", "state list"]
    assert not [k for k in fake.call("state list")["env"] if k.startswith("TF_VAR_")]


def test_no_action_prints_a_states_values() -> None:
    """`show` and `state show` print attribute values, and a state holds secrets in clear."""
    assert not {"show", "state-show", "pull"} & set(tr.ACTIONS)


# --------------------------------------------------------------------------- history, restore, unlock


def test_history_lists_the_roots_copies_without_running_terraform(capsys: pytest.CaptureFixture[str]) -> None:
    listing = "history/dns/11111111-aaaa/7.tfstate\t2026-10-13T10:00:00Z\n"
    aws, fake = FakeAws(out=listing), FakeTerraform()
    assert _run("dns", "history", fake, aws=aws) == 0
    assert fake.calls == []
    [call] = aws.calls
    assert call["op"] == "list-objects-v2"
    assert call["args"][call["args"].index("--prefix") + 1] == "history/dns/"
    assert "11111111-aaaa/7.tfstate" in capsys.readouterr().out


def test_history_fails_when_the_bucket_refuses() -> None:
    assert _run("dns", "history", FakeTerraform(), aws=FakeAws(rc=254, out="AccessDenied")) == 254


@pytest.mark.parametrize("extra", [[], ["a", "b"]])
def test_unlock_needs_exactly_one_lock_id(extra: list[str]) -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="lock id"):
        _run("dns", "unlock", fake, extra=extra)
    assert fake.calls == []


def test_unlock_releases_the_lock_and_touches_no_state() -> None:
    fake, aws = FakeTerraform(), FakeAws()
    assert _run("dns", "unlock", fake, aws=aws, extra=["c0ffee"]) == 0
    assert fake.call("force-unlock")["args"][1:] == ["force-unlock", "-force", "c0ffee"]
    assert aws.calls == [] and "state pull" not in fake.verbs()


OLD = {**STATE, "serial": 5, "resources": STATE["resources"][:1]}
OLD_KEY = "history/dns/11111111-aaaa/5.tfstate"


def _restore(fake: FakeTerraform, aws: FakeAws, ref: str = "11111111-aaaa/5") -> int:
    return _run("dns", "restore", fake, aws=aws, extra=[ref])


@pytest.mark.parametrize("extra", [[], ["11111111-aaaa"], ["../dns/7"], ["11111111-aaaa/7", "x"]])
def test_restore_refuses_anything_but_one_lineage_and_serial(extra: list[str]) -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="<lineage>/<serial>"):
        _run("dns", "restore", fake, extra=extra)
    assert fake.calls == []


def test_restore_writes_the_old_content_as_the_newest_serial_without_force() -> None:
    """A restore is a new write of an old state, like a revert: the serial moves
    forward, so the history key it lands on is new and nothing needs -force."""
    restored = {**OLD, "serial": 8}
    pushed: list[dict] = []

    class Seeing(FakeTerraform):
        def __call__(self, args: list[str], **kw: Any) -> tr.Result:
            if "push" in args:
                path = Path(args[-1])
                pushed.append({"mode": path.stat().st_mode & 0o777, "state": json.loads(path.read_text())})
            return super().__call__(args, **kw)

    aws = FakeAws(objects={OLD_KEY: OLD})
    fake = Seeing(pulls=[STATE, STATE, restored, restored])
    assert _restore(fake, aws) == 0
    push = fake.call("state push")
    assert "-force" not in push["args"]
    assert pushed == [{"mode": 0o600, "state": restored}]
    assert not Path(push["args"][-1]).exists()
    # Before: the state being replaced. After: the restored one, at its new serial.
    assert [c["key"] for c in aws.puts()] == [
        "history/dns/11111111-aaaa/7.tfstate",
        "history/dns/11111111-aaaa/8.tfstate",
    ]


def test_the_downloaded_copy_is_private_before_the_cli_writes_it_and_gone_after() -> None:
    aws = FakeAws(objects={OLD_KEY: OLD})
    fake = FakeTerraform(pulls=[STATE, STATE, {**OLD, "serial": 8}, {**OLD, "serial": 8}])
    assert _restore(fake, aws) == 0
    [get] = [c for c in aws.calls if c["op"] == "get-object"]
    assert get["target_mode"] == 0o600
    assert not Path(get["args"][-1]).exists()


def test_restore_into_an_empty_backend_keeps_the_serial() -> None:
    aws = FakeAws(objects={OLD_KEY: OLD})
    fake = FakeTerraform(pulls=[None, None, OLD, OLD])
    assert _restore(fake, aws) == 0


def test_restore_of_a_copy_history_does_not_hold_names_it_and_pushes_nothing() -> None:
    fake = FakeTerraform(pulls=[STATE])
    with pytest.raises(tr.RunnerError, match="11111111-aaaa/5"):
        _restore(fake, FakeAws())
    assert "state push" not in fake.verbs()


def test_restore_refuses_a_copy_whose_content_is_not_what_its_key_names() -> None:
    fake = FakeTerraform(pulls=[STATE])
    with pytest.raises(tr.RunnerError, match="does not hold"):
        _restore(fake, FakeAws(objects={OLD_KEY: {**OLD, "serial": 4}}))
    assert "state push" not in fake.verbs()


def test_restore_refuses_another_lineage() -> None:
    """Another lineage is another state; replacing it would take -force, which the runner never passes."""
    other = {**OLD, "lineage": "22222222-bbbb"}
    fake = FakeTerraform(pulls=[STATE])
    with pytest.raises(tr.RunnerError, match="lineage"):
        _restore(fake, FakeAws(objects={"history/dns/22222222-bbbb/5.tfstate": other}), "22222222-bbbb/5")
    assert "state push" not in fake.verbs()


def test_a_restore_that_did_not_arrive_fails() -> None:
    aws = FakeAws(objects={OLD_KEY: OLD})
    assert _restore(FakeTerraform(pulls=[STATE, STATE, STATE, STATE]), aws) == 1


def test_a_restore_never_puts_the_states_content_in_an_error() -> None:
    secret_state = {**OLD, "resources": [{"mode": "managed", "type": "x", "name": SECRET}], "serial": 4}
    with pytest.raises(tr.RunnerError) as exc:
        _restore(FakeTerraform(pulls=[STATE]), FakeAws(objects={OLD_KEY: secret_state}))
    assert SECRET not in str(exc.value)


# --------------------------------------------------------------------------- the real subprocess seam


@pytest.mark.allow_host_clients(reason="spawns a stub `terraform` script first on PATH, never the real binary")
def test_the_default_terraform_seam_passes_the_environment_and_returns_the_code(tmp_path: Path) -> None:
    script = tmp_path / "terraform"
    script.write_text('#!/bin/sh\necho "$TF_VAR_x"\nexit 4\n')
    script.chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", "TF_VAR_x": "hello"}
    result = tr.subprocess_terraform(["version"], env=env, capture=True, quiet=False)
    assert (result.returncode, result.stdout.strip()) == (4, "hello")


def test_a_missing_binary_names_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def absent(*_: Any, **__: Any) -> None:
        raise FileNotFoundError("terraform")

    monkeypatch.setattr(tr.subprocess, "run", absent)
    with pytest.raises(tr.RunnerError, match="dotf tools sync"):
        tr.subprocess_terraform(["version"], env={}, capture=False, quiet=False)


# --------------------------------------------------------------------------- the command


def _invoke(monkeypatch: pytest.MonkeyPatch, argv: list[str], code: int = 0, raises: Exception | None = None):
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    seen: dict[str, Any] = {}

    def fake_run(root: str, action: str, **kwargs: Any) -> int:
        if raises:
            raise raises
        seen.update(root=root, action=action, **kwargs)
        return code

    monkeypatch.setattr(tr, "run", fake_run)
    return CliRunner().invoke(app, ["terraform", "run", *argv]), seen


def test_arguments_after_the_separator_reach_terraform(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Makefile's SCRATCH scope, the `-raw <name>` of an output, an untaint address."""
    result, seen = _invoke(
        monkeypatch, ["r2", "plan", "--", "-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"]
    )
    assert result.exit_code == 0, result.output
    assert (seen["root"], seen["action"]) == ("r2", "plan")
    assert seen["extra"] == ["-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"]


def test_the_guard_options_reach_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    result, seen = _invoke(
        monkeypatch, ["aws", "apply", "--allow", "aws_instance.argo_hub", "--", "-replace=aws_instance.argo_hub"]
    )
    assert result.exit_code == 0, result.output
    assert list(seen["allowed"]) == ["aws_instance.argo_hub"]
    assert seen["extra"] == ["-replace=aws_instance.argo_hub"]
    assert seen["allow_destroy"] is False
    _, seen = _invoke(monkeypatch, ["dns", "apply", "--allow-destroy"])
    assert seen["allow_destroy"] is True and seen["extra"] == []


def test_terraforms_exit_code_is_the_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _invoke(monkeypatch, ["dns", "plan"], code=3)[0].exit_code == 3


def test_a_refused_start_exits_2_and_names_the_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _invoke(monkeypatch, ["nope", "plan"], raises=tr.RunnerError("unknown root 'nope'"))
    assert result.exit_code == 2 and "unknown root" in result.output


# --------------------------------------------------------------------------- the kill-switch proof


def _prove(
    monkeypatch: pytest.MonkeyPatch,
    *,
    apply_rc: int = 0,
    destroy_rc: int = 0,
    project: str = "kubelab-killswitch-1",
    verify_ok=True,
    raises: Exception | None = None,
):
    import typer
    from typer.testing import CliRunner

    from toolkit.cli import infra

    calls: list[str] = []

    def fake_run(root: str, action: str, **_: Any) -> int:
        calls.append(action)
        if raises is not None and action == "apply":
            raise raises
        return {"apply": apply_rc, "destroy": destroy_rc}[action]

    def fake_verify(scratch_project: str) -> None:
        calls.append(f"verify {scratch_project}")
        if not verify_ok:
            raise typer.Exit(1)

    monkeypatch.setattr(tr, "run", fake_run)
    monkeypatch.setattr(tr, "output", lambda root, name, **_: project)
    monkeypatch.setattr(infra, "tf_verify_killswitch", fake_verify)
    result = CliRunner().invoke(infra.app, ["terraform", "killswitch-prove"])
    return result, calls


def test_the_proof_tears_its_project_down_when_it_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, verify_ok=False)
    assert result.exit_code == 1
    assert calls == ["apply", "verify kubelab-killswitch-1", "destroy"]


def test_the_proof_tears_its_project_down_when_it_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch)
    assert result.exit_code == 0 and calls[-1] == "destroy"


def test_a_failed_apply_skips_the_proof_and_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed apply can have created the project before it failed."""
    result, calls = _prove(monkeypatch, apply_rc=1)
    assert result.exit_code == 1 and calls == ["apply", "destroy"]


def test_a_refused_start_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, raises=tr.RunnerError("cannot render"))
    assert result.exit_code == 1 and calls == ["apply", "destroy"]
    # Reported and exited, not a traceback the operator has to read past.
    assert isinstance(result.exception, SystemExit), result.exception


def test_a_proof_that_passed_but_left_its_project_behind_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, destroy_rc=1)
    assert result.exit_code == 1 and calls[-1] == "destroy"


def test_an_empty_project_output_is_a_failure_and_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, project="")
    assert result.exit_code == 1 and calls == ["apply", "destroy"]
