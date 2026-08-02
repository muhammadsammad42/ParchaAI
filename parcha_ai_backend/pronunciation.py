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


ARPABET_TO_URDU: Dict[str, str] = {
    "AA": "ا",      
    "AE": "اَ",      
    "AH": "اَ",      
    "AO": "او",     
    "AW": "او",     
    "AY": "ائ",     
    "EH": "ے",      
    "ER": "اَر",     
    "EY": "ای",     
    "IH": "اِ",      
    "IY": "ی",      
    "OW": "و",      
    "OY": "وئ",     
    "UH": "اُ",      
    "UW": "و",      

    "B": "ب",
    "CH": "چ",
    "D": "ڈ",      
    "DH": "دھ",      
    "F": "ف",
    "G": "گ",
    "HH": "ہ",
    "JH": "ج",
    "K": "ک",
    "L": "ل",
    "M": "م",
    "N": "ن",
    "NG": "نگ",     
    "P": "پ",
    "R": "ر",
    "S": "س",
    "SH": "ش",
    "T": "ٹ",       
    "TH": "تھ",      
    "V": "و",
    "W": "و",
    "Y": "ی",
    "Z": "ز",
    "ZH": "ژ",      
    
    "0": "",        
    "1": "",        
    "2": "",        
}


_cache: Optional[Dict] = None  
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

DOSAGE_FORM_PATTERNS = [
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
    "powder",
    "lotion",
    "cream",
    "ointment",
    "gel",
    "solution",
    "spray",
    "inhaler",
    "patch",
    "tab.",
    "tab",
    "cap.",
    "cap",
    "inj.",
    "inj",
    "syr.",
    "syr",
    "susp.",
    "susp",
]


def _normalize_for_pronunciation(medicine_name: str) -> str:

    normalized = medicine_name.strip()
    original_normalized = normalized  # Keep for logging
    
    for separator in ['/', '+', '&', ',']:
        if separator in normalized:
            segments = normalized.split(separator)
            normalized = segments[0].strip()
            break 
    
    # Step 2: Strip LEADING dosage forms (longest first to avoid partial matches)
    for pattern in DOSAGE_FORM_PATTERNS:
        normalized_lower = normalized.lower()
        
        # Check if starts with pattern (case-insensitive)
        if normalized_lower.startswith(pattern):
            # Strip pattern and any following whitespace/punctuation
            core_name = normalized[len(pattern):].lstrip(" .-")
            
            # If result is non-empty, use it
            if core_name.strip():
                normalized = core_name.strip()
                break  # Only strip one leading pattern
    
    # Step 3: Strip TRAILING dosage forms (longest first to avoid partial matches)
    for pattern in DOSAGE_FORM_PATTERNS:
        normalized_lower = normalized.lower()
        
        # Check if ends with pattern (case-insensitive)
        if normalized_lower.endswith(pattern):
            # Strip pattern and any preceding whitespace/punctuation
            core_name = normalized[:-(len(pattern))].rstrip(" .-")
            
            # If result is non-empty, use it
            if core_name.strip():
                normalized = core_name.strip()
                break  # Only strip one trailing pattern
    
    # Step 4: Strip common generic descriptors (Fluid, Liquid, etc.) if they're leading
    # These are not dosage forms but generic product descriptors
    generic_descriptors = ['fluid', 'liquid', 'powder', 'solution']
    for descriptor in generic_descriptors:
        normalized_lower = normalized.lower()
        if normalized_lower.startswith(descriptor + ' '):
            # Only strip if there's more after it (don't leave empty)
            core_name = normalized[len(descriptor):].lstrip()
            if core_name.strip():
                normalized = core_name.strip()
                break  # Only strip one descriptor
    
    # Log only if normalization changed the name
    if normalized != original_normalized:
        logger.debug(f"Normalized for pronunciation: '{original_normalized}' → '{normalized}'")
    
    # If stripping resulted in empty string, return original
    return normalized if normalized.strip() else medicine_name.strip()


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



def _g2p_to_urdu(medicine_name: str) -> Tuple[Optional[str], Optional[str]]:

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



def _llm_transliterate(medicine_name: str) -> Optional[str]:

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


def resolve_pronunciation(medicine_name: str) -> str:

    if not medicine_name or not medicine_name.strip():
        raise PronunciationError("Empty medicine name")
    
    medicine_name = medicine_name.strip()
    
    # Check cache first (using FULL name as key)
    cached = _get_cached_pronunciation(medicine_name)
    if cached:
        return cached
    
    # Normalize name for pronunciation (strip route/form words, handle compounds)
    normalized_name = _normalize_for_pronunciation(medicine_name)
    
    # Tier 1: Manual dictionary (check both full and normalized names)
    manual_result = _lookup_manual_dict(normalized_name)
    if manual_result:
        _cache_pronunciation(medicine_name, manual_result, "manual_dict")
        return manual_result
    
    # Tier 2: LLM (use normalized name) - produces natural Urdu without diacritics
    llm_result = _llm_transliterate(normalized_name)
    if llm_result:
        _log_for_review(medicine_name, tier=2, urdu=llm_result, details=f"Normalized: {normalized_name} | LLM")
        _cache_pronunciation(medicine_name, llm_result, "llm")
        return llm_result
    
    # Tier 3: G2P + ARPAbet mapping (last resort, only if LLM fails)
    # Produces technical phonetic output with diacritics - use only on LLM API failure
    g2p_result, arpabet = _g2p_to_urdu(normalized_name)
    if g2p_result:
        _log_for_review(medicine_name, tier=3, urdu=g2p_result, details=f"Normalized: {normalized_name} | ARPAbet: {arpabet} | G2P last resort")
        _cache_pronunciation(medicine_name, g2p_result, "g2p", arpabet=arpabet)
        return g2p_result
    
    # All tiers failed
    raise PronunciationError(
        f"Could not resolve pronunciation for '{medicine_name}' (normalized: '{normalized_name}') "
        f"using any tier (manual dict, LLM, G2P all failed)"
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
