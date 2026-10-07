import re
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Set
from dataclasses import dataclass

@dataclass
class ResolvedEntity:
    ticker: str
    match_type: str
    confidence: float
    matched_text: str

class EntityResolver:
    COMPANY_REGISTRY = {
        "AAPL": {"canonical": "Apple", "aliases": ["Apple Inc", "Apple Corp"]},
        "MSFT": {"canonical": "Microsoft", "aliases": ["Microsoft Corp", "Microsoft Corporation"]},
        "NVDA": {"canonical": "NVIDIA", "aliases": ["Nvidia", "NVIDIA Corp", "NVIDIA Corporation"]},
        "AMZN": {"canonical": "Amazon", "aliases": ["Amazon.com", "Amazon Inc"]},
        "GOOGL": {"canonical": "Alphabet", "aliases": ["Google", "Alphabet Inc", "Google LLC"]},
        "META": {"canonical": "Meta Platforms", "aliases": ["Meta", "Facebook", "Meta Platforms Inc"]},
        "TSLA": {"canonical": "Tesla", "aliases": ["Tesla Inc", "Tesla Motors"]},
        "JPM": {"canonical": "JPMorgan Chase", "aliases": ["JPMorgan", "JP Morgan", "JPMorgan Chase & Co", "J.P. Morgan"]},
        "JNJ": {"canonical": "Johnson & Johnson", "aliases": ["J&J", "Johnson and Johnson"]},
        "XOM": {"canonical": "ExxonMobil", "aliases": ["Exxon", "Exxon Mobil", "ExxonMobil Corp"]}
    }

    AMBIGUOUS_NAMES = {"Apple", "Amazon", "Meta"}
    FINANCIAL_CONTEXT_WORDS = {"stock", "shares", "earnings", "revenue", "investor", "dividend", "nasdaq", "dow", "market", "inc", "corp", "ceo", "cfo", "quarter", "forecast", "production", "outlook"}

    @classmethod
    def normalize_text(cls, text: str) -> str:
        import html
        text = html.unescape(text)
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)
        text = text.strip('.,;:"\'()[]{}!?<>*-')
        return text

    @classmethod
    def resolve_entities(cls, text: str) -> List[ResolvedEntity]:
        normalized = cls.normalize_text(text)
        lower_text = normalized.lower()
        
        has_financial_context = any(word in lower_text for word in cls.FINANCIAL_CONTEXT_WORDS)
        
        resolved = []
        seen_tickers = set()

        for ticker, data in cls.COMPANY_REGISTRY.items():
            if ticker in seen_tickers:
                continue
                
            cashtag_pattern = r'\B\$' + re.escape(ticker) + r'(?![a-zA-Z0-9-])'
            cashtag_match = re.search(cashtag_pattern, normalized, re.IGNORECASE)
            ticker_pattern = r'(?<![a-zA-Z0-9-])' + re.escape(ticker) + r'(?![a-zA-Z0-9-])'
            ticker_match = re.search(ticker_pattern, normalized) 
            
            if cashtag_match:
                resolved.append(ResolvedEntity(ticker, "Cashtag", 1.0, cashtag_match.group()))
                seen_tickers.add(ticker)
                continue
            if ticker_match and ticker_match.group() == ticker:
                resolved.append(ResolvedEntity(ticker, "Exact Ticker", 1.0, ticker_match.group()))
                seen_tickers.add(ticker)
                continue

            canonical = data["canonical"]
            canon_pattern = r'(?<![a-zA-Z0-9-])' + re.escape(canonical) + r'(?![a-zA-Z0-9-])'
            canon_match = re.search(canon_pattern, normalized, re.IGNORECASE)
            if canon_match:
                if canonical in cls.AMBIGUOUS_NAMES and not has_financial_context:
                    pass
                else:
                    resolved.append(ResolvedEntity(ticker, "Canonical Name", 0.9, canon_match.group()))
                    seen_tickers.add(ticker)
                    continue

            for alias in data["aliases"]:
                alias_pattern = r'(?<![a-zA-Z0-9-])' + re.escape(alias) + r'(?![a-zA-Z0-9-])'
                alias_match = re.search(alias_pattern, normalized, re.IGNORECASE)
                if alias_match:
                    if alias in cls.AMBIGUOUS_NAMES and not has_financial_context:
                        pass
                    else:
                        resolved.append(ResolvedEntity(ticker, "Alias", 0.85, alias_match.group()))
                        seen_tickers.add(ticker)
                        break

        return resolved

class SemanticDedup:
    POSITIVE_WORDS = {"rises", "rally", "gains", "surges", "jumps", "beats", "up", "increases", "growth", "rise"}
    NEGATIVE_WORDS = {"falls", "drops", "declines", "slumps", "plunges", "misses", "down", "decreases", "loss", "fall"}

    def __init__(self, time_window_hours: int = 24):
        self.time_window_hours = time_window_hours

    @staticmethod
    def get_document_hash(normalized_text: str) -> str:
        return hashlib.sha256(normalized_text.lower().encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_jaccard(text1: str, text2: str) -> float:
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        if not set1 or not set2:
            return 0.0
        return len(set1.intersection(set2)) / len(set1.union(set2))

    @classmethod
    def get_direction(cls, text: str) -> str:
        words = set(text.lower().split())
        has_pos = bool(words.intersection(cls.POSITIVE_WORDS))
        has_neg = bool(words.intersection(cls.NEGATIVE_WORDS))
        
        if has_pos and not has_neg:
            return "positive"
        elif has_neg and not has_pos:
            return "negative"
        return "unknown"

    def check_duplicate(self, norm_headline: str, entities: Set[str], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        candidates: list of dicts with 'normalized_headline', 'resolved_entities', 'canonical_group_id'
        """
        doc_hash = self.get_document_hash(norm_headline)
        direction = self.get_direction(norm_headline)
        
        for cand in candidates:
            cand_entities = set(cand.get("resolved_entities", "").split(",")) if cand.get("resolved_entities") else set()
            
            # Fast rejection: no shared entities (and both have entities)
            if entities and cand_entities and not entities.intersection(cand_entities):
                continue
                
            # 1. Exact Deduplication
            cand_headline = cand.get("normalized_headline", "")
            if cand.get("document_hash") == doc_hash or cand_headline.lower() == norm_headline.lower():
                return {
                    "is_duplicate": True,
                    "reason": "Exact textual match after normalization",
                    "canonical_group_id": cand.get("canonical_group_id") or cand.get("document_hash")
                }
            
            # 2. Semantic Deduplication
            sim = self.calculate_jaccard(norm_headline, cand_headline)
            if sim >= 0.4:
                cand_direction = self.get_direction(cand_headline)
                
                # Check for opposing directions
                if direction != "unknown" and cand_direction != "unknown" and direction != cand_direction:
                    continue  # They are opposite, so they are not duplicates
                
                direction_str = "compatible_event_direction" if direction == cand_direction and direction != "unknown" else "unknown_direction"
                if direction != "unknown" and cand_direction != "unknown" and direction != cand_direction:
                    pass # We already continue above, but logic wise this handles the reason.
                
                return {
                    "is_duplicate": True, 
                    "reason": f"High text similarity ({sim:.2f}) + shared entity + within {self.time_window_hours}h + {direction_str}",
                    "canonical_group_id": cand.get("canonical_group_id") or cand.get("document_hash")
                }
                
        return {
            "is_duplicate": False, 
            "reason": "New unique event",
            "canonical_group_id": doc_hash
        }
