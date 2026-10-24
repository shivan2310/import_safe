"""Provenance enums for cost assumptions.

Kept in a leaf module (no imports from the rest of the package) so both cost_config.py and rates/models.py
can use them without a circular import. rates/models.py re-exports them.
"""
from enum import Enum


class Provenance(str, Enum):
    placeholder = "placeholder"
    human_approved = "human_approved"


class EvidenceKind(str, Enum):
    official = "official"
    benchmark = "benchmark"
