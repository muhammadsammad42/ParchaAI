"""
Medicine name pronunciation resolution for ParchaAI Urdu TTS pipeline.

Resolves English medicine names to Urdu script using a 3-tier fallback:
1. Manual dictionary lookup (~30 curated entries)
2. G2P (Grapheme-to-Phoneme) → ARPAbet → Urdu character mapping
3. LLM (Groq) fallback for edge cases

All results are cached in-memory and on-disk. Names reaching tier 2 or 3
are logged for manual review.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Separate logger for pronunciation review (tier 2/3 fallbacks)
review_logger = logging.getLogger("pronunciation_review")
review_handler = None  # Initialized in _ensure_review_log()


class PronunciationError(Exception):
    """Raised when pronunciation resolution fails unrecoverably."""
    pass


# =============================================================================
# MANUAL DICTIONARY (~30 approved entries - needs native speaker verification)
# =============================================================================
# NOTE: These entries require verification by a native Urdu speaker before
# production use. Do NOT silently expand this dictionary without review.

MANUAL_DICT: Dict[str, str] = {
    "Augmentin": "اگمینٹن",
    "Paracetamol": "پیراسیٹامول",
    "Azithromycin": "ازیتھرومائسن",
    "Amoxicillin": "اموکسیسلن",
    "Ciprofloxacin": "سپروفلوکساسن",
    "Metformin": "میٹفارمن",
    "Omeprazole": "اومیپرازول",
    "Ibuprofen": "آئبوپروفین",
    "Aspirin": "اسپرین",
    "Cefixime": "سیفکسیم",
    "Clarithromycin": "کلیریتھرومائسن",
    "Doxycycline": "ڈوکسی سائکلین",
    "Erythromycin": "اریتھرومائسن",
    "Fluconazole": "فلوکونازول",
    "Gentamicin": "جینٹامائسن",
    "Hydroxyzine": "ہائیڈروکسیزین",
    "Insulin": "انسولن",
    "Ketoconazole": "کیٹوکونازول",
    "Levofloxacin": "لیووفلوکساسن",
    "Moxifloxacin": "موکسی فلوکساسن",
    "Naproxen": "نیپروکسن",
    "Ofloxacin": "اوفلوکساسن",
    "Prednisolone": "پریڈنیسولون",
    "Quinolone": "کوئنولون",
    "Ranitidine": "رینیٹیڈین",
    "Salbutamol": "سالبیوٹامول",
    "Tramadol": "ٹرامادول",
    "Ursodeoxycholic": "ارسوڈیاکسیکولک",
    "Vitamin": "وٹامن",
    "Warfarin": "وارفرین",
    "Xylocaine": "زائلوکین",
    "Zolpidem": "زولپیڈیم",
}


# =============================================================================
# ARPABET → URDU MAPPING TABLE (~40 phonemes)
# =============================================================================
# CORRECTED: Vowel diacritics now anchored to alif for reliable TTS pronunciation.
# See DIACRITIC_TEST_RESULTS.md for rationale.

ARPABET_TO_URDU: Dict[str, str] = {
    # --- Vowels (anchored to alif for audible pronunciation) ---
    "AA": "ا",      # long 'a' as in "father"
    "AE": "اَ",      # short 'a' as in "cat" (anchored zabar)
    "AH": "اَ",      # schwa as in "about" (anchored zabar)
    "AO": "او",     # 'o' as in "bought"
    "AW": "او",     # diphthong as in "down"
    "AY": "ائ",     # diphthong as in "ice"
    "EH": "ے",      # short 'e' as in "bed"
    "ER": "اَر",     # 'er' as in "butter" (vowel + consonant, anchored)
    "EY": "ای",     # long 'e' as in "ate"
    "IH": "اِ",      # short 'i' as in "kit" (anchored zer)
    "IY": "ی",      # long 'i' as in "see"
    "OW": "و",      # long 'o' as in "go"
    "OY": "وئ",     # diphthong as in "boy"
    "UH": "اُ",      # short 'u' as in "put" (anchored pesh)
    "UW": "و",      # long 'u' as in "food"
    # NOTE: OW/UW both map to و intentionally - Urdu doesn't distinguish these long vowels cleanly
    # NOTE: AW/AO both map to او intentionally - similar sounds in Urdu context
    
    # --- Consonants ---
    "B": "ب",
    "CH": "چ",
    "D": "ڈ",       # retroflex 'd'
    "DH": "دھ",      # voiced 'th' as in "this" (corrected from plain د)
    "F": "ف",
    "G": "گ",
    "HH": "ہ",
    "JH": "ج",
    "K": "ک",
    "L": "ل",
    "M": "م",
    "N": "ن",
    "NG": "نگ",     # 'ng' as in "sing"
    "P": "پ",
    "R": "ر",
    "S": "س",
    "SH": "ش",
    "T": "ٹ",       # retroflex 't'
    "TH": "تھ",      # voiceless 'th' as in "think"
    "V": "و",
    "W": "و",
    "Y": "ی",
    "Z": "ز",
    "ZH": "ژ",      # 'zh' as in "measure"
    
    # --- Stress markers (ignored) ---
    "0": "",        # no stress
    "1": "",        # primary stress
    "2": "",        # secondary stress
}


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

_cache: Optional[Dict] = None  # In-memory cache
_cache_path = Path("cache/pronunciation_cache.json")


def _load_cache() -> Dict:
    """Load pronunciation cache from disk, or initialize empty if missing."""
    global _cache
    
    if _cache is not None:
        return _cache
    
    if _cache_path.exists():
        try:
            with open(_cache_path, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info(f"Loaded pronunciation cache: {len(_cache.get('pronunciations', {}))} entries")
        except Exception as e:
            logger.warning(f"Failed to load cache, initializing empty: {e}")
            _cache = _create_empty_cache()
    else:
        _cache = _create_empty_cache()
        logger.info("Pronunciation cache initialized (empty)")
    
    return _cache


def _create_empty_cache() -> Dict:
    """Create empty cache structure."""
    return {
        "version": "1.0",
        "last_updated": datetime.now().isoformat(),
        "pronunciations": {}
    }


def _save_cache() -> None:
    """Save pronunciation cache to disk."""
    global _cache
    
    if _cache is None:
        return
    
    _cache["last_updated"] = datetime.now().isoformat()
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(_cache_path, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved pronunciation cache: {len(_cache['pronunciations'])} entries")
    except Exception as e:
        logger.error(f"Failed to save pronunciation cache: {e}")


def _cache_pronunciation(medicine_name: str, urdu: str, source: str, arpabet: Optional[str] = None) -> None:
    """Add pronunciation to cache."""
    cache = _load_cache()
    
    cache["pronunciations"][medicine_name] = {
        "urdu": urdu,
        "source": source,
        "timestamp": datetime.now().isoformat(),
    }
    
    if arpabet:
        cache["pronunciations"][medicine_name]["arpabet"] = arpabet
    
    _save_cache()


def _get_cached_pronunciation(medicine_name: str) -> Optional[str]:
    """Retrieve pronunciation from cache, or None if not found."""
    cache = _load_cache()
    entry = cache["pronunciations"].get(medicine_name)
    
    if entry:
        logger.debug(f"Cache hit: {medicine_name} → {entry['urdu']} (source: {entry['source']})")
        return entry["urdu"]
    
    return None


# =============================================================================
# REVIEW LOGGING (for tier 2/3 fallbacks)
# =============================================================================

def _ensure_review_log():
    """Initialize separate log file for tier 2/3 pronunciation reviews."""
    global review_handler
    
    if review_handler is not None:
        return
    
    review_log_path = Path("cache/pronunciation_review.log")
    review_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    review_handler = logging.FileHandler(review_log_path, encoding="utf-8")
    review_handler.setLevel(logging.INFO)
    review_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    review_logger.addHandler(review_handler)
    review_logger.setLevel(logging.INFO)
    review_logger.propagate = False  # Don't propagate to root logger


def _log_for_review(medicine_name: str, tier: int, urdu: str, details: str = ""):
    """Log pronunciations that need manual review (tier 2 or 3)."""
    _ensure_review_log()
    
    tier_name = {2: "G2P", 3: "LLM"}[tier]
    review_logger.info(
        f"TIER {tier} ({tier_name}) | {medicine_name} → {urdu} | {details}"
    )


# =============================================================================
# MEDICINE NAME NORMALIZATION (Step 1)
# =============================================================================
# Strip trailing route/form words to extract core drug name for pronunciation.
# This is ONLY for pronunciation resolution input — full name used everywhere else.

# Explicit list of route/form suffixes to strip (order matters: longest first)
ROUTE_FORM_SUFFIXES = [
    "ear drops",
    "eye drops", 
    "nasal drops",
    "drops",
    "syrup",
    "tablet",
    "tablets",
    "capsule",
    "capsules",
    "injection",
    "suspension",
    "cream",
    "ointment",
    "gel",
    "solution",
    "tab.",
    "tab",
    "cap.",
    "cap",
    "inj.",
    "inj",
    "susp.",
    "susp",
]


def _normalize_for_pronunciation(medicine_name: str) -> str:
    """
    Extract core drug name for pronunciation by stripping route/form suffixes.
    
    This normalization is ONLY for pronunciation resolution input.
    The full original name is still used everywhere else (display, dosage, matching).
    
    Examples:
        "Candibiotic ear drops" → "Candibiotic"
        "Taxim O drops" → "Taxim O"
        "Tab. Augmentin" → "Augmentin"
        "Paracetamol" → "Paracetamol" (unchanged)
    
    Parameters
    ----------
    medicine_name : str
        Full medicine name as extracted
    
    Returns
    -------
    str
        Core drug name, or original name if stripping results in empty string
    """
    normalized = medicine_name.strip()
    normalized_lower = normalized.lower()
    
    # Try stripping each suffix (longest first to avoid partial matches)
    for suffix in ROUTE_FORM_SUFFIXES:
        if normalized_lower.endswith(suffix):
            # Strip suffix and any preceding whitespace/punctuation
            core_name = normalized[:-(len(suffix))].rstrip(" .-")
            
            # If result is non-empty, use it; otherwise try next suffix
            if core_name.strip():
                logger.debug(f"Normalized for pronunciation: '{medicine_name}' → '{core_name}'")
                return core_name.strip()
    
    # No suffix matched or stripping resulted in empty string — return original
    return normalized


# =============================================================================
# TIER 1: MANUAL DICTIONARY LOOKUP
# =============================================================================

def _lookup_manual_dict(medicine_name: str) -> Optional[str]:
    """Tier 1: Lookup in manual curated dictionary."""
    # Case-insensitive lookup
    for key, value in MANUAL_DICT.items():
        if key.lower() == medicine_name.lower():
            logger.debug(f"Manual dict hit: {medicine_name} → {value}")
            return value
    return None


# =============================================================================
# TIER 2: G2P + ARPABET → URDU MAPPING
# =============================================================================

def _g2p_to_urdu(medicine_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Tier 2: Convert medicine name to Urdu via G2P → ARPAbet → Urdu mapping.
    
    Returns
    -------
    tuple of (urdu_string or None, arpabet_string or None)
    """
    try:
        from g2p_en import G2p
    except ImportError:
        logger.warning("g2p_en not installed, skipping tier 2")
        return None, None
    
    try:
        g2p = G2p()
        phonemes = g2p(medicine_name)
        
        if not phonemes:
            logger.debug(f"G2P returned empty for: {medicine_name}")
            return None, None
        
        # Convert list of phonemes to string for logging
        arpabet_str = " ".join(phonemes)
        logger.debug(f"G2P phonemes for '{medicine_name}': {arpabet_str}")
        
        # Map each ARPAbet phoneme to Urdu (Step 2: fail-safe mapping)
        urdu_chars = []
        unknown_phonemes = []
        
        for phoneme in phonemes:
            # Remove stress markers (0, 1, 2) from end of phoneme
            phoneme_clean = re.sub(r'[012]$', '', phoneme)
            
            # Skip empty phonemes (e.g., from extra spaces)
            if not phoneme_clean:
                continue
            
            urdu_char = ARPABET_TO_URDU.get(phoneme_clean)
            
            if urdu_char is not None:
                urdu_chars.append(urdu_char)
            else:
                # Unknown/unmapped phoneme: log to review but DON'T add to output
                unknown_phonemes.append(phoneme_clean)
        
        # Log unknown phonemes to review log (not main log to avoid spam)
        if unknown_phonemes:
            _ensure_review_log()
            review_logger.warning(
                f"Unknown ARPAbet phoneme(s) in '{medicine_name}': {', '.join(unknown_phonemes)} | "
                f"Full ARPAbet: {arpabet_str}"
            )
        
        urdu_result = "".join(urdu_chars)
        
        # Sanity check: result must be non-empty, contain Urdu characters, and be >= 2 chars
        if not urdu_result or len(urdu_result) < 2:
            logger.debug(f"G2P sanity check failed (too short): {medicine_name} → {urdu_result}")
            return None, arpabet_str
        
        # Check if result contains actual Urdu characters (Unicode range U+0600–U+06FF)
        if not re.search(r'[\u0600-\u06FF]', urdu_result):
            logger.debug(f"G2P sanity check failed (no Urdu chars): {medicine_name} → {urdu_result}")
            return None, arpabet_str
        
        logger.debug(f"G2P success: {medicine_name} → {urdu_result}")
        return urdu_result, arpabet_str
        
    except Exception as e:
        logger.warning(f"G2P failed for {medicine_name}: {e}")
        return None, None


