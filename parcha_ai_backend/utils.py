
import re
from typing import Optional, Dict, Tuple


UNIT_ALIASES = {
    "milliliters": "ml",
    "milliliter": "ml",
    "millilitres": "ml",
    "millilitre": "ml",
    "mililiter": "ml",  
    "cc": "ml",  
    
    "milligrams": "mg",
    "milligram": "mg",
    "miligram": "mg",  
    "micrograms": "mcg",
    "microgram": "mcg",
    "grams": "g",
    "gram": "g",
    
    "tablets": "tab",
    "tablet": "tab",
    "capsules": "cap",
    "capsule": "cap",
    "drops": "drop",

    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",

    "international units": "iu",
    "international unit": "iu",
    "units": "unit",
}


NUMERIC_FREQUENCY_MAP = {
    # Twice daily patterns
    "1+0+1": "1-0-1",
    "1-0-1": "1-0-1",
    "0+1+1": "1-0-1",
    "0-1-1": "1-0-1",
    "1+1+0": "1-0-1",
    "1-1-0": "1-0-1",
    
    # Three times daily patterns
    "1+1+1": "1-1-1",
    "1-1-1": "1-1-1",
    
    # Once daily patterns
    "1+0+0": "1-0-0",
    "1-0-0": "1-0-0",
    "0+1+0": "1-0-0",
    "0-1-0": "1-0-0",
    "0+0+1": "1-0-0",
    "0-0-1": "1-0-0",
    
    # Four times daily patterns
    "1+1+1+1": "1-1-1-1",
    "1-1-1-1": "1-1-1-1",
}

FREQUENCY_PHRASE_MAP = [
    ("three times a day", "three times a day"),
    ("three times daily", "three times a day"),
    ("thrice a day", "three times a day"),
    ("thrice daily", "three times a day"),
    ("thrice", "three times a day"),  
    ("3 times a day", "three times a day"),
    ("3 times daily", "three times a day"),
    ("3x a day", "three times a day"),
    ("3x daily", "three times a day"),
    ("three times in a day", "three times a day"),
    ("three times per day", "three times a day"),

    ("twice a day", "twice a day"),
    ("twice daily", "twice a day"),
    ("two times a day", "twice a day"),
    ("two times daily", "twice a day"),
    ("2 times a day", "twice a day"),
    ("2 times daily", "twice a day"),
    ("2x a day", "twice a day"),
    ("2x daily", "twice a day"),
    ("morning and night", "twice a day"),
    ("morning and evening", "twice a day"),
    ("every 12 hours", "twice a day"),
    ("every 12 hrs", "twice a day"),

    ("once a day", "once a day"),
    ("once daily", "once a day"),
    ("one time a day", "once a day"),
    ("one time daily", "once a day"),
    ("1 time a day", "once a day"),
    ("1 time daily", "once a day"),
    ("every morning", "once a day"),
    ("every evening", "once a day"),
    ("every night", "once a day"),
    ("at night", "once a day"),
    ("at bedtime", "at bedtime"),
    ("every 24 hours", "once a day"),
    ("every 24 hrs", "once a day"),

    ("four times a day", "four times a day"),
    ("four times daily", "four times a day"),
    ("4 times a day", "four times a day"),
    ("4 times daily", "four times a day"),
    ("4x a day", "four times a day"),
    ("4x daily", "four times a day"),
    ("every 4 hours", "six times a day"),
    ("every 4 hrs", "six times a day"),
    ("every 6 hours", "four times a day"),
    ("every 6 hrs", "four times a day"),
    ("every 8 hours", "three times a day"),
    ("every 8 hrs", "three times a day"),
    ("as needed", "as needed"),
    ("when required", "as needed"),
    ("if needed", "as needed"),
    ("as necessary", "as needed"),
    ("1-0-1", "twice a day"),
    ("1+0+1", "twice a day"),
    ("0-1-1", "twice a day"),
    ("1-1-0", "twice a day"),
    ("1-1-1", "three times a day"),
    ("1+1+1", "three times a day"),
    ("1-0-0", "once a day"),
    ("1+0+0", "once a day"),
    ("0-1-0", "once a day"),
    ("0-0-1", "once a day"),
    ("1-1-1-1", "four times a day"),
    ("1+1+1+1", "four times a day"),
]


