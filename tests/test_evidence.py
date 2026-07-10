from __future__ import annotations

import json

import pytest

from benchmark import evidence


def _write_jsonl(path, rows) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_session_recall_computation(tmp_path) -> None:
    rows = [
        {"question_id": "q1", "answer_session_ids": ["s1"], "retrieved_session_ids": ["s1", "s2"]},
        {"question_id": "q2", "answer_session_ids": ["s9"], "retrieved_session_ids": ["s1", "s2"]},
        {"question_id": "q3_abs", "answer_session_ids": [], "retrieved_session_ids": []},
    ]
    path = tmp_path / "recall.jsonl"
    _write_jsonl(path, rows)

    result = evidence.session_recall(path)

    assert result == {"recall_at_10": 0.5, "n_scored": 2, "n_excluded_abs": 1}


def test_sha256_matches_hashlib(tmp_path) -> None:
    import hashlib

    path = tmp_path / "artifact.bin"
    path.write_bytes(b"akashik evidence")
    assert evidence._sha256(path) == hashlib.sha256(b"akashik evidence").hexdigest()


@pytest.fixture
def real_evidence_dir():
    if not evidence.EVIDENCE_ROOT.exists():
        pytest.skip("no evidence directory in this checkout")
    return evidence.latest_evidence_dir()


def test_acmb_table_renders_all_adapters(real_evidence_dir) -> None:
    table = evidence.render_acmb_table(real_evidence_dir)
    for _adapter, label in evidence.ACMB_ADAPTER_COLUMNS:
        assert label in table
    assert "Fact Recall" in table
    assert "Latency p95" in table
    assert "do not edit by hand" in table


def test_qa_table_contains_verified_overall(real_evidence_dir) -> None:
    table = evidence.render_qa_table(real_evidence_dir)
    verified = evidence.qa_metrics(real_evidence_dir)
    assert f"**{verified['overall']:.2f}**" in table
    assert "Jul 2026 verified" in table


def test_qa_overall_recomputable_from_verdicts(real_evidence_dir) -> None:
    verdict_path = real_evidence_dir / "qa_oracle" / "verdicts" / "all_verdicts.jsonl"
    rows = [
        json.loads(line)
        for line in verdict_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    judged = [row for row in rows if not row["abstained"]]
    correct = sum(1 for row in judged if row["judgment"] is True)
    recomputed = round(correct / len(judged), 4)

    summary = evidence.qa_metrics(real_evidence_dir)
    assert recomputed == summary["overall"]


def test_check_detects_mutation(real_evidence_dir, tmp_path, monkeypatch) -> None:
    readme_copy = tmp_path / "README.md"
    readme_copy.write_text(evidence.README_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(evidence, "README_PATH", readme_copy)

    assert evidence.cmd_check(real_evidence_dir) == 0

    mutated = readme_copy.read_text(encoding="utf-8").replace("| Fact Recall | 0.648 |", "| Fact Recall | 0.999 |")
    readme_copy.write_text(mutated, encoding="utf-8")
    assert evidence.cmd_check(real_evidence_dir) == 1


def test_manifest_covers_all_files(real_evidence_dir, tmp_path, monkeypatch) -> None:
    manifest_path = real_evidence_dir / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("manifest not yet generated")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = {entry["path"] for entry in manifest["files"]}
    on_disk = {
        str(path.relative_to(real_evidence_dir))
        for path in real_evidence_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert on_disk == listed
