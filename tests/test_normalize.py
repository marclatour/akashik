from __future__ import annotations

from akashik.identity import content_hash, normalized_hash
from akashik.query_normalize import normalize_query
from akashik.retrieve import retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store


def test_start_query_maps_to_opens() -> None:
    normalized = normalize_query("What time does the River Glass exhibit start?")
    assert "river glass exhibit opens" in normalized


def test_location_query_maps_to_sits() -> None:
    normalized = normalize_query("Where is the blue compass currently located?")
    assert "blue compass sits" in normalized


def test_worker_entrance_query_maps_to_gate_badges() -> None:
    normalized = normalize_query("Which entrance do green badge workers use now?")
    assert "gate badges now" in normalized


def test_open_now_query_preserves_now() -> None:
    normalized = normalize_query("What time does the River Glass exhibit open now?")
    assert "river glass exhibit" in normalized
    assert "opens" in normalized
    assert "now" in normalized


def test_hash_matching_uses_original_query_not_normalized(tmp_path) -> None:
    content = "The River Glass exhibit opens."
    with Store(tmp_path / "store.db") as store:
        store.insert(
            MemoryUnit(
                level="fact",
                content=content,
                content_hash=content_hash(content),
                normalized_hash=normalized_hash(content),
                metadata={"source": "test.txt", "timestamp": "2026-04-15T00:00:00+00:00", "tags": []},
            )
        )

        response = retrieve("River Glass exhibit start", store, level="fact")

        assert response.results
        assert response.results[0].unit.content == content
        assert response.confidence < 0.95
