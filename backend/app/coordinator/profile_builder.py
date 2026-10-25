"""Turn TinyFish results and order inputs into tagged facts, and read facts back into engine inputs.

Facts are the source of truth: they are stored flat (text, int, bool) and the profile, the classifier input, the
rule profile and the certification claim are all derived from stored facts. That is what lets an investigation
pause for a question and resume without keeping anything in memory.

Tagging (docs/prd-backend.md B6):
- a listing field with a supporting excerpt is ``confirmed`` (high confidence) and carries an evidence ID;
- a certification or manufacturer statement is a ``seller_claim``, whatever its excerpt;
- any other field without an excerpt is a ``seller_claim`` with low confidence and no evidence;
- what the buyer typed or answered is ``user_supplied``.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.db.ids import new_ulid
from app.db.repositories import EvidenceIn, EvidenceRow, FactIn, FactRow
from app.decision.classifier import Classification
from app.decision.enums import Confidence, FactKind
from app.decision.report_schema import EvidenceItem, ProductFact, ProductProfile
from app.decision.verification_engine import CertClaim, CertRecord
from app.coordinator.store import OrderInput
from app.services.tinyfish.evidence_capture import build_evidence_pairs
from app.services.tinyfish.models import ExtractionResult, RegistryResult

SPEC_PREFIX = "spec:"
USER_FIELDS = ("quantity", "purpose", "variant", "destination_state", "destination_city", "unit_price",
               "price_currency", "title", "category")
SELLER_CLAIM_FIELDS = frozenset({"certification_claims", "certification_numbers", "bis_registration_no",
                                 "manufacturer"})
_SCALAR_LISTING_FIELDS = ("title", "price", "currency", "moq", "manufacturer", "model", "origin")

# BIS CRS registration numbers look like R-41234567.
_BIS_NUMBER_RE = re.compile(r"\bR[- ]?\d{6,10}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CURRENCY_MARKERS = (("USD", "USD"), ("US$", "USD"), ("US $", "USD"), ("$", "USD"),
                     ("INR", "INR"), ("RS.", "INR"), ("RS ", "INR"), ("₹", "INR"))


def parse_price(text: Any, currency_hint: Any = None) -> Tuple[Optional[Decimal], Optional[str]]:
    """Read one unit price and its currency out of text such as 'US$10.00' or '$1.92-3.07'.

    For a two-number range (e.g. '$1.92-3.07'), returns the midpoint.
    Returns (None, ...) for more than two numbers or no number.
    The currency comes from the text, else from ``currency_hint``; it is None when neither names one.
    """
    if not isinstance(text, str) or not text.strip():
        return None, None
    numbers = _NUMBER_RE.findall(text)
    if len(numbers) == 2:
        # Price range — take the midpoint
        try:
            lo = Decimal(numbers[0].replace(",", ""))
            hi = Decimal(numbers[1].replace(",", ""))
            amount = (lo + hi) / 2
        except InvalidOperation:
            return None, None
    elif len(numbers) == 1:
        try:
            amount = Decimal(numbers[0].replace(",", ""))
        except InvalidOperation:
            return None, None
    else:
        return None, None
    upper = text.upper()
    currency = next((code for marker, code in _CURRENCY_MARKERS if marker in upper), None)
    if currency is None and isinstance(currency_hint, str):
        hint = currency_hint.strip().upper()
        currency = hint or None
    return amount, currency


def _first_bis_number(*texts: Any) -> Optional[str]:
    for text in texts:
        if isinstance(text, str):
            match = _BIS_NUMBER_RE.search(text)
            if match:
                return match.group(0).upper().replace(" ", "-")
    return None


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return str(value)


def build_listing_facts(
    result: ExtractionResult, investigation_id: str
) -> Tuple[List[FactIn], List[EvidenceIn]]:
    """Facts and evidence from a Task A result. Dict and list fields are flattened to scalar facts."""
    pairs = build_evidence_pairs(result, investigation_id)
    evidence_by_field: Dict[str, EvidenceItem] = {field: item for field, item in pairs}
    evidence = [EvidenceIn(id=item.id, source_url=item.source_url, retrieved_at=item.retrieved_at,
                           excerpt=item.excerpt, source_type=item.source_type) for _, item in pairs]
    facts: List[FactIn] = []

    def add(field: str, value: Any, source_field: str) -> None:
        item = evidence_by_field.get(source_field)
        if field in SELLER_CLAIM_FIELDS:
            kind = FactKind.seller_claim
            confidence = Confidence.medium if item else Confidence.low
        elif item is not None:
            kind, confidence = FactKind.confirmed, Confidence.high
        else:
            kind, confidence = FactKind.seller_claim, Confidence.low
        facts.append(FactIn(field=field, value=value, kind=kind, confidence=confidence,
                            evidence_id=item.id if item else None))

    fields = result.fields
    for name in _SCALAR_LISTING_FIELDS:
        value = fields.get(name)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            add(name, str(value), name)
    specs = fields.get("specs")
    if isinstance(specs, dict):
        for key, value in specs.items():
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                add(SPEC_PREFIX + key, str(value), "specs")
    for name in ("certification_claims", "certification_numbers"):
        value = fields.get(name)
        if value:
            add(name, _text(value), name)
    number = _first_bis_number(fields.get("certification_numbers") and _text(fields["certification_numbers"]),
                               fields.get("certification_claims") and _text(fields["certification_claims"]))
    if number:
        source = "certification_numbers" if "certification_numbers" in evidence_by_field else "certification_claims"
        add("bis_registration_no", number, source)

    amount, currency = parse_price(fields.get("price"), fields.get("currency"))
    price_item = evidence_by_field.get("price")
    if amount is not None and currency in ("USD", "INR"):
        for field, value in (("unit_price", format(amount, "f")), ("price_currency", currency)):
            facts.append(FactIn(field=field, value=value, kind=FactKind.confirmed if price_item else
                                FactKind.seller_claim, evidence_id=price_item.id if price_item else None,
                                confidence=Confidence.high if price_item else Confidence.low))
    return facts, evidence


def build_order_facts(order: OrderInput) -> List[FactIn]:
    """User-supplied facts from the order form. Seller certificates are claims relayed by the buyer."""
    facts = [FactIn(field="quantity", value=order.quantity, kind=FactKind.user_supplied)]
    for field, value in (("purpose", order.purpose), ("variant", order.variant),
                         ("destination_state", order.destination_state),
                         ("destination_city", order.destination_city)):
        if isinstance(value, str) and value.strip():
            facts.append(FactIn(field=field, value=value.strip(), kind=FactKind.user_supplied))
    number = _first_bis_number(*order.seller_certificates)
    if number:
        facts.append(FactIn(field="bis_registration_no", value=number, kind=FactKind.seller_claim,
                            confidence=Confidence.low))
    return facts


_INTERNAL_PREFIXES = ("rule_check:",)


def _latest(facts: Sequence[FactRow], include_internal: bool = False) -> Dict[str, FactRow]:
    """One fact per field. A user-supplied fact beats an extracted one; later beats earlier.

    Internal facts (e.g. ``rule_check:*``) are excluded unless ``include_internal=True``: they are used by the
    coordinator for persistence across restarts, not as product facts visible in the profile.
    """
    chosen: Dict[str, FactRow] = {}
    for fact in facts:
        if not include_internal and any(fact.field.startswith(p) for p in _INTERNAL_PREFIXES):
            continue
        current = chosen.get(fact.field)
        if current is None or current.kind is not FactKind.user_supplied or fact.kind is FactKind.user_supplied:
            chosen[fact.field] = fact
    return chosen


def fact_value(fact: FactRow) -> Any:
    return int(fact.value) if fact.field == "quantity" and fact.value.lstrip("-").isdigit() else fact.value


def profile_from_facts(facts: Sequence[FactRow]) -> ProductProfile:
    confirmed: List[ProductFact] = []
    claims: List[ProductFact] = []
    user: List[ProductFact] = []
    for fact in _latest(facts).values():
        item = ProductFact(field=fact.field, value=fact_value(fact), kind=fact.kind, evidence_id=fact.evidence_id)
        {FactKind.confirmed: confirmed, FactKind.seller_claim: claims, FactKind.user_supplied: user}[fact.kind] \
            .append(item)
    return ProductProfile(confirmed=confirmed, seller_claims=claims, user_supplied=user)


def extracted_from_facts(facts: Sequence[FactRow]) -> Dict[str, Any]:
    """The mapping the classifier reads: title, description, category, specifications, bluetooth."""
    latest = _latest(facts)
    out: Dict[str, Any] = {}
    for name in ("title", "model", "manufacturer"):
        if name in latest:
            out[name] = latest[name].value
    if "category" in latest and latest["category"].kind is not FactKind.user_supplied:
        out["category"] = latest["category"].value
    specs = {f.field[len(SPEC_PREFIX):]: f.value for f in latest.values() if f.field.startswith(SPEC_PREFIX)}
    if specs:
        out["specifications"] = specs
        for key, value in specs.items():
            if "bluetooth" in key.lower():
                out["bluetooth"] = value
    return out


def _mentions(extracted: Mapping[str, Any], needles: Sequence[str]) -> bool:
    haystack = " ".join([str(extracted.get("title", ""))] + [
        f"{k} {v}" for k, v in (extracted.get("specifications") or {}).items()]).lower()
    return any(n in haystack for n in needles)


def rule_profile(extracted: Mapping[str, Any], classification: Optional[Classification]) -> Dict[str, Any]:
    """Facts for the rule engine. A capability is set only when the listing shows it; an unseen one stays out of
    the profile so the rule reports unverified rather than 'not applicable'."""
    profile: Dict[str, Any] = {}
    if classification is not None and classification.category:
        profile["category"] = classification.category
    if _mentions(extracted, ("bluetooth",)):
        profile["has_bluetooth"] = True
    if _mentions(extracted, ("wifi", "wi-fi", "wlan")):
        profile["has_wifi"] = True
    if _mentions(extracted, ("battery", "mah", "lithium")):
        profile["has_battery"] = True
    return profile


def cert_claim_from_facts(facts: Sequence[FactRow]) -> Optional[CertClaim]:
    """The seller's claim, or None when no registration number was claimed anywhere."""
    latest = _latest(facts)
    reg = latest.get("bis_registration_no")
    if reg is None:
        return None
    return CertClaim(
        registration_no=reg.value,
        manufacturer=latest["manufacturer"].value if "manufacturer" in latest else None,
        model=latest["model"].value if "model" in latest else None,
    )


