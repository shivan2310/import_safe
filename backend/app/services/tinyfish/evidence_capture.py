"""Turn connector results into report evidence (docs/prd-backend.md B6).

A field becomes evidence only when it has a non-empty supporting excerpt. Fields without one stay low confidence
and produce no evidence item.
"""
from typing import List, Tuple

from app.db.ids import new_ulid
from app.decision.report_schema import EvidenceItem
from app.services.tinyfish.models import ExtractionResult, RegistryResult


def build_evidence_pairs(result: ExtractionResult, investigation_id: str) -> List[Tuple[str, EvidenceItem]]:
    """Return ``(field, EvidenceItem)`` pairs, one per field with a non-empty excerpt, in field order."""
    if not isinstance(investigation_id, str) or not investigation_id.strip():
        raise ValueError("investigation_id is required")
    source_type = "official_portal" if isinstance(result, RegistryResult) else "listing"
    pairs: List[Tuple[str, EvidenceItem]] = []
    for field in result.fields:
        excerpt = result.excerpt_map.get(field, "").strip()
        if not excerpt:
            continue
        item = EvidenceItem(
            id=new_ulid(),
            source_url=result.source_url,
            retrieved_at=result.retrieved_at,
            excerpt=excerpt,
            source_type=source_type,
        )
        pairs.append((field, item))
    return pairs


def build_evidence_items(result: ExtractionResult, investigation_id: str) -> List[EvidenceItem]:
    return [item for _, item in build_evidence_pairs(result, investigation_id)]
