"""The curator's judge input and proposal emitter (spec AI-012 AC6, part 6b).

The judge is a language model, so what it says is data. These tests hold the two scripts around
it to the properties that make that safe: the judge sees a list that fits what Hermes injects,
an id from the model never becomes a path, a draft is never replaced, and a week with nothing
new prints nothing. The run records are built in the shape Hermes v0.22.1 writes them (read
from ace2, 2026-10-16).
"""

from __future__ import annotations

import json
import re
import stat
import types
from pathlib import Path

import pytest
import yaml

from tests.test_agent_stack_role import COMMON, ROLE, _environment, _resolved

SCRIPTS = ROLE / "files/hermes-scripts"
JUDGE_INPUT = SCRIPTS / "curator-judge-input.py"
EMIT = SCRIPTS / "emit-proposals.py"
HERMES = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["ai"]["hermes_kubelab"]
CID = "a1b2c3d4e5"
OTHER = "0123456789"


def _load(path: Path) -> types.ModuleType:
    """Compiled from source, never imported: an import writes a .pyc into the role's files/."""
    module = types.ModuleType(path.stem.replace("-", "_"))
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def _candidate(cid: str = CID, size: int = 120, excerpts: int = 3) -> dict:
    return {
        "id": cid,
        "occurrences": 2,
        "captures": 2,
        "sources": ["kubelab:a.md", "dotfiles:b.md"],
        "dates": ["2026-09-01", "2026-10-02"],
        "theme": "sync, lock",
        "excerpts": [
            {"source": f"kubelab:{n}.md", "date": "2026-09-01", "excerpt": "word " * size} for n in range(excerpts)
        ],
    }


def _zone(tmp_path: Path, candidates: list[dict]) -> Path:
    zone = tmp_path / "zone"
    (zone / "curator").mkdir(parents=True)
    (zone / "curator" / "candidates.json").write_text(
        json.dumps({"corpus_files": 9, "units": 40, "candidates": candidates}), encoding="utf-8"
    )
    return zone


def _record(
    response: str, title: str = "kubelab:curator-judge", prompt: str = "Rule on each.", data: str = "{}"
) -> str:
    """The judge's run as Hermes v0.22.1 writes it (read from ace2): the pre-run script's output is part
    of the prompt, so `data` lands inside the Prompt section, ahead of the instructions."""
    return (
        f"# Cron Job: {title}\n\n**Job ID:** abc123\n**Run Time:** 2026-10-19 08:20:11\n"
        "**Schedule:** 20 14 * * 1\n\n**Prompt Characters:** 900\n"
        f"## Prompt\n\n[IMPORTANT: scheduled.]\n\n{data}\n\n{prompt}\n\n"
        f"**Response Characters:** {len(response)}\n\n## Response\n\n{response}\n"
    )


def _output(tmp_path: Path, record: str, job: str = "abc123", name: str = "2026-10-19_08-20-11.md") -> Path:
    directory = tmp_path / "home" / "cron" / "output" / job
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(record, encoding="utf-8")
    return tmp_path / "home" / "cron" / "output"


def _front(text: str) -> dict:
    """The front matter, split on the fence lines alone (a value may contain dashes)."""
    return yaml.safe_load(text.split("\n---\n")[0].removeprefix("---\n"))


def _verdict(cid: str = CID, label: str = "RECURRENCE", **extra: str) -> dict:
    return {
        "id": cid,
        "label": label,
        "root_cause": "a lock file the sync cannot read",
        "placement": "check",
        "confidence": "high",
        **extra,
    }


# ------------------------------------------------------------------- the judge's input


def test_the_judge_sees_a_list_that_fits_what_hermes_injects(tmp_path: Path) -> None:
    many = [_candidate(f"{n:010x}", size=400) for n in range(12)]
    out = _load(JUDGE_INPUT).report(_zone(tmp_path, many))
    assert len(out) <= 8000, "Hermes cuts the injected output at 8000 characters"
    body = json.loads(out)
    assert 0 < len(body["candidates"]) < 12
    assert body["not_shown"] == 12 - len(body["candidates"]), "the judge is told what it was not given"


