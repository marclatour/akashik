import hashlib

import numpy as np

from akashik import association as A
from akashik.ingest import ingest_text
from akashik.retrieve import retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store


def fake_encoder(texts):
    """Deterministic 64-dim vectors: sum of a pseudo-random +/-1 vector per word.

    Texts sharing most words get mostly agreeing sign bits; unrelated texts ~50%.
    """
    out = np.zeros((len(texts), 64))
    for row, text in enumerate(texts):
        for word in text.lower().split():
            seed = int.from_bytes(hashlib.sha256(word.strip(".,?!").encode()).digest()[:4], "big")
            out[row] += np.random.default_rng(seed).choice([-1.0, 1.0], 64)
    return out


def unit(uid, content, valid_from):
    return MemoryUnit(
        id=uid, level="fact", content=content, content_hash=uid, normalized_hash=uid,
        parent_id=None, metadata={}, valid_from=valid_from,
    )


def test_codes_are_packed_sign_bits_and_similarity_is_bit_agreement():
    codes = A.to_code(np.array([[1.0] * 16, [-1.0] * 16, [1.0] * 8 + [-1.0] * 8]))
    assert codes.shape == (3, 2)
    sims = A.code_similarity(codes[0], codes)
    assert list(sims) == [1.0, 0.0, 0.5]


def test_code_cache_encodes_each_fact_once():
    calls = []

    def counting(texts):
        calls.append(len(texts))
        return fake_encoder(texts)

    cache = A.CodeCache()
    units = [unit("a", "red car", "2026-01-01"), unit("b", "blue bike", "2026-01-02")]
    cache.codes_for(units, counting)
    cache.codes_for(units, counting)
    assert calls == [2]
    assert cache.encoded == 2


def test_fuse_is_deterministic_and_rewards_agreement():
    a, b, c = unit("a", "x", "1"), unit("b", "y", "1"), unit("c", "z", "1")
    fused = A.fuse([a, b], [b, c])
    assert [u.id for u in fused] == ["b", "a", "c"]
    assert [u.id for u in A.fuse([a, b], [b, c])] == ["b", "a", "c"]


def test_arbitrate_withholds_only_older_session_near_duplicates():
    class S:
        pass

    store = S()
    old = unit("old", "I drive the red car to work", "2026-01-01")
    new = unit("new", "I drive the red car to work daily", "2026-03-01")
    same_day = unit("same", "I drive the red car to work", "2026-03-01")
    other = unit("other", "my favourite tea is green", "2026-01-01")
    kept, withheld = A.arbitrate(store, [old, other, new], fake_encoder, threshold=0.8)
    assert [u.id for u in kept] == ["other", "new"]
    assert withheld == [("old", "new")]
    kept, withheld = A.arbitrate(store, [same_day, new], fake_encoder, threshold=0.8)
    assert withheld == []  # same session: never withheld


def test_associative_rerank_falls_back_without_encoder():
    a = unit("a", "x", "1")
    assert A.associative_rerank(object(), "q", [a], None, as_of=None) == [a]


def test_retrieve_flag_off_is_unchanged_and_exact_match_still_wins(tmp_path, monkeypatch):
    store = Store(tmp_path / "m.db")
    ingest_text(store, "I live in Chicago", metadata={"instance_id": "t", "session_date": "2022-01-01"})
    ingest_text(store, "My dog is named Rex", metadata={"instance_id": "t", "session_date": "2022-02-01"})
    monkeypatch.setattr(A, "default_encoder", lambda: fake_encoder)

    base = retrieve("where do I live", store, level="fact", use_semantic=False)
    again = retrieve("where do I live", store, level="fact", use_semantic=False)
    assert [r.unit.id for r in base.results] == [r.unit.id for r in again.results]

    exact = retrieve("My dog is named Rex", store, level="fact", use_association=True)
    assert exact.results[0].unit.content == "My dog is named Rex"
    assert exact.results[0].confidence == 1.0


def test_retrieve_with_association_reaches_non_lexical_match(tmp_path, monkeypatch):
    store = Store(tmp_path / "m.db")
    ingest_text(store, "The Corolla gets me to class", metadata={"instance_id": "t", "session_date": "2022-01-01"})
    ingest_text(store, "Tea is my morning ritual", metadata={"instance_id": "t", "session_date": "2022-01-02"})
    monkeypatch.setattr(A, "default_encoder", lambda: fake_encoder)
    response = retrieve("corolla class", store, level="fact", use_association=True)
    assert any("Corolla" in r.unit.content for r in response.results)
    assert store._last_association_stats["associated"] >= 1
