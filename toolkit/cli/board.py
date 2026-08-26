"""Bitácora board governance commands (GOV-002, #823)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from toolkit.core.logging import logger
from toolkit.features import board_ids, board_streams, board_sweep

app = typer.Typer(
    name="board",
    help="Bitácora board governance: keep the Stream field true to the registry.",
    no_args_is_help=True,
)


@app.command("streams")
def streams_cmd(
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Write the field values (creates the field on first run)."),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="Exit 1 if any open issue is unplaced or out of date."),
    ] = False,
    registry_path: Annotated[
        Path,
        typer.Option("--registry", help="Stream registry YAML."),
    ] = board_streams.DEFAULT_REGISTRY,
) -> None:
    """Plan (default), apply, or check the Stream field against harness/board-streams.yaml."""
    try:
        registry = board_streams.load_registry(registry_path)
        info = board_streams.fetch_project(registry)
        items = board_streams.fetch_open_items(registry)
    except (board_streams.RegistryError, board_streams.GitHubError) as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc

    plan = board_streams.plan(items, registry)
    sizes = board_streams.desired_counts(items, registry)
    to_write = plan.counts()

    typer.echo(f"{'Stream':32s} {'size':>5s} {'write':>6s}")
    for stream in registry.streams:
        typer.echo(f"{stream:32s} {sizes.get(stream, 0):5d} {to_write.get(stream, 0):6d}")
    typer.echo(
        f"\nopen issues on board: {len(items)}  "
        f"unchanged: {plan.unchanged}  to write: {len(plan.changes)}  "
        f"unplaced: {len(plan.unplaced)}"
    )
    if info.field_id is None:
        typer.echo(f"field {registry.field!r} does not exist yet; --apply creates it")
    for item in plan.unplaced:
        typer.echo(f"  unplaced #{item.number} {item.title[:90]}")

    if check:
        if plan.unplaced or plan.changes:
            raise typer.Exit(code=1)
        return

    if not apply:
        typer.echo("\ndry run — nothing written (use --apply)")
        return

    try:
        info = board_streams.ensure_field(registry, info)
        written = board_streams.apply(info, plan.changes)
    except (board_streams.RegistryError, board_streams.GitHubError) as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc
    typer.echo(f"written: {written}")
    if plan.unplaced:
        typer.echo(f"{len(plan.unplaced)} issue(s) remain unplaced — add overrides or prefixes to the registry")
        raise typer.Exit(code=1)


@app.command("parts")
def parts_cmd(
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Add the missing parent/sub-issue links."),
    ] = False,
    registry_path: Annotated[
        Path,
        typer.Option("--registry", help="Stream registry YAML."),
    ] = board_streams.DEFAULT_REGISTRY,
) -> None:
    """Plan (default) or apply the parent links declared under `parts:` in the registry."""
    try:
        registry = board_streams.load_registry(registry_path)
    except board_streams.RegistryError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc
    if not registry.parts:
        typer.echo("no parts declared in the registry")
        return

    numbers = sorted(set(registry.parts) | {c for cs in registry.parts.values() for c in cs})
    try:
        refs = board_streams.fetch_issue_refs(registry, numbers)
    except board_streams.GitHubError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc

    plan = board_streams.plan_parts(registry, refs)
    for parent, children in registry.parts.items():
        to_link = sum(1 for link in plan.links if link.parent == parent)
        linked = sum(1 for c in children if refs.get(c) and refs[c].parent == parent)
        typer.echo(f"#{parent}: {len(children)} parts — linked {linked}, to link {to_link}")
    for child, current, desired in plan.conflicts:
        typer.echo(f"  conflict: #{child} already under #{current}, registry wants #{desired} — skipped")
    for number in plan.missing:
        typer.echo(f"  missing: #{number} not found in {registry.repo}")
    for number in plan.closed_parents:
        typer.echo(f"  closed parent: #{number} is not OPEN — its parts were left alone")

    if not apply:
        typer.echo("\ndry run — nothing linked (use --apply)")
        return
    try:
        added = board_streams.apply_parts(refs, plan.links)
    except board_streams.GitHubError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc
    typer.echo(f"linked: {added}")
    if plan.conflicts or plan.missing or plan.closed_parents:
        raise typer.Exit(code=1)


@app.command("sweep")
def sweep_cmd(
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Write the Status/Priority changes."),
    ] = False,
    registry_path: Annotated[
        Path,
        typer.Option("--registry", help="In Progress sweep registry YAML."),
    ] = board_sweep.DEFAULT_REGISTRY,
) -> None:
    """Plan (default) or apply the one-time In Progress sweep in harness/board-inprogress-sweep.yaml."""
    try:
        registry = board_sweep.load_registry(registry_path)
    except board_sweep.RegistryError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc

    numbers = sorted(set(registry.stays) | set(registry.parked))
    try:
        items = board_sweep.fetch_items(registry, numbers)
    except board_sweep.GitHubError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc

    plan = board_sweep.plan(items, registry)
    for change in plan.changes:
        parts = []
        if change.status is not None:
            parts.append(f"status -> {change.status}")
        if change.priority is not None:
            parts.append(f"priority -> {change.priority}")
        typer.echo(f"  #{change.item.number}: {', '.join(parts)}")
    for number in plan.missing:
        typer.echo(f"  missing: #{number} not found on the board")
    typer.echo(f"\nunchanged: {plan.unchanged}  to write: {len(plan.changes)}  missing: {len(plan.missing)}")

    if not apply:
        typer.echo("\ndry run — nothing written (use --apply)")
        return
    if plan.missing:
        logger.error("refusing to apply: some registry issues were not found on the board")
        raise typer.Exit(code=2)

    try:
        project_id, fields = board_sweep.fetch_fields(registry)
        written = board_sweep.apply(project_id, fields, registry, plan.changes)
    except board_sweep.GitHubError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc
    typer.echo(f"written: {written}")


@app.command("ids")
def ids_cmd(
    check: Annotated[
        bool,
        typer.Option("--check", help="Exit 1 if any open issue shares its id with another."),
    ] = False,
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="owner/name to scan. Defaults to the Stream registry's project.repo."),
    ] = None,
) -> None:
    """Report (default) or check for open issues that share a ticket id."""
    repo_name = repo
    if repo_name is None:
        try:
            repo_name = board_streams.load_registry().repo
        except board_streams.RegistryError as exc:
            logger.error(str(exc))
            raise typer.Exit(code=2) from exc

    try:
        issues = board_ids.fetch_open_issues(repo_name)
    except board_ids.GitHubError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2) from exc

    dupes = board_ids.duplicates(issues)
    for fid in sorted(dupes):
        numbers = " ".join(f"#{i.number}" for i in dupes[fid])
        typer.echo(f"{fid}: {numbers}")
    typer.echo(f"\nopen issues scanned: {len(issues)}  duplicate ids: {len(dupes)}")

    if check and dupes:
        raise typer.Exit(code=1)
