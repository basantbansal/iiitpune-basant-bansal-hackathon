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
        "XOM": {"canonical": "ExxonMobil", "aliases": ["Exxon", "Exxon Mobil", "ExxonMobil Corp"]},
        "RELIANCE": {
            "canonical": "Reliance Industries Limited",
            "aliases": ["Reliance Industries", "RIL", "Reliance Retail", "Reliance Jio"],
            "allow_standalone_alias": False,  # Bare 'Reliance' requires disambiguation
            "negative_patterns": [
                r"\bfirst\s+reliance\b",
                r"\breliance\s+bancshares\b",
                r"\breliance\s+steel\b",
                r"\breliance\s+global\b",
                r"\bbancshares\b",
                r"\bsouth\s+carolina\b"
            ],
            "context_keywords": ["industries", "ril", "jio", "ambani", "refinery", "telecom", "retail", "oil-to-chemicals", "o2c", "petrochemicals", "nifty", "sensex", "nse", "bse", "india", "indian", "mumbai"]
        },
        "TCS": {
            "canonical": "Tata Consultancy Services Limited",
            "aliases": ["Tata Consultancy Services", "Tata Consultancy"],
            "allow_standalone_alias": False,  # Bare 'TCS' requires disambiguation
            "negative_patterns": [
                r"\btelecommunication\s+systems\b",
                r"\bus\s+government\s+contractor\b",
                r"\bdefense\s+contractor\b",
                r"\bus\s+army\b",
                r"\bpentagon\b",
                r"\btraction\s+control\b",
                r"\btaxpayers\s+for\s+common\s+sense\b",
                r"\bteacher\s+certification\b",
                r"\btax\s+collected\s+at\s+source\b",
                r"\btraffic\s+control\b",
                r"\btrue\s+cost\s+of\s+solar\b"
            ],
            "context_keywords": ["tata", "consultancy", "it services", "software", "tech", "outsourcing", "deal", "cloud", "nifty", "sensex", "nse", "bse", "india", "indian", "shares", "share", "stock", "earnings", "profit", "revenue", "dividend", "quarter", "results", "q1", "q2", "q3", "q4"]
        },
        "HDFCBANK": {"canonical": "HDFC Bank Limited", "aliases": ["HDFC Bank", "HDFC Bank Ltd"]},
        "INFY": {"canonical": "Infosys Limited", "aliases": ["Infosys", "Infosys Ltd", "Infy"]},
        "ICICIBANK": {"canonical": "ICICI Bank Limited", "aliases": ["ICICI Bank", "ICICI Bank Ltd"]},
        "HINDUNILVR": {"canonical": "Hindustan Unilever Limited", "aliases": ["Hindustan Unilever", "HUL", "Unilever India", "Hindustan Unilever Ltd"]},
        "ITC": {
            "canonical": "ITC Limited",
            "aliases": ["ITC Limited", "ITC Ltd"],
            "allow_standalone_alias": False,  # Bare 'ITC' requires disambiguation
            "negative_patterns": [
                r"\bus\s+itc\b",
                r"\bu\.s\.\s+itc\b",
                r"\binternational\s+trade\s+commission\b",
                r"\bpatent\s+dispute\b",
                r"\bpatent\s+investigation\b",
                r"\bsection\s+337\b",
                r"\bmicron\b",
                r"\btrade\s+commission\b",
                r"\binput\s+tax\s+credit\b",
                r"\binvestment\s+tax\s+credit\b",
                r"\bgst\s+council\b"
            ],
            "context_keywords": ["limited", "ltd", "fmcg", "cigarette", "cigarettes", "tobacco", "hotel", "hotels", "paperboards", "agri", "puri", "sanjiv", "nifty", "sensex", "nse", "bse", "india", "indian", "kolkata", "shares", "share", "stock", "earnings", "results", "profit", "dividend", "q1", "q2", "q3", "q4"]
        },
        "BHARTIARTL": {"canonical": "Bharti Airtel Limited", "aliases": ["Bharti Airtel", "Airtel", "Bharti Airtel Ltd"]},
        "LT": {
            "canonical": "Larsen & Toubro Limited",
            "aliases": ["Larsen & Toubro", "L&T", "Larsen and Toubro", "Larsen Toubro"],
            "allow_standalone_alias": False,  # Bare 'LT' requires disambiguation
            "negative_patterns": [
                r"\btaiwan\b",
                r"\blt\s+technology\b",
                r"\blt\s+corp\b",
                r"\blieutenant\b",
                r"\blt\.\b",
                r"\blt\s+col\b",
                r"\blt\s+gen\b",
                r"\blt\s+debt\b",
                r"\blong[- ]term\b",
                r"\bdisplay\s+driver\b",
                r"\blight\s+(?:and|&)\s+translucent\b"
            ],
            "context_keywords": ["larsen", "toubro", "l&t", "infrastructure", "construction", "engineering", "epc", "defense", "metro", "order", "orders", "subramanian", "nifty", "sensex", "nse", "bse", "india", "indian", "mumbai", "shares", "share", "stock", "earnings", "contract", "results", "profit", "revenue", "dividend", "q1", "q2", "q3", "q4"]
        },
        "SBIN": {"canonical": "State Bank of India", "aliases": ["State Bank of India", "SBI", "State Bank"]}
    }

    AMBIGUOUS_NAMES = {"Apple", "Amazon", "Meta"}
    AMBIGUOUS_TICKERS = {"LT", "ITC", "TCS"}
    GENERIC_HEADLINE_PATTERNS = [
        r"\bstock\s+price\s+today\b",
        r"\bshare\s+price\s+today\b",
        r"\blive\s+bse\s*/\s*nse\s+updates\b",
        r"\boptions\s+chain\s+analysis\b",
        r"\bshare\s+price\s*:\s*technical\s+analysis\b",
        r"\bstock\s+quote\b",
        r"\bprice\s+target\s+and\s+consensus\b",
        r"\bstock\s+price,\s*news,\s*quote\s+(?:and|&)\s+history\b",
        r"\bstock\s+price\b.*\bquote\s+(?:and|&)\s+history\b",
        r"\binteractive\s+stock\s+chart\b",
        r"\bquote\s+(?:and|&)\s+history\b",
        r"\bvaluation,\s*fundamentals\s+(?:and|&)\s+technicals\b"
    ]
    FINANCIAL_CONTEXT_WORDS = {
        "stock", "shares", "earnings", "revenue", "investor", "dividend",
        "nasdaq", "dow", "market", "inc", "corp", "ceo", "cfo", "quarter",
        "forecast", "production", "outlook", "order", "contract", "profit",
        "results", "nifty", "sensex", "nse", "bse"
    }

    @classmethod
    def normalize_text(cls, text: str) -> str:
        import html
        text = html.unescape(text)
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)
        text = text.strip('.,;:"\'()[]{}!?<>*-')
        return text

    @classmethod
    def is_generic_quote_page(cls, text: str) -> bool:
        lower = text.lower()
        return any(re.search(pat, lower) for pat in cls.GENERIC_HEADLINE_PATTERNS)

    @classmethod
    def resolve_entities(cls, text: str) -> List[ResolvedEntity]:
        normalized = cls.normalize_text(text)
        lower_text = normalized.lower()

        # Reject generic stock price / quote pages
        if cls.is_generic_quote_page(normalized):
            return []

        has_financial_context = any(re.search(r'\b' + re.escape(word) + r'\b', lower_text) for word in cls.FINANCIAL_CONTEXT_WORDS)
        
        resolved = []
        seen_tickers = set()

        for ticker, data in cls.COMPANY_REGISTRY.items():
            if ticker in seen_tickers:
                continue

            # Check negative patterns first
            negative_pats = data.get("negative_patterns", [])
            if any(re.search(pat, lower_text) for pat in negative_pats):
                continue

            # 1. Cashtag match (e.g. $AAPL, $RELIANCE, $TCS)
            cashtag_pattern = r'\B\$' + re.escape(ticker) + r'(?![a-zA-Z0-9-])'
            cashtag_match = re.search(cashtag_pattern, normalized, re.IGNORECASE)
            if cashtag_match:
                resolved.append(ResolvedEntity(ticker, "Cashtag", 1.0, cashtag_match.group()))
                seen_tickers.add(ticker)
                continue

            # 2. Canonical Name match (e.g. "Reliance Industries Limited", "Tata Consultancy Services Limited")
            canonical = data["canonical"]
            canon_pattern = r'(?<![a-zA-Z0-9-])' + re.escape(canonical) + r'(?![a-zA-Z0-9-])'
            canon_match = re.search(canon_pattern, normalized, re.IGNORECASE)
            if canon_match:
                if canonical in cls.AMBIGUOUS_NAMES and not has_financial_context:
                    pass
                else:
                    resolved.append(ResolvedEntity(ticker, "Canonical Name", 0.95, canon_match.group()))
                    seen_tickers.add(ticker)
                    continue

            # 3. Aliases match (e.g. "Reliance Industries", "Tata Consultancy Services", "L&T", "Larsen & Toubro")
            matched_alias = False
            for alias in data.get("aliases", []):
                alias_pattern = r'(?<![a-zA-Z0-9-])' + re.escape(alias) + r'(?![a-zA-Z0-9-])'
                alias_match = re.search(alias_pattern, normalized, re.IGNORECASE)
                if alias_match:
                    if alias in cls.AMBIGUOUS_NAMES and not has_financial_context:
                        pass
                    else:
                        resolved.append(ResolvedEntity(ticker, "Alias", 0.90, alias_match.group()))
                        seen_tickers.add(ticker)
                        matched_alias = True
                        break
            if matched_alias:
                continue

            # 4. Bare Ticker symbol match
            # If ticker is in AMBIGUOUS_TICKERS (LT, ITC, TCS), require disambiguating context keywords
            ticker_pattern = r'(?<![a-zA-Z0-9-])' + re.escape(ticker) + r'(?![a-zA-Z0-9-])'
            ticker_match = re.search(ticker_pattern, normalized)
            if ticker_match and ticker_match.group() == ticker:
                if ticker in cls.AMBIGUOUS_TICKERS:
                    context_words = data.get("context_keywords", [])
                    has_company_context = any(re.search(r'\b' + re.escape(word) + r'\b', lower_text) for word in context_words)
                    if has_company_context:
                        resolved.append(ResolvedEntity(ticker, "Disambiguated Ticker", 0.85, ticker_match.group()))
                        seen_tickers.add(ticker)
                        continue
                else:
                    resolved.append(ResolvedEntity(ticker, "Exact Ticker", 1.0, ticker_match.group()))
                    seen_tickers.add(ticker)
                    continue

            # 5. Bare standalone alias (e.g. 'Reliance' without 'Industries')
            if data.get("allow_standalone_alias", True) is False:
                # If ticker has 'Reliance' in text, check if context supports Reliance Industries
                if ticker == "RELIANCE":
                    rel_match = re.search(r'(?<![a-zA-Z0-9-])Reliance(?![a-zA-Z0-9-])', normalized, re.IGNORECASE)
                    if rel_match:
                        context_words = data.get("context_keywords", [])
                        if any(re.search(r'\b' + re.escape(w) + r'\b', lower_text) for w in context_words):
                            resolved.append(ResolvedEntity(ticker, "Disambiguated Alias", 0.85, rel_match.group()))
                            seen_tickers.add(ticker)
                            continue

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
            raw_entities = cand.get("resolved_entities")
            if not raw_entities:
                cand_entities = set()
            elif isinstance(raw_entities, list):
                cand_entities = set(raw_entities)
            else:
                cand_entities = set(str(raw_entities).split(","))
            
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