# Frequency abbreviation mapping for robust lookup
FREQUENCY_ABBREVIATION_MAP = {
    "od": "once a day",
    "o.d.": "once a day",
    "o.d": "once a day",
    "qd": "once a day",
    "q.d.": "once a day",
    
    "bd": "twice a day",
    "b.d.": "twice a day",
    "b.d": "twice a day",
    "bid": "twice a day",
    "b.i.d.": "twice a day",
    "b.i.d": "twice a day",
    
    "tid": "three times a day",
    "t.i.d.": "three times a day",
    "t.i.d": "three times a day",
    "tds": "three times a day",
    "t.d.s.": "three times a day",
    "t.d.s": "three times a day",
    
    "qid": "four times a day",
    "q.i.d.": "four times a day",
    "q.i.d": "four times a day",
    "qds": "four times a day",
    "q.d.s.": "four times a day",
    "q.d.s": "four times a day",
    
    "prn": "as needed",
    "p.r.n.": "as needed",
    "p.r.n": "as needed",
    "sos": "as needed",
    "s.o.s.": "as needed",
    
    # Time-based
    "hs": "at bedtime",
    "h.s.": "at bedtime",
    "stat": "immediately",
    "nocte": "at bedtime",
    "mane": "once a day",
    "q4h": "six times a day",
    "q6h": "four times a day",
    "q8h": "three times a day",
    "q12h": "twice a day",
    "q24h": "once a day",

    # STAT (single immediate dose) -- common in hospital prescriptions
    "stat": "immediately",
    "ad": "once a day",
    "a.d.": "once a day",
    "a.d": "once a day",
}


WORD_NUMBER_MAP = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30",
}

DURATION_ALIASES = {
    "day": "days",
    "days": "days",
    "week": "weeks",
    "weeks": "weeks",
    "wk": "weeks",
    "wks": "weeks",
    "month": "months",
    "months": "months",
    "mo": "months",
    "mos": "months",
    "year": "years",
    "years": "years",
    "yr": "years",
    "yrs": "years",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
}


