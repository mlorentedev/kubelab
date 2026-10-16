#!/usr/bin/env python3
"""
curator-analyze.py: recurrence detector over the lesson corpus (spec AI-012 AC6).

Ported from hermes-nan. The deterministic narrowing half of the curation loop: it runs as a
host unit of the agent's user, reads the root-owned vault mirror, and writes the candidate
clusters to one JSON file in the agent's zone for the judge to read. Reads the vault's
`sessions/` and lessons plus the repositories' `docs/lessons/` (fetched from GitHub's public
API, unauthenticated) —
clusters lesson-units by a *rarity-weighted* keyword signature, and surfaces recurrences
(same root cause seen >=2x across DISTINCT incidents) as proposal CANDIDATES.

It writes only the file named by `--out`; promotion into the shared brain stays human. Each
candidate is handed to an LLM judge for the "same root cause / worth promoting?" verdict.

Signal-not-noise is proven HERE, in the narrowing. Two moves keep it from drowning in
session-handoff boilerplate:
  1. SEGMENT — from session records, keep only lesson-bearing sections (Decisions/Findings/
     Lessons); drop Open-threads/Next-action/Artifacts (activity logs, not root causes).
     `docs/lessons.md` / `lessons/_index.md` / `docs/lessons/*.md` are all-lessons; keep them whole.
  2. RECURRENCE = >=2 DISTINCT incidents (source+date pairs), not >=2 files — so the same
     discipline repeated across distinct dated lessons in ONE lessons.md still counts.

Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# The corpus is UTF-8 (em-dashes, arrows, accents); force UTF-8 stdout so a Windows cp1252
# console doesn't crash on a candidate excerpt. No-op where the stream is already UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ── Tuning knobs (the signal-vs-noise crux — the "autonomy dial" gate) ────────────────────
MIN_UNIT_TOKENS = 10  # a block needs this many distinct significant tokens to be a "lesson unit"
DF_MAX_RATIO = 0.45  # drop tokens appearing in >45% of units — too common to be distinctive
SIM_THRESHOLD = 0.18  # Jaccard over distinctive tokens; >= this links two units into a cluster
DEDUP_THRESHOLD = 0.65  # >= this Jaccard => a near-LITERAL duplicate (same lesson copy-pasted) —
# collapse to one occurrence. Set high on purpose: a session bullet and its
# distilled lessons.md twin (~0.3-0.5) and a genuine recurrence of one
# discipline (~0.3-0.5) are lexically indistinguishable, so the
# promotion-vs-recurrence call is left to the LLM judge, not this threshold.
MIN_OCCURRENCES = 2  # a real recurrence = >=2 DISTINCT lessons (after dedup)


# Session sections that carry root-cause lessons vs. activity-log boilerplate. Section headers
# are matched exactly (after stripping #/*/: markers), so normal prose never trips them.
LESSON_SECTIONS = {
    "decisions",
    "findings",
    "lessons",
    "learnings",
    "lesson",
    "key learnings",
    "what i learned",
    "what changed",
    "gotchas",
    "takeaways",
    "decisiones",
    "lecciones",
    "hallazgos",
    "aprendizajes",
}
NOISE_SECTIONS = {
    "open threads",
    "next action",
    "next actions",
    "next",
    "artifacts",
    "last task",
    "repo state",
    "summary",
    "status",
    "context",
    "tldr",
    "tl;dr",
    "blockers",
    "carried",
    "open",
    "state",
    "hilos abiertos",
    "siguiente accion",
    "próxima acción",
}
SECTION_VOCAB = LESSON_SECTIONS | NOISE_SECTIONS

STOPWORDS = set(
    """