# =============================================================================
# TIER 3: LLM FALLBACK (Groq)
# =============================================================================

def _llm_transliterate(medicine_name: str) -> Optional[str]:
    """
    Tier 3: LLM fallback for edge cases where G2P fails sanity check.
    
    Prompts Groq to transliterate a single medicine name to Urdu script.
    """
    try:
        from groq import Groq
        from .config import get_config
        
        config = get_config()
        if not config.groq_api_key:
            logger.warning("GROQ_API_KEY not configured, skipping tier 3")
            return None
        
        client = Groq(api_key=config.groq_api_key)
        
        # Simple, focused prompt for single-name transliteration
        prompt = f"Transliterate this English medicine name to Urdu script only: {medicine_name}. Output only the Urdu word, no explanation, no Roman Urdu, no English."
        
        response = client.chat.completions.create(
            model=config.urdu_model,  # Reuse same model as Urdu explanation
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  # Low temperature for consistency
            max_tokens=50,    # Short output expected
        )
        
        content = response.choices[0].message.content if response.choices else None
        
        if not content:
            logger.warning(f"LLM returned empty for: {medicine_name}")
            return None
        
        # Clean up: remove any English text, punctuation, whitespace
        urdu_result = content.strip()
        
        # Remove any English letters that might have leaked through
        urdu_result = re.sub(r'[A-Za-z]', '', urdu_result)
        urdu_result = urdu_result.strip()
        
        # Sanity check: must contain Urdu characters
        if not re.search(r'[\u0600-\u06FF]', urdu_result):
            logger.warning(f"LLM sanity check failed (no Urdu): {medicine_name} → {urdu_result}")
            return None
        
        logger.debug(f"LLM success: {medicine_name} → {urdu_result}")
        return urdu_result
        
    except Exception as e:
        logger.error(f"LLM fallback failed for {medicine_name}: {e}")
        return None


