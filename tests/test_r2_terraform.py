"""The R2 Terraform root is rendered from `backup.sources`, never declared twice.

BACKUP-057 PR 2. One bucket per node, each under a lock rule that no node token
can change. What this file pins, and why each matters:

- one bucket per `backup.sources` key, so a node added to the SSOT gets its own
  bucket and no node shares one (the isolation half, AC1/AC2);
- the lock covers exactly `data/`, `snapshots/`, `keys/` and `config`. `locks/`
  and `index/` stay out: `backup` deletes its lock file on every run and `prune`
  rewrites the index, so locking either breaks every scheduled ship;
- R, the lock's age, is shorter than the `--keep-within` the nodes prune with.
  If it were not, `prune` would try to delete a pack the lock still holds and
  the ship would fail every night;
- the node buckets cannot be destroyed by a plan, and the scratch bucket can.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
import yaml

from toolkit.features import r2_tfvars

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra" / "config" / "values" / "common.yaml"
ROLE_DEFAULTS = REPO / "infra" / "ansible" / "roles" / "node_backup" / "defaults" / "main.yml"
ROOT = REPO / "infra" / "terraform" / "r2"


def _common() -> dict:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))


def _assigned(rendered: str, name: str) -> str:
    for line in rendered.splitlines():
        head, _, tail = line.partition("=")
        if head.strip() == name:
            return tail.strip()
    raise AssertionError(f"{name!r} is not assigned in:\n{rendered}")


def _node_buckets(rendered: str) -> dict[str, str]:
    block = re.search(r"^node_buckets\s*=\s*\{\n(.*?)^\}", rendered, re.M | re.S)
    assert block, f"node_buckets is not a map in:\n{rendered}"
    return dict(re.findall(r'^\s*"([^"]+)"\s*=\s*"([^"]+)"', block.group(1), re.M))


@pytest.fixture
def config() -> dict:
    return {
        "backup": {
            "r2": {"account_id": "0123abcd", "lock_retention_days": 30},
            "sources": {"alpha": {}, "beta": {}},
        }
    }


class TestOneBucketPerNode:
    def test_every_backup_source_gets_a_bucket_named_after_it(self) -> None:
        common = _common()
        buckets = _node_buckets(r2_tfvars.render(common))
        assert buckets == {node: f"kubelab-backup-{node}" for node in common["backup"]["sources"]}

    def test_a_node_added_to_the_ssot_gets_its_own_bucket(self, config: dict) -> None:
        config["backup"]["sources"]["gamma"] = {}
        assert _node_buckets(r2_tfvars.render(config))["gamma"] == "kubelab-backup-gamma"

    def test_a_node_name_that_is_not_an_hcl_identifier_still_renders(self, config: dict) -> None:
        """Map keys are quoted: an unquoted key that starts with a digit is not
        an HCL identifier, and the tfvars would fail to parse."""
        config["backup"]["sources"]["3pi"] = {}
        assert _node_buckets(r2_tfvars.render(config))["3pi"] == "kubelab-backup-3pi"

    def test_a_node_whose_bucket_would_be_the_scratch_bucket_is_refused(self, config: dict) -> None:
        """The scratch bucket has no `prevent_destroy`. A node sharing its name
        would put real backups in the one bucket a plan is allowed to destroy."""
        config["backup"]["sources"]["scratch"] = {}
        with pytest.raises(r2_tfvars.RenderError, match="scratch"):
            r2_tfvars.render(config)

    def test_no_sources_is_refused(self, config: dict) -> None:
        config["backup"]["sources"] = {}
        with pytest.raises(r2_tfvars.RenderError, match="backup.sources"):
            r2_tfvars.render(config)


class TestTheLockCoversTheRepositoryButNotItsLocksOrIndex:
    def test_the_locked_prefixes_are_exactly_the_four_restic_never_rewrites(self) -> None:
        out = r2_tfvars.render(_common())
        assert set(re.findall(r'"([^"]+)"', _assigned(out, "locked_prefixes"))) == {
            "data/",
            "snapshots/",
            "keys/",
            "config",
        }

    @pytest.mark.parametrize("prefix", ["locks/", "index/"])
    def test_a_prefix_restic_deletes_on_every_run_is_never_locked(self, prefix: str) -> None:
        assert prefix not in _assigned(r2_tfvars.render(_common()), "locked_prefixes")

    def test_r_is_rendered_in_seconds_from_common(self) -> None:
        days = _common()["backup"]["r2"]["lock_retention_days"]
        assert _assigned(r2_tfvars.render(_common()), "lock_max_age_seconds") == str(days * 86400)

    @pytest.mark.parametrize("key", ["account_id", "lock_retention_days"])
    def test_a_missing_r2_key_is_refused_naming_it(self, config: dict, key: str) -> None:
        del config["backup"]["r2"][key]
        with pytest.raises(r2_tfvars.RenderError, match=f"backup.r2.{key}"):
            r2_tfvars.render(config)

    @pytest.mark.parametrize("days", [30.9, 0.5, 0, -1, "30", True])
    def test_r_that_is_not_a_positive_whole_number_of_days_is_refused(self, config: dict, days: object) -> None:
        """`int()` would turn 30.9 into a 30-day lock and 0.5 into no lock at all."""
        config["backup"]["r2"]["lock_retention_days"] = days
        with pytest.raises(r2_tfvars.RenderError, match="lock_retention_days"):
            r2_tfvars.render(config)

    def test_r_is_shorter_than_the_keep_within_the_nodes_prune_with(self) -> None:
        """`forget --keep-within <K>` keeps every snapshot younger than K, so
        `prune` only deletes packs older than K. The lock refuses deletes younger
        than R. With R < K the two never meet; with R >= K every nightly prune
        hits a locked pack and the ship fails."""
        r_days = _common()["backup"]["r2"]["lock_retention_days"]
        flags = yaml.safe_load(ROLE_DEFAULTS.read_text(encoding="utf-8"))["node_backup_retention_flags"]
        m = re.search(r"--keep-within\s+(\d+)d\b", flags)
        assert m, f"node_backup_retention_flags has no --keep-within <N>d: {flags!r}"
        assert r_days < int(m.group(1))

    def test_prune_never_repacks_so_a_deleted_pack_is_older_than_r(self) -> None:
        """The lock's `Age` is the object's age; `--keep-within` bounds a snapshot's.
        They are linked only if no pack is ever rewritten: a repacked pack is minutes
        old while the snapshots it serves are not, and its later delete is refused.
        In restic 0.19.1 `--max-unused unlimited` still repacks tree and small packs;
        only `--max-repack-size 0` keeps every candidate (`decidePackAction`)."""
        flags = yaml.safe_load(ROLE_DEFAULTS.read_text(encoding="utf-8"))["node_backup_retention_flags"]
        assert re.search(r"--max-repack-size\s+0\b", flags), (
            f"node_backup_retention_flags lets prune repack: {flags!r}. A repacked pack is "
            "younger than R, so the lock refuses its delete and the ship's prune fails."
        )


class TestTheRootMatchesWhatIsRendered:
    def _variables(self) -> set[str]:
        text = (ROOT / "variables.tf").read_text(encoding="utf-8")
        return set(re.findall(r'^variable\s+"([^"]+)"', text, re.M))

    def test_every_rendered_name_is_a_declared_variable(self) -> None:
        """An undeclared name fails `terraform plan`; catch it without one."""
        out = r2_tfvars.render(_common())
        rendered = {
            line.partition("=")[0].strip()
            for line in out.splitlines()
            if "=" in line and not line.startswith((" ", "#", "}"))
        }
        assert rendered <= self._variables()

    def _resource_blocks(self) -> dict[str, str]:
        text = (ROOT / "main.tf").read_text(encoding="utf-8")
        blocks: dict[str, str] = {}
        for m in re.finditer(r'^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text, re.M):
            depth, i = 1, m.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                i += 1
            blocks[f"{m.group(1)}.{m.group(2)}"] = text[m.end() : i]
        return blocks

    def test_node_buckets_and_their_locks_cannot_be_destroyed_by_a_plan(self) -> None:
        node = {k: v for k, v in self._resource_blocks().items() if re.search(r"^\s*for_each\s*=", v, re.M)}
        assert {k.split(".")[0] for k in node} == {"cloudflare_r2_bucket", "cloudflare_r2_bucket_lock"}
        for name, body in node.items():
            assert re.search(r"prevent_destroy\s*=\s*true", body), f"{name} lacks prevent_destroy"

    def test_the_scratch_pair_is_count_gated_and_destroyable(self) -> None:
        """`prevent_destroy` cannot depend on a variable, so the scratch pair
        must live outside the node map to be destroyable at all."""
        scratch = {k: v for k, v in self._resource_blocks().items() if re.search(r"^\s*count\s*=", v, re.M)}
        assert {k.split(".")[0] for k in scratch} == {"cloudflare_r2_bucket", "cloudflare_r2_bucket_lock"}
        for name, body in scratch.items():
            assert "for_each" not in body, name
            assert "prevent_destroy" not in body, name

    def test_the_hcl_declares_no_prefix_of_its_own(self) -> None:
        """The rendered list is the one the lock applies only if the HCL has none
        of its own: a literal here would lock what the renderer's tests never see."""
        text = (ROOT / "main.tf").read_text(encoding="utf-8")
        assert re.search(r"for\s+\w+\s+in\s+var\.locked_prefixes", text)
        for prefix in (*r2_tfvars.LOCKED_PREFIXES, "locks/", "index/"):
            assert f'"{prefix}"' not in text, f"main.tf hardcodes {prefix!r}"

    def test_the_lock_rules_are_ordered_by_id_as_the_api_returns_them(self) -> None:
        """The API answers with the rules sorted by `id`. A list in the rendered
        prefix order (data/, snapshots/, keys/, config) then differs from state on
        every plan, so AC2's "a second plan shows no diff" can never hold
        (measured on the first apply, 2026-10-03). Iterating a map keyed by id
        yields the lexical order Terraform guarantees for map keys."""
        text = (ROOT / "main.tf").read_text(encoding="utf-8")
        assert re.search(
            r"for\s+id\s*,\s*prefix\s+in\s+\{\s*for\s+\w+\s+in\s+var\.locked_prefixes\s*:\s*\"retain-", text
        ), "lock_rules must iterate a map keyed by the rule id, not the prefix list"

    def test_the_provider_is_pinned_to_v5(self) -> None:
        text = (ROOT / "main.tf").read_text(encoding="utf-8")
        assert re.search(r'version\s*=\s*"~>\s*5\.\d+"', text)