the a an and or but of to in on at for with from by as is are was were be been being this that
these those it its it's we our you your they their them he she his her i me my mine ours
not no yes do does did done can could should would will shall may might must have has had
if then else when while because so than too very just only also still even more most much
into onto over under out up down off about across after before per via vs etc eg ie ok
new old same other another each any all some both few many several such own here there
one two three four five first second third next last
pr prs issue issues ticket tickets commit commits merged merge open close closed fix fixed fixes
session sessions vault repo repos file files line lines code change changes update updated
run ran running added add adds removed remove note notes done work working task tasks
md sh ps1 yaml json bats test tests use used using set get
manu claude opencode dotfiles knowledge hermes agent agents
problem solution context rule related tags example approach symptom why how
always never instead ensure must want need make made way
""".split()
)

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]{2,}")
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
BULLET_SPLIT_RE = re.compile(r"(?m)^(?=\s*(?:[-*]|\d+\.)\s+\S)")
HAS_BULLET_RE = re.compile(r"(?m)^\s*([-*]|\d+\.)\s+\S")


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def header_label(line: str):
    """Return a normalized section label iff this line is a recognized section header, else None."""
    s = line.strip()
    if not s or len(s) > 40:
        return None
    s = s.lstrip("#").strip().strip("*").strip()
    s = re.sub(r":\**$", "", s).strip().lower()
    return s if s in SECTION_VOCAB else None


def tokenize(text: str) -> list[str]:
    out = []
    for m in TOKEN_RE.findall(text.lower()):
        t = m.strip("-_+")
        if len(t) < 3 or t in STOPWORDS or t.isdigit():
            continue
        out.append(t)
    return out


def blocks_to_units(text: str) -> list[str]:
    """Blank-line blocks; a bullet list explodes into one unit per top-level item."""
    units: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if HAS_BULLET_RE.search(block):
            for it in BULLET_SPLIT_RE.split(block):
                it = it.strip()
                if it:
                    units.append(it)
        else:
            units.append(block)
    return units


def split_lessons_file(text: str) -> list[str]:
    """A lessons file: one unit per ## / ### heading section (date stays with its body)."""
    text = strip_frontmatter(text)
    parts = [p.strip() for p in re.split(r"(?m)^(?=#{1,6}\s)", text) if p.strip()]
    return parts if len(parts) > 1 else blocks_to_units(text)


def split_session_file(text: str) -> list[str]:
    """A session record: collect only the lines under lesson-bearing sections, then unitize."""
    text = strip_frontmatter(text)
    current = None
    kept: list[str] = []
    for line in text.splitlines():
        lbl = header_label(line)
        if lbl is not None:
            current = lbl
            continue
        if current in LESSON_SECTIONS:
            kept.append(line)
    return blocks_to_units("\n".join(kept))


def is_lessons_file(path: Path) -> bool:
    return path.name in ("lessons.md", "lessons/_index.md") or "docs" in path.parts or path.name.startswith("lesson-")


def load_corpus(paths: list[Path], vault_root: Path) -> list[dict]:
    units = []
    for p in paths:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            source = str(p.relative_to(vault_root))
        except ValueError:
            source = p.name
        m = DATE_RE.search(p.name)
        file_date = m.group(1) if m else ""
        raw_units = split_lessons_file(raw) if is_lessons_file(p) else split_session_file(raw)
        for u in raw_units:
            toks = tokenize(u)
            if len(set(toks)) < MIN_UNIT_TOKENS:
                continue
            d = DATE_RE.search(u)
            units.append(
                {
                    "source": source,
                    "date": d.group(1) if d else file_date,
                    "text": u,
                    "tokens": set(toks),
                }
            )
    return units


def distinctive_signatures(units: list[dict]) -> None:
    """Drop corpus-common tokens; store unit['sig'] = rare, root-cause-bearing tokens."""
    n = len(units) or 1
    df: dict[str, int] = {}
    for u in units:
        for t in u["tokens"]:
            df[t] = df.get(t, 0) + 1
    cutoff = DF_MAX_RATIO * n
    common = {t for t, c in df.items() if c > cutoff}
    for u in units:
        u["sig"] = u["tokens"] - common


