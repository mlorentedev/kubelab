"""TF-013: an unattended apply refuses a plan that deletes or replaces anything.

lesson-543: a Cloudflare create timed out but landed, and Terraform tainted the
record. The next `tf-dns-apply`, which ran with `-auto-approve`, would have
deleted a live record. The guard reads the saved plan's JSON, and the apply then
runs that same file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

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


# --------------------------------------------------------------------------- the command


def _guard(plan: dict, *args: str) -> object:
    from toolkit.cli.infra import app

    return CliRunner().invoke(app, ["terraform", "plan-guard", "-", *args], input=json.dumps(plan))


def test_the_command_exits_non_zero_on_a_refused_plan_and_names_it() -> None:
    result = _guard(_plan(CREATE, TAINTED))
    assert result.exit_code == 1
    assert "replace_because_tainted" in result.output
    assert "tf-untaint" in result.output


def test_the_command_passes_a_clean_plan_and_an_allowed_one() -> None:
    assert _guard(_plan(CREATE, UPDATE)).exit_code == 0
    assert _guard(_plan(TAINTED), "--allow-destroy").exit_code == 0
    assert _guard(_plan(CBD), "--allow", CBD[0]).exit_code == 0


def test_the_command_never_echoes_the_plan_it_reads() -> None:
    """The plan's JSON carries input variables, the provider token included."""
    plan = {**_plan(CREATE), "variables": {"cloudflare_api_token": {"value": "token-sentinel"}}}
    assert "token-sentinel" not in _guard(plan).output


# --------------------------------------------------------------------------- the wiring


def _recipe(target: str) -> str:
    match = re.search(rf"^{re.escape(target)}:.*?\n((?:\t.*\n?)+)", MAKEFILE, re.M)
    assert match, target
    return match.group(1)


@pytest.mark.parametrize("target", ["tf-dns-apply", "tf-gcp-apply", "tf-aws-apply"])
def test_each_unattended_apply_goes_through_the_guard(target: str) -> None:
    recipe = _recipe(target)
    assert "$(call _tf_guarded_apply," in recipe
    assert "-auto-approve" not in recipe


def test_the_guarded_apply_runs_the_plan_it_checked_and_removes_it() -> None:
    body = re.search(r"^define _tf_guarded_apply\n(.*?)^endef", MAKEFILE, re.M | re.S).group(1)
    assert '-out="$$_p/plan"' in body
    assert 'terraform show -json "$$_p/plan" | $(TOOLKIT) infra terraform plan-guard -' in body
    assert 'terraform apply -input=false "$$_p/plan"' in body
    assert "trap 'rm -rf \"$$_p\"' EXIT" in body
    assert "$(if $(ALLOW_DESTROY),--allow-destroy)" in body


def test_only_the_named_replace_and_the_test_fixture_keep_auto_approve() -> None:
    """aws1-replace asks for its replace by address, and the killswitch test
    creates and destroys its own fixture. Any other auto-approve is unguarded."""
    holders = set()
    for match in re.finditer(r"^([\w.-]+):[^\n]*\n((?:\t.*\n?)+)", MAKEFILE, re.M):
        if re.search(r"terraform (apply|destroy) -auto-approve", match.group(2)):
            holders.add(match.group(1))
    assert holders == {"aws1-replace", "gcp-killswitch-prove", "gcp-killswitch-teardown"}, holders


def test_untaint_is_a_target_that_touches_state_only() -> None:
    recipe = _recipe("tf-untaint")
    assert "terraform untaint '$(RES)'" in recipe
    assert "apply" not in recipe


def test_every_dns_record_outlives_a_slow_create() -> None:
    """The cause of lesson-543 is the provider's 30s default timeout."""
    text = "".join(p.read_text() for p in sorted((REPO / "infra/terraform/dns").glob("*.tf")))
    records = re.findall(r'^resource "cloudflare_record" "(\w+)" \{(.*?)^\}', text, re.M | re.S)
    assert records
    for name, body in records:
        assert re.search(r'timeouts \{\s*create = "2m"\s*update = "2m"\s*\}', body), name
