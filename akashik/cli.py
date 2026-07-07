"""Click CLI for Akashik."""

from __future__ import annotations

from pathlib import Path

import click

from akashik.executor import execute
from akashik.ingest import FACT_TYPES, commit_fact, ingest_file
from akashik.retrieve import retrieve
from akashik.schema import LEVELS
from akashik.store import Store


@click.group()
@click.option(
    "--db",
    "db_path",
    default="./akashik.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.pass_context
def cli(ctx: click.Context, db_path: Path) -> None:
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


def _open_store(ctx: click.Context) -> Store:
    return Store(ctx.obj["db_path"])


@cli.command("ingest")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--level", default="document", show_default=True, type=click.Choice(LEVELS))
@click.pass_context
def ingest_command(ctx: click.Context, file_path: Path, level: str) -> None:
    with _open_store(ctx) as store:
        document = ingest_file(file_path, store, level=level)
    click.echo(f"Ingested {file_path} as {document.level} id={document.id}")


@cli.command("query")
@click.option("--text", required=True)
@click.option("--level", type=click.Choice(LEVELS))
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--navigator/--no-navigator", default=True, show_default=True)
@click.pass_context
def query_command(
    ctx: click.Context,
    text: str,
    level: str | None,
    limit: int,
    navigator: bool,
) -> None:
    with _open_store(ctx) as store:
        response = retrieve(text, store, level=level, limit=limit, use_navigator=navigator)

    if not response.results:
        click.echo("No matches. confidence=0.0")
        return

    for index, result in enumerate(response.results, start=1):
        click.echo(f"[{index}] level={result.unit.level} confidence={result.confidence:.2f}")
        click.echo(f"source: {result.unit.source}")
        click.echo(f"content: {result.unit.content}")
        click.echo(f"chain: {_format_chain(result)}")
        click.echo("")


@cli.command("execute")
@click.argument("query")
@click.option(
    "--store",
    "store_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional store path override for this command.",
)
@click.option("--query-date")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--abstention-threshold", default=0.3, show_default=True, type=float)
@click.pass_context
def execute_command(
    ctx: click.Context,
    query: str,
    store_path: Path | None,
    query_date: str | None,
    limit: int,
    abstention_threshold: float,
) -> None:
    db_path = store_path or ctx.obj["db_path"]
    with Store(db_path) as store:
        result = execute(
            store,
            query,
            query_date=query_date,
            top_k=limit,
            abstention_threshold=abstention_threshold,
        )

    if result.abstained:
        click.echo("Answer: No evidence found")
        click.echo(f"Type: {result.answer_type}")
        click.echo("Abstained: true")
        return

    click.echo(f"Answer: {result.answer}")
    click.echo(f"Type: {result.answer_type}")
    click.echo(f"Confidence: {result.answer_confidence:.2f} / {result.coverage_confidence:.2f}")
    click.echo(f"Requires reasoning: {str(result.requires_reasoning).lower()}")
    for source in result.sources:
        session_id = source.session_id or "unknown_session"
        session_date = source.session_date or "unknown_date"
        click.echo(
            f'Source: {session_id} ({session_date}) — "{source.content}"'
        )


@cli.command("show")
@click.option("--id", "unit_id", required=True)
@click.pass_context
def show_command(ctx: click.Context, unit_id: str) -> None:
    with _open_store(ctx) as store:
        unit = store.fetch_by_id(unit_id)
        if unit is None:
            raise click.ClickException(f"No memory unit found for id={unit_id}")
        chain = store.fetch_parent_chain(unit.id)

    click.echo(f"id: {unit.id}")
    click.echo(f"level: {unit.level}")
    click.echo(f"source: {unit.source}")
    click.echo(f"content: {unit.content}")
    click.echo(f"chain: {_format_unit_chain(unit, chain)}")


@cli.command("commit")
@click.argument("content")
@click.option("--type", "fact_type", default="claim", show_default=True, type=click.Choice(FACT_TYPES))
@click.option("--project", default="general", show_default=True)
@click.option("--supersedes", default=None, help="Fact id this commit replaces.")
@click.option("--source", default="user", show_default=True)
@click.option("--session-date", default=None, help="Override the commit date (YYYY-MM-DD).")
@click.pass_context
def commit_command(
    ctx: click.Context,
    content: str,
    fact_type: str,
    project: str,
    supersedes: str | None,
    source: str,
    session_date: str | None,
) -> None:
    with _open_store(ctx) as store:
        try:
            unit = commit_fact(
                store,
                content,
                fact_type=fact_type,
                project=project,
                supersedes=supersedes,
                source=source,
                session_date=session_date,
            )
        except ValueError as error:
            raise click.ClickException(str(error))
    click.echo(f"Committed {fact_type} id={unit.id} project={project}")
    if supersedes:
        click.echo(f"Supersedes {supersedes}")


@cli.command("state")
@click.argument("project")
@click.pass_context
def state_command(ctx: click.Context, project: str) -> None:
    """Show all current committed facts for a project, grouped by type."""
    with _open_store(ctx) as store:
        units = store.fetch_by_metadata_filters(level="fact", filters={"project": project})

    current = [unit for unit in units if unit.valid_until is None]
    if not current:
        click.echo(f"No current facts for project={project}")
        return

    grouped: dict[str, list] = {}
    for unit in current:
        grouped.setdefault(str(unit.metadata.get("fact_type", "fact")), []).append(unit)

    click.echo(f"project: {project}")
    for fact_type in sorted(grouped):
        click.echo(f"\n{fact_type}:")
        for unit in grouped[fact_type]:
            date = unit.valid_from or "undated"
            click.echo(f"  [{unit.id}] ({date}) {unit.content}")


@cli.command("log")
@click.argument("fact_id")
@click.pass_context
def log_command(ctx: click.Context, fact_id: str) -> None:
    """Show the full supersession history for one fact, oldest first."""
    with _open_store(ctx) as store:
        chain = store.fetch_lineage_chain(fact_id)
    if not chain:
        raise click.ClickException(f"No memory unit found for id={fact_id}")
    for unit in chain:
        status = "current" if unit.valid_until is None else f"superseded (until {unit.valid_until})"
        marker = "*" if unit.id == fact_id else " "
        click.echo(f"{marker} [{unit.id}] {status}")
        click.echo(f"    {unit.content}")


@cli.command("stats")
@click.pass_context
def stats_command(ctx: click.Context) -> None:
    with _open_store(ctx) as store:
        stats = store.stats()

    click.echo(f"db: {stats.db_path}")
    click.echo(f"total: {stats.total}")
    for level in LEVELS:
        click.echo(f"{level}: {stats.by_level[level]}")


def _format_chain(result) -> str:
    return _format_unit_chain(result.unit, result.parent_chain)


def _format_unit_chain(unit, parent_chain) -> str:
    levels = [unit.level, *[parent.level for parent in parent_chain]]
    return " -> ".join(levels)