# =============================================================================
# PUBLIC API
# =============================================================================

def resolve_pronunciation(medicine_name: str) -> str:
    """
    Resolve English medicine name to Urdu script pronunciation.
    
    Uses 3-tier fallback: manual dict → G2P → LLM.
    All results are cached. Tier 2/3 results are logged for review.
    
    Parameters
    ----------
    medicine_name : str
        English medicine name (case-insensitive)
    
    Returns
    -------
    str
        Urdu script pronunciation
    
    Raises
    ------
    PronunciationError
        If all three tiers fail to produce valid Urdu
    """
    if not medicine_name or not medicine_name.strip():
        raise PronunciationError("Empty medicine name")
    
    medicine_name = medicine_name.strip()
    
    # Check cache first (using FULL name as key)
    cached = _get_cached_pronunciation(medicine_name)
    if cached:
        return cached
    
    # Normalize name for pronunciation (strip route/form words)
    normalized_name = _normalize_for_pronunciation(medicine_name)
    
    # Tier 1: Manual dictionary (check both full and normalized names)
    manual_result = _lookup_manual_dict(normalized_name)
    if manual_result:
        _cache_pronunciation(medicine_name, manual_result, "manual_dict")
        return manual_result
    
    # Tier 2: G2P + ARPAbet mapping (use normalized name)
    g2p_result, arpabet = _g2p_to_urdu(normalized_name)
    if g2p_result:
        _log_for_review(medicine_name, tier=2, urdu=g2p_result, details=f"Normalized: {normalized_name} | ARPAbet: {arpabet}")
        _cache_pronunciation(medicine_name, g2p_result, "g2p", arpabet=arpabet)
        return g2p_result
    
    # Tier 3: LLM fallback (use normalized name, only if G2P failed sanity check)
    llm_result = _llm_transliterate(normalized_name)
    if llm_result:
        _log_for_review(medicine_name, tier=3, urdu=llm_result, details=f"Normalized: {normalized_name} | LLM fallback")
        _cache_pronunciation(medicine_name, llm_result, "llm")
        return llm_result
    
    # All tiers failed
    raise PronunciationError(
        f"Could not resolve pronunciation for '{medicine_name}' (normalized: '{normalized_name}') "
        f"using any tier (manual dict, G2P, LLM all failed)"
    )


def get_pronunciation_stats() -> Dict:
    """
    Get statistics about cached pronunciations by source.
    
    Returns
    -------
    dict
        Stats dict with counts per source: manual_dict, g2p, llm
    """
    cache = _load_cache()
    stats = {"manual_dict": 0, "g2p": 0, "llm": 0, "total": 0}
    
    for entry in cache["pronunciations"].values():
        source = entry.get("source", "unknown")
        if source in stats:
            stats[source] += 1
        stats["total"] += 1
    
    return stats