def jaccard(a: set, b: set) -> float:
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def cluster(units: list[dict]) -> list[list[int]]:
    """Connected components over edges with Jaccard(sig) >= SIM_THRESHOLD."""
    n = len(units)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        si = units[i]["sig"]
        if not si:
            continue
        for j in range(i + 1, n):
            if jaccard(si, units[j]["sig"]) >= SIM_THRESHOLD:
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def dedup_into_lessons(members: list[dict], threshold: float) -> list[list[dict]]:
    """Collapse members that are the SAME lesson — a session bullet and its promoted lessons.md
    twin, or a literal duplicate entry — into one group. Recurrence counts distinct lessons,
    so 'promoted to lessons.md' never masquerades as 'happened twice'."""
    groups: list[list[dict]] = []
    reps: list[set] = []
    for m in members:
        for k, rep in enumerate(reps):
            if jaccard(m["sig"], rep) >= threshold:
                groups[k].append(m)
                break
        else:
            groups.append([m])
            reps.append(m["sig"])
    return groups


def candidate_id(sources: list[str], dates: list[str]) -> str:
    """Stable identity for a recurrence candidate: a short hash of its (sorted) sources+dates.

    Stable across runs while the cluster is the SAME recurring event — so the S3 inbox can
    dedup already-emitted proposals and the disposer can re-join a judge verdict (which carries
    only the id) back to this candidate's evidence. Deliberately CHANGES when a new occurrence
    enters the cluster (new source/date): a fresh recurrence count is exactly when we want the
    judge to re-evaluate rather than let a disposed proposal silence it. Theme is NOT hashed —
    it is frequency-derived and noisy, which would churn the id for the wrong reasons.
    """
    payload = "\n".join(sources) + "" + "\n".join(dates)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def summarize_cluster(units: list[dict], idxs: list[int], dedup_threshold: float) -> dict:
    members = [units[i] for i in idxs]
    lessons = dedup_into_lessons(members, dedup_threshold)
    # one representative per distinct lesson — prefer the promoted lessons.md capture
    reps = [next((m for m in g if m["source"].endswith("lessons.md")), g[0]) for g in lessons]
    freq: dict[str, int] = {}
    for r in reps:
        for t in r["sig"]:
            freq[t] = freq.get(t, 0) + 1
    theme = [t for t, c in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])) if c >= 2][:8]
    if not theme and len(reps) > 1:  # tiny clusters: fall back to the rarest shared tokens
        shared = set.intersection(*[r["sig"] for r in reps])
        theme = sorted(shared)[:8]
    excerpts = []
    for r in reps:
        first = next((ln.strip() for ln in r["text"].splitlines() if ln.strip()), "")
        excerpts.append({"source": r["source"], "date": r["date"], "excerpt": first[:200]})
    sources = sorted({m["source"] for m in members})
    dates = sorted({r["date"] for r in reps if r["date"]})
    return {
        "id": candidate_id(sources, dates),  # stable across runs (S3): join verdict->evidence + dedup
        "occurrences": len(lessons),  # distinct lessons (post-dedup)
        "captures": len(members),  # raw units before dedup
        "sources": sources,
        "dates": dates,
        "theme": theme,
        "excerpts": excerpts,
    }