def _iso_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _scope(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[;,]", str(value or ""))
    return [p.strip() for p in parts if p.strip()]


def registry_record(
    result: RegistryResult, investigation_id: str
) -> Tuple[Optional[CertRecord], List[EvidenceIn]]:
    """An official record from a Task B result, with its evidence rows.

    No record is returned when the lookup failed or found nothing: the verification engine then reports
    unverified. The record's evidence is the first field excerpt in a stable order; without any excerpt the
    verification engine treats the record as unreliable.
    """
    pairs = build_evidence_pairs(result, investigation_id)
    evidence = [EvidenceIn(id=item.id, source_url=item.source_url, retrieved_at=item.retrieved_at,
                           excerpt=item.excerpt, source_type=item.source_type) for _, item in pairs]
    if result.failed or not result.record_found:
        return None, evidence
    by_field = dict(pairs)
    anchor = next((by_field[k] for k in ("registration_number", "manufacturer") if k in by_field),
                  pairs[0][1] if pairs else None)
    f = result.fields
    record = CertRecord(
        registration_no=f.get("registration_number"),
        manufacturer=f.get("manufacturer"),
        factory_location=f.get("factory_location"),
        model_scope=_scope(f.get("model_scope")),
        brand=f.get("brand"),
        valid_from=_iso_date(f.get("valid_from")),
        valid_to=_iso_date(f.get("valid_to")),
        status=f.get("status"),
        source_type="official_portal",
        source_url=result.source_url,
        evidence_id=anchor.id if anchor else None,
        excerpt=anchor.excerpt if anchor else None,
        retrieved_at=result.retrieved_at,
    )
    return record, evidence


def evidence_items(rows: Sequence[EvidenceRow]) -> List[EvidenceItem]:
    return [EvidenceItem(id=r.id, source_url=r.source_url, retrieved_at=r.retrieved_at, excerpt=r.excerpt or "",
                         source_type=r.source_type) for r in rows]


__all__ = ["build_listing_facts", "build_order_facts", "cert_claim_from_facts", "evidence_items",
           "extracted_from_facts", "parse_price", "profile_from_facts", "registry_record", "rule_profile",
           "new_ulid"]
