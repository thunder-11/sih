"""
Fraud Typology Classifier (PRD §3 FR-4.1).
Heuristic keyword-based classifier for hackathon — maps complaint text
to standardized Indian cybercrime fraud typologies.
"""
import re

TYPOLOGY_KEYWORDS = {
    "TASK_BASED_SCAM": [
        "task", "rating", "review", "telegram", "like", "subscribe", "youtube",
        "google maps", "daily return", "commission", "prepaid", "advance",
        "part time", "part-time", "work from home", "data entry",
    ],
    "INVESTMENT_PONZI_SCAM": [
        "invest", "trading", "profit", "return", "guaranteed", "forex", "binary",
        "portfolio", "mutual fund", "stock", "crypto trading", "whatsapp group",
        "high return", "doubl", "100%", "200%", "mining",
    ],
    "DIGITAL_ARREST_EXTORTION": [
        "cbi", "police", "arrest", "warrant", "narcotics", "ndps", "customs",
        "ed", "enforcement directorate", "digital arrest", "video call",
        "verification", "aadhaar", "courier", "parcel", "drugs",
    ],
    "SEXTORTION_BLACKMAIL": [
        "video call", "nude", "intimate", "blackmail", "record", "screenshot",
        "morphed", "sex", "honey trap", "dating", "relationship",
    ],
    "RANSOMWARE_PAYMENT": [
        "ransomware", "encrypt", "locked", "decrypt", "ransom", "bitcoin",
        "pay to unlock", "cryptolocker", "locker", "files encrypted",
    ],
    "PHISHING_DRAINER": [
        "phishing", "fake website", "clone", "approval", "dapp", "connect wallet",
        "seed phrase", "private key", "metamask", "drainer", "uniswap",
        "pancakeswap", "airdrop", "nft mint",
    ],
    "DARKNET_FINANCIAL_CRIME": [
        "darknet", "dark web", "tor", "hawala", "money laundering",
        "underground", "contraband", "illegal", "drug", "weapon",
    ],
}


def classify_typology(complaint_text: str, provided_typology: str = None) -> dict:
    """
    Classify complaint text into fraud typology.
    If a typology is already provided (from NCRP form), validate and return it.
    Otherwise, classify from text using keyword matching.
    """
    if provided_typology and provided_typology in TYPOLOGY_KEYWORDS:
        # Validate provided typology — compute confidence based on text match
        text_lower = complaint_text.lower() if complaint_text else ""
        keywords = TYPOLOGY_KEYWORDS[provided_typology]
        matches = sum(1 for kw in keywords if kw in text_lower)
        confidence = min(95, 60 + matches * 10)
        return {
            "classified_typology": provided_typology,
            "confidence": confidence,
            "method": "PROVIDED_VALIDATED",
            "matched_keywords": matches,
        }

    if not complaint_text:
        return {
            "classified_typology": provided_typology or "TASK_BASED_SCAM",
            "confidence": 30,
            "method": "DEFAULT_FALLBACK",
            "matched_keywords": 0,
        }

    text_lower = complaint_text.lower()
    scores = {}

    for typology, keywords in TYPOLOGY_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword in text_lower:
                score += 1
                # Bonus for longer, more specific keywords
                if len(keyword) > 8:
                    score += 1
        scores[typology] = score

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {
            "classified_typology": provided_typology or "TASK_BASED_SCAM",
            "confidence": 30,
            "method": "NO_MATCH_FALLBACK",
            "matched_keywords": 0,
        }

    confidence = min(90, 50 + best_score * 10)

    return {
        "classified_typology": best,
        "confidence": confidence,
        "method": "NLP_KEYWORD_CLASSIFICATION",
        "matched_keywords": best_score,
    }


TYPOLOGY_LABELS = {
    "TASK_BASED_SCAM": "Task-Based / Part-Time Job Scam",
    "INVESTMENT_PONZI_SCAM": "Investment / Trading Ponzi Scam",
    "DIGITAL_ARREST_EXTORTION": "Digital Arrest Extortion",
    "SEXTORTION_BLACKMAIL": "Sextortion / Blackmail",
    "RANSOMWARE_PAYMENT": "Ransomware Payment",
    "PHISHING_DRAINER": "Phishing / Wallet Drainer",
    "DARKNET_FINANCIAL_CRIME": "Darknet / Financial Crime",
}