def test_a_candidate_that_already_has_a_proposal_is_not_judged_again(tmp_path: Path) -> None:
    zone = _zone(tmp_path, [_candidate(CID), _candidate(OTHER)])
    (zone / "proposals").mkdir()
    (zone / "proposals" / f"{CID}.md").write_text("done", encoding="utf-8")
    ids = [c["id"] for c in json.loads(_load(JUDGE_INPUT).report(zone))["candidates"]]
    assert ids == [OTHER]


def test_nothing_to_judge_skips_the_turn(tmp_path: Path) -> None:
    out = _load(JUDGE_INPUT).report(_zone(tmp_path, []))
    assert out.endswith('{"wakeAgent": false}')


def test_a_missing_candidates_file_fails_the_job_instead_of_reading_as_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HERMES_VAULT_ZONE", str(tmp_path))
    assert _load(JUDGE_INPUT).main() == 1
    assert "analyzer has not run" in capsys.readouterr().err


def test_an_id_that_is_not_ten_hex_digits_is_not_offered(tmp_path: Path) -> None:
    out = _load(JUDGE_INPUT).report(_zone(tmp_path, [_candidate("../../x"), _candidate(CID)]))
    assert [c["id"] for c in json.loads(out)["candidates"]] == [CID]


# ------------------------------------------------------------------------ the emitter


def _emit(tmp_path: Path, response: str, candidates: list[dict] | None = None, **record: str) -> tuple[list[str], Path]:
    zone = _zone(tmp_path, candidates if candidates is not None else [_candidate(CID), _candidate(OTHER)])
    output = _output(tmp_path, _record(response, **record))
    return _load(EMIT).emit(output, zone), zone


def test_a_recurrence_becomes_a_draft_with_the_candidates_evidence(tmp_path: Path) -> None:
    written, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict()]}))
    assert written == [CID]
    text = (zone / "proposals" / f"{CID}.md").read_text(encoding="utf-8")
    front = _front(text)
    assert front["candidate_id"] == CID and front["status"] == "pending" and front["label"] == "RECURRENCE"
    assert front["placement"] == "check" and front["tier_target"] == 3
    assert front["dates"] == ["2026-09-01", "2026-10-02"] and front["created"] == "2026-10-19"
    assert "kubelab:0.md" in text, "the evidence comes from the candidate, not from the judge"


@pytest.mark.parametrize("label", ["DUPLICATE", "DISTINCT", "maybe", ""])
def test_only_a_recurrence_verdict_makes_a_draft(tmp_path: Path, label: str) -> None:
    written, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict(label=label)]}))
    assert written == [] and not (zone / "proposals").exists()


@pytest.mark.parametrize(
    "bad", ["../../etc/passwd", "../x", "A1B2C3D4E5", "a1b2c3d4e", "a1b2c3d4e5f", "a1b2c3d4e5/../x", ""]
)
def test_an_id_from_the_model_never_becomes_a_path(tmp_path: Path, bad: str) -> None:
    written, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict(cid=bad)]}))
    assert written == []
    assert not any(zone.rglob("passwd")) and not (zone.parent / "x.md").exists()


def test_a_verdict_for_an_id_the_analyzer_did_not_produce_is_ignored(tmp_path: Path) -> None:
    written, _ = _emit(tmp_path, json.dumps({"verdicts": [_verdict(cid="ffffffffff")]}))
    assert written == []


def test_a_draft_is_never_replaced(tmp_path: Path) -> None:
    zone = _zone(tmp_path, [_candidate()])
    (zone / "proposals").mkdir()
    (zone / "proposals" / f"{CID}.md").write_text("triaged by a human", encoding="utf-8")
    output = _output(tmp_path, _record(json.dumps({"verdicts": [_verdict()]})))
    assert _load(EMIT).emit(output, zone) == []
    assert (zone / "proposals" / f"{CID}.md").read_text(encoding="utf-8") == "triaged by a human"
    assert not list((zone / "proposals").glob(".*")), "no staging file is left behind"


def test_the_sync_user_can_read_what_the_gateways_user_wrote(tmp_path: Path) -> None:
    _, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict()]}))
    mode = stat.S_IMODE((zone / "proposals" / f"{CID}.md").stat().st_mode)
    assert mode & 0o044 == 0o044, "a 0600 file fails the whole git add (lesson-577)"