def fetch_github_lessons(repos: list[str], cache_dir: Path) -> dict[str, int]:
    """Download each repository's lessons from its public tarball into `cache_dir`.

    One request per repository and no API quota. Walking the tarball rather than listing a
    directory is what keeps this correct as a repository groups its lessons into category
    folders (kubelab does): the listing the original used saw only the top level. Returns
    the number of lesson files taken per repository, so a repository that yields none
    can be called out instead of passing for a quiet corpus.
    """
    counts: dict[str, int] = {}
    for repo in repos:
        owner_repo = repo.strip() if "/" in repo else f"mlorentedev/{repo.strip()}"
        target = cache_dir / owner_repo.replace("/", "_")
        counts[owner_repo] = 0
        # Extracted beside the target and swapped in whole: a stream that drops mid-archive
        # must not leave a partial corpus that passes the zero-files guard as a valid one.
        staging = target.with_name(target.name + ".part")
        shutil.rmtree(staging, ignore_errors=True)
        taken = 0
        try:
            with urllib.request.urlopen(f"https://codeload.github.com/{owner_repo}/tar.gz/HEAD", timeout=60) as resp:
                with tarfile.open(fileobj=resp, mode="r|gz") as archive:
                    for member in archive:
                        parts = member.name.split("/", 1)[-1].split("/")
                        in_lessons = parts[:2] == ["docs", "lessons"] and len(parts) >= 3
                        if not member.isfile() or not (in_lessons or parts == ["docs", "lessons.md"]):
                            continue
                        name = parts[-1]
                        if not name.endswith(".md") or name.startswith("_"):
                            continue
                        handle = archive.extractfile(member)
                        if handle is None:
                            continue
                        staging.mkdir(parents=True, exist_ok=True)
                        (staging / name).write_bytes(handle.read())
                        taken += 1
        except (OSError, tarfile.TarError, EOFError) as error:
            print(f"warning: {owner_repo}: {type(error).__name__}: {error}", file=sys.stderr)
            shutil.rmtree(staging, ignore_errors=True)
            continue
        shutil.rmtree(target, ignore_errors=True)
        if taken:
            staging.rename(target)
        counts[owner_repo] = taken
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Recurrence detector over the lesson corpus.")
    ap.add_argument("--vault", required=True, help="vault root (the read-only mirror's tree)")
    ap.add_argument(
        "--repos", nargs="*", default=[], help="owner/repo whose docs/lessons/ is fetched as a public tarball"
    )
    ap.add_argument("--cache-dir", default=None, help="where fetched lessons are kept (required with --repos)")
    ap.add_argument("--out", required=True, help="file the candidates are written to, atomically")
    ap.add_argument(
        "--dedup",
        type=float,
        default=DEDUP_THRESHOLD,
        help="Jaccard >= this collapses same-lesson captures into one occurrence",
    )
    ap.add_argument("--top", type=int, default=10, help="max candidates to report")
    args = ap.parse_args()

    vault = Path(args.vault).resolve()
    if not (vault / "00_meta").is_dir():
        print(f"error: {vault} is not a vault root (no 00_meta/)", file=sys.stderr)
        return 2

    paths: list[Path] = []
    paths += sorted(vault.glob("10_projects/*/sessions/*.md"))
    paths += sorted(vault.glob("80_agents/*/sessions/*.md"))
    paths += sorted(vault.glob("10_projects/*/lessons/_index.md"))
    paths += sorted(vault.glob("80_agents/*/lessons/_index.md"))

    if args.repos:
        if not args.cache_dir:
            print("error: --repos needs --cache-dir", file=sys.stderr)
            return 2
        cache = Path(args.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        counts = fetch_github_lessons(args.repos, cache)
        empty = sorted(repo for repo, taken in counts.items() if not taken)
        if empty:
            # An empty corpus reads as "no recurrence", the one answer a broken fetch must not give.
            print(f"error: no lessons fetched from {', '.join(empty)}", file=sys.stderr)
            return 3
        paths += sorted(cache.glob("*/*.md"))

    units = load_corpus(paths, vault)
    distinctive_signatures(units)
    clusters = cluster(units)

    # A recurrence is the same root cause at >=2 DISTINCT TIMES. Requiring >=2 distinct dates
    # (not just >=2 captures) is the principled line that drops promotion-twins.
    candidates = [summarize_cluster(units, g, args.dedup) for g in clusters]
    candidates = [c for c in candidates if c["occurrences"] >= MIN_OCCURRENCES and len(c["dates"]) >= MIN_OCCURRENCES]
    candidates.sort(key=lambda c: (len(c["dates"]), c["occurrences"]), reverse=True)
    candidates = candidates[: args.top]

    report = {"corpus_files": len(paths), "units": len(units), "candidates": candidates}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed, so the judge never reads half a file.
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=".candidates-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, out)
    print(f"{len(paths)} files, {len(units)} lesson units, {len(candidates)} candidates -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
