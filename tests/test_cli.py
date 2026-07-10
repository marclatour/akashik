from __future__ import annotations

from click.testing import CliRunner

from akashik.cli import cli
from akashik.store import Store


def _write_sample(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text(
        "Storage Overview\n\n"
        "Akashik keeps every memory unit in SQLite. "
        "The blue glass shelf holds twenty two volumes.\n",
        encoding="utf-8",
    )
    return sample


def test_cli_ingest_and_stats(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"
    sample = _write_sample(tmp_path)

    ingest_result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--file", str(sample)]
    )
    assert ingest_result.exit_code == 0
    assert "Ingested" in ingest_result.output

    stats_result = runner.invoke(cli, ["--db", str(db_path), "stats"])
    assert stats_result.exit_code == 0
    assert "document: 1" in stats_result.output
    assert "fact:" in stats_result.output


def test_cli_query_returns_fact_with_chain(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"
    sample = _write_sample(tmp_path)
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--file", str(sample)])

    result = runner.invoke(
        cli,
        ["--db", str(db_path), "query", "--text", "blue glass shelf", "--level", "fact"],
    )

    assert result.exit_code == 0
    assert "blue glass shelf" in result.output
    assert "level=fact" in result.output
    assert "chain:" in result.output


def test_cli_query_no_matches(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"

    result = runner.invoke(
        cli, ["--db", str(db_path), "query", "--text", "phrase that matches nothing"]
    )

    assert result.exit_code == 0
    assert "No matches. confidence=0.0" in result.output


def test_cli_show_roundtrip(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"
    sample = _write_sample(tmp_path)
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--file", str(sample)])

    with Store(db_path) as store:
        fact_id = store.execute(
            "SELECT id FROM memory_units WHERE level = 'fact' LIMIT 1"
        ).fetchone()[0]

    result = runner.invoke(cli, ["--db", str(db_path), "show", "--id", fact_id])

    assert result.exit_code == 0
    assert f"id: {fact_id}" in result.output
    assert "level: fact" in result.output


def test_cli_show_unknown_id_errors(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"

    result = runner.invoke(
        cli, ["--db", str(db_path), "show", "--id", "no-such-uuid"]
    )

    assert result.exit_code != 0
    assert "No memory unit found" in result.output


def test_cli_commit_state_and_log(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"

    first = runner.invoke(
        cli,
        [
            "--db", str(db_path),
            "commit", "Ship episode one Friday",
            "--type", "action_item",
            "--project", "show",
            "--session-date", "2026-07-01",
        ],
    )
    assert first.exit_code == 0
    first_id = first.output.split("id=")[1].split()[0]

    second = runner.invoke(
        cli,
        [
            "--db", str(db_path),
            "commit", "Episode one shipped Saturday",
            "--type", "outcome",
            "--project", "show",
            "--supersedes", first_id,
            "--session-date", "2026-07-05",
        ],
    )
    assert second.exit_code == 0
    assert f"Supersedes {first_id}" in second.output

    state = runner.invoke(cli, ["--db", str(db_path), "state", "show"])
    assert state.exit_code == 0
    assert "outcome:" in state.output
    assert "Episode one shipped Saturday" in state.output
    assert "Ship episode one Friday" not in state.output

    log = runner.invoke(cli, ["--db", str(db_path), "log", first_id])
    assert log.exit_code == 0
    assert "superseded (until 2026-07-05)" in log.output
    assert "current" in log.output


def test_cli_commit_rejects_invalid_type(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"

    result = runner.invoke(
        cli, ["--db", str(db_path), "commit", "something", "--type", "musing"]
    )
    assert result.exit_code != 0


def test_cli_state_empty_project(tmp_path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "cli.db"
    Store(db_path).close()

    result = runner.invoke(cli, ["--db", str(db_path), "state", "nothing"])
    assert result.exit_code == 0
    assert "No current facts" in result.output


def test_cli_honors_akashik_db_env(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("AKASHIK_DB", str(db_path))

    result = runner.invoke(cli, ["commit", "env default works", "--type", "claim"])
    assert result.exit_code == 0
    assert db_path.exists()

    stats = runner.invoke(cli, ["stats"])
    assert stats.exit_code == 0
    assert str(db_path) in stats.output
