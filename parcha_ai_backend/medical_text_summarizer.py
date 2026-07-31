
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from groq import Groq

from .config import get_config

logger = logging.getLogger(__name__)


class MedicalSummarizerError(Exception):
    """Raised when summarization fails unrecoverably."""
    pass


# =============================================================================
# SUMMARIZATION PROMPT
# =============================================================================

# Field type labels for context injection
FIELD_LABELS = {
    "uses": "استعمالات",          
    "precautions": "احتیاطی تدابیر",  
    "side_effects": "ضمنی اثرات"     
}

MEDICAL_SUMMARY_PROMPT = """آپ کو ایک طبی متن کو سادہ اردو میں خلاصہ کرنا ہے۔

یہ متن دوا کے '{field_label}' کے بارے میں ہے۔

اصول:
- بالکل 2-3 مختصر جملے لکھیں، زیادہ نہیں۔
- صرف سادہ اردو استعمال کریں، طبی اصطلاحات نہیں۔
- کوئی مارک ڈاؤن، نمبرنگ، یا انگریزی استعمال نہ کریں۔
- صرف نیچے دیے گئے متن کو خلاصہ کریں — اپنی طرف سے کوئی معلومات شامل نہ کریں۔
- صرف خلاصہ لکھیں، کوئی تعارفی جملہ یا وضاحت شامل نہ کریں۔
- اگر متن میں کوئی معلومات نہیں ہیں تو کچھ نہ لکھیں۔

متن:
{text}
"""


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

_cache: Optional[Dict] = None
_cache_path = Path("cache/medical_summary_cache.json")

# Maximum source text length before truncation (to avoid wasting tokens)
MAX_SOURCE_TEXT_LENGTH = 1500


