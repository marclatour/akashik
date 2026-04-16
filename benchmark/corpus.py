"""Synthetic benchmark corpus loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from benchmark import DEFAULT_CORPUS_DIR

_SECTION_SPLIT_RE = re.compile(r"\n\s*\n+")


@dataclass(slots=True)
class CorpusDocument:
    filename: str
    path: Path
    text: str
    sections: list[str] = field(default_factory=list)
    word_count: int = 0


def load_corpus(corpus_dir: str | Path | None = None) -> list[CorpusDocument]:
    base_dir = Path(corpus_dir or DEFAULT_CORPUS_DIR).resolve()
    documents: list[CorpusDocument] = []

    for path in sorted(base_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        sections = split_sections(text)
        documents.append(
            CorpusDocument(
                filename=path.name,
                path=path,
                text=text,
                sections=sections,
                word_count=len(text.split()),
            )
        )

    validate_corpus(documents)
    return documents


def split_sections(text: str) -> list[str]:
    return [section.strip() for section in _SECTION_SPLIT_RE.split(text.strip()) if section.strip()]


def validate_corpus(documents: list[CorpusDocument]) -> None:
    if not 10 <= len(documents) <= 20:
        raise ValueError(f"Benchmark corpus must contain 10-20 documents; found {len(documents)}.")

    filenames = {document.filename for document in documents}
    if len(filenames) != len(documents):
        raise ValueError("Benchmark corpus filenames must be unique.")

    for document in documents:
        if not 500 <= document.word_count <= 1000:
            raise ValueError(
                f"Document {document.filename} must be 500-1000 words; found {document.word_count}."
            )
        if not document.sections:
            raise ValueError(f"Document {document.filename} must contain at least one section.")
