"""Rate fetchers.

Only FixtureFetcher (for tests) exists. The live TinyFish adapter is a later step and is NOT implemented here;
no HTTP or TinyFish call is made anywhere in this package. When it is built, every Candidate it returns must
carry the source URL, the retrieval time (timezone-aware, supplied by the adapter) and the supporting excerpt as
found on the page. It must not bypass CAPTCHA, authentication or anti-bot restrictions, and page text stays
untrusted data. Tier claims from a fetcher are advisory: the checks recompute tiers from policy.yaml.
"""
from typing import Dict, List, Mapping, Optional, Protocol, Sequence, runtime_checkable

from app.decision.rates.models import Candidate


@runtime_checkable
class RateFetcher(Protocol):
    def fetch(self, rate_key: str) -> List[Candidate]:
        """Candidates for one rate_key. May raise; the updater records a fetch_error and continues."""
        ...


class FixtureFetcher:
    """Returns fixed candidates per rate_key, or raises a configured error for a key.

    Every candidate it returns is marked is_fixture=True, so proposals built from it show
    "FIXTURE DATA, NOT REAL EVIDENCE" and cannot be approved without an explicit --allow-fixture.
    """

    def __init__(
        self,
        fixtures: Mapping[str, Sequence[Candidate]],
        errors: Optional[Mapping[str, Exception]] = None,
    ):
        self._fixtures: Dict[str, List[Candidate]] = {key: list(items) for key, items in fixtures.items()}
        self._errors: Dict[str, Exception] = dict(errors or {})
        self.calls: List[str] = []

    def fetch(self, rate_key: str) -> List[Candidate]:
        self.calls.append(rate_key)
        if rate_key in self._errors:
            raise self._errors[rate_key]
        return [c.model_copy(update={"is_fixture": True}) for c in self._fixtures.get(rate_key, [])]