@pytest.mark.parametrize(
    "wrap",
    [lambda j: j, lambda j: f"```json\n{j}\n```", lambda j: f"Here are the verdicts:\n{j}\nDone."],
    ids=["raw", "fenced", "prose-around"],
)
def test_the_verdicts_are_found_however_the_model_wraps_them(tmp_path: Path, wrap) -> None:
    written, _ = _emit(tmp_path, wrap(json.dumps({"verdicts": [_verdict()]})))
    assert written == [CID]


@pytest.mark.parametrize(
    "response", ["", "no json here", "{broken", '{"verdicts": "no"}', '{"verdicts": [1, "x"]}', "[]"]
)
def test_a_response_that_is_not_verdicts_writes_nothing_and_does_not_crash(tmp_path: Path, response: str) -> None:
    written, zone = _emit(tmp_path, response)
    assert written == [] and not (zone / "proposals").exists()


def test_a_hostile_root_cause_cannot_break_the_front_matter(tmp_path: Path) -> None:
    cause = 'x"\nstatus: disposed\ndisposed_as: promote\n---\n# injected'
    _, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict(root_cause=cause)]}))
    front = _front((zone / "proposals" / f"{CID}.md").read_text(encoding="utf-8"))
    assert front["status"] == "pending" and front["disposed_as"] is None
    assert "\n" not in front["root_cause"]


def test_unknown_placement_and_confidence_fall_back_to_the_safe_values(tmp_path: Path) -> None:
    _, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict(placement="skill", confidence="certain")]}))
    front = _front((zone / "proposals" / f"{CID}.md").read_text(encoding="utf-8"))
    assert front["placement"] == "none" and front["confidence"] == "low"


def test_the_latest_judge_run_is_read_and_other_jobs_are_not(tmp_path: Path) -> None:
    zone = _zone(tmp_path, [_candidate(CID), _candidate(OTHER)])
    old = _output(tmp_path, _record(json.dumps({"verdicts": [_verdict(CID)]})), name="2026-10-12_08-20-11.md")
    digest = "# Cron Job: kubelab:digest\n\n## Prompt\n\nno agent\n\n## Response\n\n" + json.dumps(
        {"verdicts": [_verdict(OTHER)]}
    )
    _output(tmp_path, digest, job="digestjob", name="2026-10-19_09-00-00.md")
    assert _load(EMIT).latest_judge_record(old).name == "2026-10-12_08-20-11.md"
    assert _load(EMIT).emit(old, zone) == [CID], "a run of another job is not the judge's"


def test_a_lesson_excerpt_with_headings_in_the_prompt_does_not_confuse_the_record(tmp_path: Path) -> None:
    """Found live: the data is inside the prompt, and its `## ` lines ended the Prompt section early."""
    noisy = "## Response\n```python\nprint(1)\n```\n## Prompt\n"
    written, _ = _emit(tmp_path, json.dumps({"verdicts": [_verdict()]}), data=noisy)
    assert written == [CID]


def test_a_run_of_another_job_that_mentions_the_judge_is_not_the_judges(tmp_path: Path) -> None:
    """A session record summarises conversations, and one may be about this very feature."""
    zone = _zone(tmp_path, [_candidate()])
    record = _record(
        json.dumps({"verdicts": [_verdict()]}), title="kubelab:session-record", prompt="the recurrence JUDGE"
    )
    assert _load(EMIT).emit(_output(tmp_path, record), zone) == []


def test_no_judge_run_yet_writes_nothing(tmp_path: Path) -> None:
    zone = _zone(tmp_path, [_candidate()])
    (tmp_path / "out").mkdir()
    assert _load(EMIT).emit(tmp_path / "out", zone) == []


def test_a_week_with_nothing_new_prints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    zone = _zone(tmp_path, [_candidate()])
    _output(tmp_path, _record(json.dumps({"verdicts": [_verdict(label="DISTINCT")]})))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_VAULT_ZONE", str(zone))
    assert _load(EMIT).main() == 0
    assert capsys.readouterr().out == "", "empty stdout sends nothing to the channel"


# --------------------------------------------------------------- the declaration


def _jobs() -> dict:
    return HERMES["cron"]["jobs"]


