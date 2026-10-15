"""TF-013: an unattended apply refuses a plan that deletes or replaces anything.

lesson-543: a Cloudflare create timed out but landed, and Terraform tainted the
record. The next `tf-dns-apply`, which ran with `-auto-approve`, would have
deleted a live record. The runner reads the saved plan's JSON, and the apply then
runs that same file (toolkit/features/terraform_runner.py).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from toolkit.features import terraform_runner as tr
from toolkit.features.terraform_plan_guard import refused, summary

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = (REPO / "Makefile").read_text()


def _plan(*changes: tuple[str, list[str], str | None]) -> dict:
    return {
        "resource_changes": [
            {"address": address, "change": {"actions": actions}, **({"action_reason": reason} if reason else {})}
            for address, actions, reason in changes
        ]
    }


CREATE = ('cloudflare_record.kubelab_svc["chat"]', ["create"], None)
UPDATE = ("cloudflare_record.kubelab_root", ["update"], None)
NOOP = ("cloudflare_record.kubelab_www", ["no-op"], None)
DELETE = ('cloudflare_record.kubelab_svc["old"]', ["delete"], None)
TAINTED = ('cloudflare_record.kubelab_svc["chat"]', ["delete", "create"], "replace_because_tainted")
CBD = ("google_compute_instance.hub", ["create", "delete"], "replace_because_cannot_update")


# --------------------------------------------------------------------------- the rule


@pytest.mark.parametrize("change", [CREATE, UPDATE, NOOP], ids=["create", "update", "no-op"])
def test_creates_updates_and_no_ops_pass(change: tuple) -> None:
    assert refused(_plan(change)) == []


@pytest.mark.parametrize("change", [DELETE, TAINTED, CBD], ids=["delete", "tainted-replace", "create-before-destroy"])
def test_every_delete_is_refused_replace_included(change: tuple) -> None:
    [blocked] = refused(_plan(CREATE, change))
    assert blocked.address == change[0]


def test_a_tainted_replace_is_named_as_one() -> None:
    [blocked] = refused(_plan(TAINTED))
    assert blocked.describe() == 'replace cloudflare_record.kubelab_svc["chat"] (replace_because_tainted)'


def test_allow_destroy_lets_everything_through() -> None:
    assert refused(_plan(DELETE, TAINTED), allow_destroy=True) == []


def test_an_allowed_address_passes_and_no_other() -> None:
    [blocked] = refused(_plan(DELETE, CBD), allowed=frozenset({CBD[0]}))
    assert blocked.address == DELETE[0]


def test_the_summary_counts_a_replace_as_one_add_and_one_destroy() -> None:
    counts = summary(_plan(CREATE, UPDATE, NOOP, TAINTED))
    assert (counts["create"], counts["update"], counts["delete"]) == (2, 1, 1)


# --------------------------------------------------------------------------- the runner's guarded apply


class _Terraform:
    """Answers `show -json` with the given plan; records the verbs it was asked for."""

    def __init__(self, plan: dict) -> None:
        self.plan = plan
        self.verbs: list[str] = []

    def __call__(self, args: list[str], *, env: dict, capture: bool, quiet: bool) -> tr.Result:
        self.verbs.append(args[1])
        return tr.Result(0, json.dumps(self.plan) if args[1] == "show" else "")


def _apply(plan: dict, **kwargs: object) -> tuple[int, _Terraform]:
    fake = _Terraform(plan)
    config = {
        "cloudflare": {"api_token": "token-sentinel"},
        "networking": {"vps": {"public_ip": "192.0.2.1"}},
        "terraform": {"state": {"access_key_id": "k", "secret_access_key": "s"}},
    }
    rc = tr.run(
        "dns", "apply", terraform_dir=REPO / "infra/terraform", load_config=lambda: config, terraform=fake, **kwargs
    )
    return rc, fake


def test_a_refused_plan_exits_non_zero_names_the_taint_and_never_applies(capsys: pytest.CaptureFixture[str]) -> None:
    rc, fake = _apply(_plan(CREATE, TAINTED))
    out = capsys.readouterr().out
    assert rc == 1 and "apply" not in fake.verbs
    assert "replace_because_tainted" in out
    assert "tf-untaint" in out


def test_a_clean_plan_and_an_allowed_one_are_applied() -> None:
    assert _apply(_plan(CREATE, UPDATE))[0] == 0
    assert _apply(_plan(TAINTED), allow_destroy=True)[0] == 0
    rc, fake = _apply(_plan(CBD), allowed=[CBD[0]])
    assert rc == 0 and [v for v in fake.verbs if v != "state"][-1] == "apply"


def test_the_guard_never_echoes_the_plan_it_reads(capsys: pytest.CaptureFixture[str]) -> None:
    """The plan's JSON carries input variables, the provider token included."""
    plan = {**_plan(CREATE, TAINTED), "variables": {"cloudflare_api_token": {"value": "token-sentinel"}}}
    _apply(plan)
    captured = capsys.readouterr()
    assert "token-sentinel" not in captured.out + captured.err


# --------------------------------------------------------------------------- the wiring


def _recipe(target: str) -> str:
    match = re.search(rf"^{re.escape(target)}:.*?\n((?:\t.*\n?)+)", MAKEFILE, re.M)
    assert match, target
    return match.group(1)


@pytest.mark.parametrize("root", ["dns", "gcp", "aws", "compute"])
def test_each_unattended_apply_is_guarded_and_honours_allow_destroy(root: str) -> None:
    assert tr.ROOTS[root].apply == "guarded"
    recipe = _recipe(f"tf-{root}-apply")
    assert f"$(_TF) {root} apply $(_TF_ALLOW)" in recipe
    assert "-auto-approve" not in recipe


@pytest.mark.parametrize(("value", "opens"), [("1", True), ("", False), ("0", False), ("false", False)])
def test_only_allow_destroy_1_opens_the_guard(value: str, opens: bool) -> None:
    """Make's `$(if)` is true for any non-empty string, so `ALLOW_DESTROY=0` must not count."""
    flag = re.search(r"^_TF_ALLOW = (.*)$", MAKEFILE, re.M).group(1)
    out = subprocess.run(
        ["make", "-s", "-f", "-", "show", f"ALLOW_DESTROY={value}"],
        input=f"show:\n\t@echo '{flag}'\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (out == "--allow-destroy") is opens, out


def test_no_make_target_auto_approves() -> None:
    """Unattended apply lives in the runner, declared per root, and only the
    disposable kill-switch fixture has it. A Make line cannot opt out."""
    assert "-auto-approve" not in MAKEFILE


def test_aws1_replace_allows_its_named_replace_and_nothing_else() -> None:
    recipe = _recipe("aws1-replace")
    assert "$(_TF) aws apply --allow aws_instance.argo_hub -- -replace=aws_instance.argo_hub" in recipe
    assert "--allow-destroy" not in recipe and "_TF_ALLOW" not in recipe


def test_untaint_is_a_target_that_touches_state_only() -> None:
    recipe = _recipe("tf-untaint")
    assert "$(_TF) $(ROOT) untaint -- '$(RES)'" in recipe
    assert "apply" not in recipe


def test_every_dns_record_outlives_a_slow_create() -> None:
    """The cause of lesson-543 is the provider's 30s default timeout."""
    text = "".join(p.read_text() for p in sorted((REPO / "infra/terraform/dns").glob("*.tf")))
    records = re.findall(r'^resource "cloudflare_record" "(\w+)" \{(.*?)^\}', text, re.M | re.S)
    assert records
    for name, body in records:
        assert re.search(r'timeouts \{\s*create = "2m"\s*update = "2m"\s*\}', body), name