def normalize_whitespace(text: str) -> str:
    """Remove excessive whitespace and normalize to single spaces.
    
    Parameters
    ----------
    text : str
        Input text with potentially irregular whitespace
    
    Returns
    -------
    str
        Text with normalized whitespace
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Replace all whitespace sequences (spaces, tabs, newlines) with single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def round_numbers(text: str) -> str:
    """Normalize numeric representations by removing trailing zeros and unnecessary decimals.
    
    Parameters
    ----------
    text : str
        Text containing numbers
    
    Returns
    -------
    str
        Text with normalized numbers
    
    """
    def fix_number(match):
        num_str = match.group(0)
        
        # Handle decimal numbers
        if '.' in num_str:
            # Remove trailing zeros after decimal point
            num_str = num_str.rstrip('0').rstrip('.')
        else:
            # Remove leading zeros (but keep single 0)
            try:
                num_str = str(int(num_str))
            except ValueError:
                pass
        
        return num_str
    
    # Match integers and decimals
    return re.sub(r'\d+\.?\d*', fix_number, text)


def normalize_dosage(dosage: str) -> str:

    if not dosage or not isinstance(dosage, str):
        return "unread"
    
    text = dosage.lower().strip()
    
    # Check for null-like values
    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"
    
    # Remove dots that aren't decimal points
    text = re.sub(r'(?<!\d)\.(?!\d)', '', text)
    
    # Remove commas, semicolons, colons, parentheses, brackets
    text = re.sub(r'[,;:()\[\]]', '', text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)
    
    # Replace unit aliases with standard abbreviations
    for long_form, short_form in UNIT_ALIASES.items():
        text = re.sub(rf'\b{long_form}\b', short_form, text)
    
    text = re.sub(r'(\d)([a-z]+)\b', r'\1 \2', text)
    
    # Ensure single space (defensive cleanup)
    text = re.sub(r'(\d)\s+(ml|mg|mcg|g|tab|cap|drop|iu|unit)\b', r'\1 \2', text)
    
    # Round numbers
    text = round_numbers(text)
    
    return text.strip()


def extract_dosage_core(dosage: str) -> str:

    if not dosage or not isinstance(dosage, str):
        return "unread"

    text = dosage.lower().strip()

    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"

    text = re.sub(r'\([^)]*\)', ' ', text)
    text = normalize_whitespace(text)

    match = re.search(
        r'(\d+(?:\.\d+)?)\s*(mg|ml|mcg|g|iu|units?|tabs?|caps?|drops?|tsp|tbsp|teaspoons?|tablespoons?)\b',
        text
    )
    if not match:
        return "unread"

    num = round_numbers(match.group(1))
    unit = match.group(2).rstrip('s')  

    if unit in ('teaspoon', 'tsp'):
        unit = 'tsp'
    elif unit in ('tablespoon', 'tbsp'):
        unit = 'tbsp'
    return f"{num} {unit}"


def dosages_match(pred_dosage: str, truth_dosage: str, fuzzy_threshold: int = 85) -> bool:

    pred_norm = normalize_dosage(pred_dosage)
    truth_norm = normalize_dosage(truth_dosage)

    if pred_norm == truth_norm:
        return True
    if pred_norm == "unread" or truth_norm == "unread":
        return False

    pred_core = extract_dosage_core(pred_dosage)
    truth_core = extract_dosage_core(truth_dosage)

    if pred_core != "unread" and pred_core == truth_core:
        return True

    if pred_core != "unread" and pred_core.replace(' ', '') in truth_norm.replace(' ', ''):
        return True
    if truth_core != "unread" and truth_core.replace(' ', '') in pred_norm.replace(' ', ''):
        return True

    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(pred_norm, truth_norm) >= fuzzy_threshold
    except ImportError:
        return False

MEDICINE_FORM_WORDS = {
    'syr', 'syp', 'syrup', 'tab', 'tabs', 'tablet', 'tablets', 'cap', 'caps',
    'capsule', 'capsules', 'drop', 'drops', 'susp', 'suspension', 'inj',
    'injection', 'oint', 'ointment', 'supp', 'suppository', 'sol', 'solution',
    'lotion', 'cream', 'gel', 'spray', 'sachet', 'sachets', 'ear', 'eye',
    'nasal', 'rectal', 'oral', 'forte',
}


def strip_form_words(name: str) -> str:

    if not name or not isinstance(name, str):
        return ""

    cleaned = re.sub(r'[^\w\s]', ' ', name.lower())
    tokens = [t for t in cleaned.split() if t not in MEDICINE_FORM_WORDS]

    result = ' '.join(tokens).strip()
    return result if result else name.lower().strip()


def medicine_names_match(pred_name: str, truth_name: str, fuzzy_threshold: int = 80) -> bool:

    pred_clean = strip_form_words(normalize_text_field(pred_name))
    truth_clean = strip_form_words(normalize_text_field(truth_name))

    if pred_clean in {"unread", ""} or truth_clean in {"unread", ""}:
        return pred_clean == truth_clean

    if pred_clean == truth_clean:
        return True

    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(pred_clean, truth_clean) >= fuzzy_threshold
    except ImportError:
        return False


def normalize_frequency(frequency: str) -> str:
    """Normalize frequency descriptions to standard English phrases.
    
    This function handles:
    1. Medical abbreviations (OD, BD, TID, etc.) with robust case-insensitive matching
    2. Natural language phrases mapped to standard format
    3. Numeric matrix notation (1-0-1, 1+0+1, etc.)
    4. Proper spacing for units
    
    Parameters
    ----------
    frequency : str
        Raw frequency string
    
    Returns
    -------
    str
        Normalized frequency string in standard English
    """
    if not frequency or not isinstance(frequency, str):
        return "unread"
    
    text = frequency.lower().strip()
    
    # Check for null-like values
    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"
    
    stat_then_daily = re.search(
        r'\bstat\b.*\b(?:od|once(?:\s+a)?\s+day|once\s+daily)\b', text
    )
    if stat_then_daily:
        return "stat once then once a day"

    text = re.sub(r'\s*\([^)]*\)', '', text).strip()
    
    # Remove dots and extra punctuation (but preserve hyphens in patterns like 1-0-1)
    text = re.sub(r'(?<!\d)\.(?!\d)', '', text)
    text = re.sub(r'[,;:\[\]]', '', text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)
    text = re.sub(r'(?<=\d)\s*[-+]\s*(?=\d)', '-', text)

    if re.fullmatch(r'\d(\s+\d){1,3}', text):
        text = re.sub(r'\s+', '-', text)

    text_clean = text.replace(" ", "").replace(".", "").lower()
    if text_clean in FREQUENCY_ABBREVIATION_MAP:
        return FREQUENCY_ABBREVIATION_MAP[text_clean]
    
    # STEP 2: Check phrase mappings (longest first to avoid partial matches)
    for phrase, standardized in FREQUENCY_PHRASE_MAP:
        if phrase in text:
            return standardized

    for word in text.split():
        word_clean = word.strip(".")
        if word_clean in FREQUENCY_ABBREVIATION_MAP:
            return FREQUENCY_ABBREVIATION_MAP[word_clean]

    text = re.sub(r'(\d)(tab|cap)\b', r'\1 \2', text)
    
    return text.strip()


def normalize_duration(duration: str) -> str:
    """Normalize duration format with proper spacing.
    
    Parameters
    ----------
    duration : str
        Raw duration string
    
    Returns
    -------
    str
        Normalized duration string with space between number and unit
    """
    if not duration or not isinstance(duration, str):
        return "unread"
    
    text = duration.lower().strip()
    
    # Check for null-like values
    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"

    dose_count = re.fullmatch(r'\s*(\d+)\s+doses?\s+(?:total|only)\s*', text)
    if dose_count:
        count = dose_count.group(1)
        return f"{count} dose" if count == "1" else f"{count} doses total"

    special_durations = {
        "finish course": "finish course",
        "finish the course": "finish course",
        "complete course": "finish course",
        "as directed": "as directed",
        "until finished": "finish course",
        "ongoing": "ongoing",
        "continuous": "ongoing",
        "indefinite": "ongoing",
        "long term": "ongoing",
    }
    text_lower_clean = re.sub(r'\s+', ' ', text.strip())
    if text_lower_clean in special_durations:
        return special_durations[text_lower_clean]

    text = re.sub(r'\s*\([^)]*\)', '', text).strip()
    
    # Remove extra punctuation
    text = re.sub(r'[,;:\[\]]', '', text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)

    words = text.split()
    words = [WORD_NUMBER_MAP.get(w, w) for w in words]
    text = " ".join(words)

    text = re.sub(r'(\d)([a-z]+)\b', r'\1 \2', text)

    for singular, plural in DURATION_ALIASES.items():
        text = re.sub(rf'\b{singular}\b', plural, text)
    
    text = re.sub(r'(\d)(days|weeks|months|years)\b', r'\1 \2', text)
    
    # Ensure single space (defensive cleanup)
    text = re.sub(r'(\d)\s+(days|weeks|months|years)\b', r'\1 \2', text)
    
    # Round numbers
    text = round_numbers(text)
    
    return text.strip()


def normalize_text_field(value: str) -> str:
    """General text field normalization for any string field.
    
    This is used for fields like medicine name, purpose, composition, etc.
    It performs basic cleaning without aggressive transformations.
    
    Parameters
    ----------
    value : str
        Raw text value
    
    Returns
    -------
    str
        Cleaned text value
    """
    if not value or not isinstance(value, str):
        return "unread"
    
    text = value.strip()
    
    # Check for null-like values
    if text.lower() in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"
    
    # Basic whitespace normalization
    text = normalize_whitespace(text)
    
    return text


# =============================================================================
# HIGH-LEVEL NORMALIZATION FUNCTION
# =============================================================================

def normalize_field(field_name: str, field_value: str) -> str:
    """Intelligently normalize a field based on its name.
    
    This is the main entry point for field normalization. It applies
    field-specific rules based on the field name.
    
    Parameters
    ----------
    field_name : str
        Name of the field (e.g., "dosage", "frequency", "duration")
    field_value : str
        Raw field value
    
    Returns
    -------
    str
        Normalized field value
    """
    field_name = field_name.lower().strip()
    
    if field_name in {"dosage", "dose"}:
        return normalize_dosage(field_value)
    elif field_name in {"frequency", "freq"}:
        return normalize_frequency(field_value)
    elif field_name in {"duration"}:
        return normalize_duration(field_value)
    else:
        return normalize_text_field(field_value)


def normalize_medicine_dict(medicine: Dict[str, any]) -> Dict[str, any]:
    """Normalize all fields in a medicine dictionary.
    
    Parameters
    ----------
    medicine : dict
        Dictionary containing medicine fields
    
    Returns
    -------
    dict
        Dictionary with normalized fields
    """
    normalized = {}
    
    for key, value in medicine.items():
        if isinstance(value, str):
            normalized[key] = normalize_field(key, value)
        else:
            normalized[key] = value
    
    return normalized


# =============================================================================
# COMPARISON UTILITIES
# =============================================================================

def fields_match(field_name: str, value1: str, value2: str, fuzzy_threshold: int = 85) -> bool:
    """Check if two field values match after normalization.
    
    This is used for evaluation to compare extracted values with ground truth.
    It normalizes both values and checks for exact match or high fuzzy similarity.
    
    Parameters
    ----------
    field_name : str
        Name of the field being compared
    value1 : str
        First value
    value2 : str
        Second value
    fuzzy_threshold : int, optional
        RapidFuzz similarity threshold (0-100), by default 85
    
    Returns
    -------
    bool
        True if values match after normalization
    """
    # Normalize both values
    norm1 = normalize_field(field_name, value1)
    norm2 = normalize_field(field_name, value2)
    
    # Check for exact match
    if norm1 == norm2:
        return True
    
    # If either is "unread", they don't match
    if norm1 == "unread" or norm2 == "unread":
        return False
    try:
        from rapidfuzz import fuzz
        similarity = fuzz.token_set_ratio(norm1, norm2)
        return similarity >= fuzzy_threshold
    except ImportError:
        # If rapidfuzz not available, only exact matches count
        return False


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def is_null_or_unread(value: str) -> bool:
    """Check if a value should be considered null/unread.
    
    Parameters
    ----------
    value : str
        Value to check
    
    Returns
    -------
    bool
        True if value is null-like or "unread"
    """
    if not value or not isinstance(value, str):
        return True
    
    normalized = value.lower().strip()
    return normalized in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}


def normalize_text(text: str) -> str:
    """
    Convenience alias for normalize_text_field.
    
    Normalizes general text by cleaning whitespace and checking for null values.
    
    Parameters
    ----------
    text : str
        Text to normalize
    
    Returns
    -------
    str
        Normalized text
    """
    return normalize_text_field(text)