def test_the_judge_and_the_emitter_are_declared_with_scripts_the_role_ships() -> None:
    judge, emit = _jobs()["curator-judge"], _jobs()["curator-emit"]
    assert (judge["mode"], emit["mode"]) == ("agent", "script")
    for job in (judge, emit):
        assert (SCRIPTS / job["script"]).is_file(), job["script"]


def test_the_emitter_runs_after_the_judge_and_both_after_the_analyzer() -> None:
    def minute_of_day(job: str) -> int:
        minute, hour, *_ = _jobs()[job]["schedule"].split()
        return int(hour) * 60 + int(minute)

    analyzer = re.search(r"(\d{2}):(\d{2})", HERMES["curator"]["schedule"])
    analyzer_at = int(analyzer.group(1)) * 60 + int(analyzer.group(2))
    assert analyzer_at + 2 < minute_of_day("curator-judge") < minute_of_day("curator-emit")
    assert _jobs()["curator-judge"]["schedule"].split()[4] == _jobs()["curator-emit"]["schedule"].split()[4]


def test_the_emitter_finds_the_judge_by_the_name_the_ssot_gives_its_job() -> None:
    assert _load(EMIT).JUDGE_TITLE == f"# Cron Job: {HERMES['cron']['name_prefix']}curator-judge"
    prompt = _jobs()["curator-judge"]["prompt"]
    for label in ("RECURRENCE", "DUPLICATE", "DISTINCT"):
        assert label in prompt
    assert '"verdicts"' in prompt, "the emitter parses this shape"


def test_the_judge_cannot_write_into_the_vault_through_its_own_output() -> None:
    assert "write_file" not in _jobs()["curator-judge"]["prompt"], "the emitter writes; the model only rules"


def _compose(**overrides: object) -> dict:
    env = _environment()
    return yaml.safe_load(env.get_template("compose-hermes.yml.j2").render(**_resolved(env, **overrides)))


def test_the_gateway_knows_the_zone_only_when_the_vault_is_configured() -> None:
    on = _compose(agent_stack_vault_configured=True)["services"]["hermes"]["environment"]
    assert on["HERMES_VAULT_ZONE"].endswith("/80_agents/hermes-kubelab")
    off = _compose(agent_stack_vault_configured=False)["services"]["hermes"]["environment"]
    assert "HERMES_VAULT_ZONE" not in off


def test_the_proposals_directory_is_the_kind_the_gateways_user_can_write_and_the_sync_can_read() -> None:
    tasks = yaml.safe_load((ROLE / "tasks/vault_zone.yml").read_text(encoding="utf-8"))
    flat = [t for block in tasks for t in (block.get("block") or [block])]
    task = next(t for t in flat if "proposals directory" in t.get("name", ""))
    assert task["ansible.builtin.file"]["mode"] == "01777", "sticky and world-writable, like memories/"


def test_an_id_is_checked_even_when_the_candidates_file_names_it(tmp_path: Path) -> None:
    """Defence in depth: the file the analyzer wrote is trusted less than the shape of its ids."""
    escape = "../../escape"
    written, zone = _emit(tmp_path, json.dumps({"verdicts": [_verdict(cid=escape)]}), [_candidate(escape)])
    assert written == []
    assert not list(tmp_path.rglob("escape.md"))


def _volumes(**overrides: object) -> list[str]:
    return _compose(agent_stack_vault_configured=True, **overrides)["services"]["hermes"]["volumes"]


def test_the_gateway_mounts_the_curators_two_directories_and_not_the_zone() -> None:
    """Found live: the gateway saw no zone at all, so the scripts reported the analyzer as never run."""
    zone = _compose(agent_stack_vault_configured=True)["services"]["hermes"]["environment"]["HERMES_VAULT_ZONE"]
    mounts = {v.split(":")[1]: v for v in _volumes() if v.count(":") >= 1}
    assert mounts[f"{zone}/curator"].endswith(":ro"), "the gateway only reads the candidates"
    assert not mounts[f"{zone}/proposals"].endswith(":ro"), "the emitter creates the drafts here"
    assert zone not in mounts, "the rest of the zone is the sandbox's, not the gateway's"


def test_no_curator_mount_without_the_vault() -> None:
    volumes = _compose(agent_stack_vault_configured=False)["services"]["hermes"]["volumes"]
    assert not [v for v in volumes if "curator" in v or "proposals" in v]