def _load_cache() -> Dict:
    """Load medical summary cache from disk, or initialize empty if missing."""
    global _cache
    
    if _cache is not None:
        return _cache
    
    if _cache_path.exists():
        try:
            with open(_cache_path, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info(f"Loaded medical summary cache: {len(_cache.get('summaries', {}))} entries")
        except Exception as e:
            logger.warning(f"Failed to load medical summary cache, initializing empty: {e}")
            _cache = _create_empty_cache()
    else:
        _cache = _create_empty_cache()
        logger.info("Medical summary cache initialized (empty)")
    
    return _cache


def _create_empty_cache() -> Dict:
    """Create empty cache structure."""
    return {
        "version": "1.0",
        "last_updated": datetime.now().isoformat(),
        "summaries": {}
    }


def _save_cache() -> None:
    """Save medical summary cache to disk."""
    global _cache
    
    if _cache is None:
        return
    
    _cache["last_updated"] = datetime.now().isoformat()
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(_cache_path, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved medical summary cache: {len(_cache['summaries'])} entries")
    except Exception as e:
        logger.error(f"Failed to save medical summary cache: {e}")


def _cache_key(medicine_name: str, field_type: str) -> str:
    """Generate cache key for (medicine_name, field_type) pair."""
    return f"{medicine_name}|{field_type}"


def _get_cached_summary(medicine_name: str, field_type: str) -> Optional[str]:
    """Retrieve summary from cache, or None if not found."""
    cache = _load_cache()
    key = _cache_key(medicine_name, field_type)
    entry = cache["summaries"].get(key)
    
    if entry:
        logger.debug(f"Cache hit: {medicine_name} / {field_type} → {entry['summary'][:50]}...")
        return entry["summary"]
    
    return None


def _cache_summary(medicine_name: str, field_type: str, summary: str, source_hash: str) -> None:
    """Add summary to cache."""
    cache = _load_cache()
    key = _cache_key(medicine_name, field_type)
    
    cache["summaries"][key] = {
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
        "source_hash": source_hash,
    }
    
    _save_cache()


# =============================================================================
# TEXT PREPROCESSING
# =============================================================================

def _should_summarize(text: str) -> bool:
    """
    Check if text should be summarized.
    
    Returns False if text is empty, "unread", or otherwise invalid.
    """
    if not text or not isinstance(text, str):
        return False
    
    text_clean = text.strip().lower()
    
    # Skip if "unread" or other null-like values
    null_like = {"unread", "null", "none", "nan", "n/a", "na", "", "unknown"}
    if text_clean in null_like:
        return False
    
    # Skip if too short (less than 10 characters is unlikely to be real medical text)
    if len(text_clean) < 10:
        return False
    
    return True


def _truncate_text(text: str, max_length: int = MAX_SOURCE_TEXT_LENGTH) -> str:
    """
    Truncate long source text to avoid wasting tokens.
    
    Keeps first `max_length` characters. Tries to break at sentence boundaries
    when possible.
    """
    if len(text) <= max_length:
        return text
    
    # Truncate
    truncated = text[:max_length]
    
    # Try to break at last sentence ending (., !, ?)
    last_sentence = max(
        truncated.rfind('.'),
        truncated.rfind('!'),
        truncated.rfind('?')
    )
    
    if last_sentence > max_length * 0.7:  # If sentence break is reasonably close to end
        truncated = truncated[:last_sentence + 1]
    
    logger.debug(f"Truncated text from {len(text)} to {len(truncated)} chars")
    return truncated.strip()


def _hash_text(text: str) -> str:
    """Simple hash of source text for cache validation."""
    import hashlib
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]


# =============================================================================
# GROQ SUMMARIZATION
# =============================================================================

def _call_groq_summarize(text: str, field_type: str) -> str:

    config = get_config()
    
    if not config.groq_api_key:
        logger.warning("GROQ_API_KEY not configured, cannot summarize")
        return ""
    
    # Get field label for context
    field_label = FIELD_LABELS.get(field_type, field_type)
    
    # Truncate long text
    text_truncated = _truncate_text(text)
    
    # Build prompt
    prompt = MEDICAL_SUMMARY_PROMPT.format(
        field_label=field_label,
        text=text_truncated
    )
    
    try:
        client = Groq(api_key=config.groq_api_key)
        
        start = time.time()
        response = client.chat.completions.create(
            model=config.urdu_model,  # Reuse same model as Urdu explanation
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  # Low temperature for consistency
            max_tokens=200,   # 2-3 sentences shouldn't need more
        )
        
        content = response.choices[0].message.content if response.choices else None
        elapsed = time.time() - start
        
        if not content:
            logger.warning(f"Groq returned empty for {field_type} summarization")
            return ""
        
        # Clean up response
        summary = content.strip()
        
        summary = re.sub(r'^(یہ\s+)?خلاصہ\s*[:\-]?\s*', '', summary, flags=re.IGNORECASE)
        summary = re.sub(r'^(یہاں|نیچے)\s+(خلاصہ|معلومات)\s*[:\-]?\s*', '', summary, flags=re.IGNORECASE)
        
        # Verify it's Urdu script (at least 80% Urdu characters)
        urdu_chars = len(re.findall(r'[\u0600-\u06FF]', summary))
        total_chars = len(re.findall(r'[A-Za-z\u0600-\u06FF]', summary))
        
        if total_chars > 0 and urdu_chars / total_chars < 0.8:
            logger.warning(f"Summary not mostly Urdu script for {field_type}")
            return ""
        
        logger.info(f"Summarized {field_type} in {elapsed:.2f}s: {len(text)} chars → {len(summary)} chars")
        return summary
        
    except Exception as e:
        logger.error(f"Groq summarization failed for {field_type}: {e}")
        return ""


# =============================================================================
# PUBLIC API
# =============================================================================

def summarize_uses_precautions(
    medicine_name: str,
    text: str,
    field_type: str
) -> Optional[str]:

    # Validate field type
    if field_type not in FIELD_LABELS:
        logger.warning(f"Invalid field_type: {field_type}. Must be 'uses' or 'precautions'")
        return None
    
    # Check if text should be summarized
    if not _should_summarize(text):
        logger.debug(f"Skipping summarization for {medicine_name}/{field_type}: text is empty/unread")
        return None
    
    # Check cache first
    cached = _get_cached_summary(medicine_name, field_type)
    if cached is not None:
        return cached if cached else None  # Empty string in cache = failed summarization
    
    # Call Groq to summarize
    summary = _call_groq_summarize(text, field_type)
    
    # Cache result (even if empty, to avoid re-calling on next request)
    source_hash = _hash_text(text)
    _cache_summary(medicine_name, field_type, summary, source_hash)
    
    # Return None if summarization failed (empty string)
    return summary if summary else None


def get_summary_stats() -> Dict:

    cache = _load_cache()
    stats = {"uses": 0, "precautions": 0, "total": 0}
    
    for key in cache["summaries"].keys():
        _, field_type = key.split("|")
        if field_type in stats:
            stats[field_type] += 1
        stats["total"] += 1
    
    return stats
