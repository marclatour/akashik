"""Akashik public package interface."""

from akashik.ingest import ingest_file
from akashik.retrieve import retrieve
from akashik.schema import LEVELS, MemoryUnit, RetrievalResponse, RetrievalResult, StoreStats
from akashik.store import Store

__all__ = [
    "LEVELS",
    "MemoryUnit",
    "RetrievalResponse",
    "RetrievalResult",
    "Store",
    "StoreStats",
    "ingest_file",
    "retrieve",
]

__version__ = "0.1.0"
