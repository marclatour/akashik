from __future__ import annotations

from pathlib import Path

from akashik.ingest_pipeline import ingest_turn
from akashik.store import Store


def main() -> int:
    store_path = Path.home() / ".akashik" / "stores" / "ingest_test" / "test.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        store_path.unlink()
    except FileNotFoundError:
        pass

    turns = [
        "I was still in Chicago then, renting a two-flat in Avondale.",
        "The Denver landlord finally fixed the hallway light, so the place feels less temporary now.",
        "I spent the weekend trying to rescue a sourdough starter that kept collapsing.",
        "My partner works at Cedar Health, so that name comes up constantly.",
        "I don't live in Chicago anymore.",
    ]

    with Store(store_path) as store:
        for text in turns:
            result = ingest_turn(store, text)
            print(f"INPUT: {text}")
            print(f"RAW RESPONSE: {result['raw_response']}")
            print(f"RESULT: {result}")
            print("-" * 80)

        facts = store.fetch_by_metadata_filters(level="fact")
        print("FACTS IN STORE:")
        for fact in facts:
            print(f"- {fact.content}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