def _make_dry_run(target: str, *args: str) -> subprocess.CompletedProcess[str]:
    """`make -n` prints the recipe without running it, so no token is read."""
    return subprocess.run(
        ["make", "-n", "--no-print-directory", "-C", str(REPO), target, *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _terraform_line(out: str, verb: str) -> str:
    return next(line for line in out.splitlines() if f"terraform {verb} " in line)


class TestTheScratchPairIsTornDownByTheSameScope:
    """Step 6 of the measurement destroys the scratch pair. It goes through the
    same Make scope as its creation, so the teardown can never become an
    untargeted apply: with `scratch` false and no `-target`, that apply would
    also create every node bucket."""

    def test_scratch_destroy_turns_the_pair_off_and_targets_only_it(self) -> None:
        run = _make_dry_run("tf-r2-apply", "SCRATCH=1", "SCRATCH_DESTROY=1")
        assert run.returncode == 0, run.stderr
        line = _terraform_line(run.stdout, "apply")
        assert "-var=scratch=false" in line
        assert "-var=scratch=true" not in line
        assert re.findall(r"-target=([\w.]+)", line) == [
            "cloudflare_r2_bucket.scratch",
            "cloudflare_r2_bucket_lock.scratch",
        ]

    def test_scratch_alone_still_creates_the_pair(self) -> None:
        run = _make_dry_run("tf-r2-plan", "SCRATCH=1")
        assert run.returncode == 0, run.stderr
        assert "-var=scratch=true" in _terraform_line(run.stdout, "plan")

    def test_scratch_destroy_without_scratch_is_refused(self) -> None:
        run = _make_dry_run("tf-r2-apply", "SCRATCH_DESTROY=1")
        assert run.returncode != 0
        assert "SCRATCH_DESTROY" in run.stderr
