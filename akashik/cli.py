"""Click CLI for Akashik."""

from __future__ import annotations

from pathlib import Path

import click

from akashik.executor import execute
from akashik.ingest import ingest_file
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
