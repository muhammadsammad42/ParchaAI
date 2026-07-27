"""
Text normalization utilities for ParchaAI prescription extraction pipeline.

This module provides comprehensive text cleaning and standardization functions
to improve matching accuracy by eliminating format variations in dosage,
frequency, duration, and other prescription fields.

The normalization rules are designed to handle common variations in:
- Dosage formats (spaces, units, decimal numbers)
- Frequency descriptions (medical abbreviations, natural language)
- Duration formats (days, weeks, months)
- General text cleaning (whitespace, punctuation, case)
"""

import re
from typing import Optional, Dict, Tuple


# =============================================================================
# UNIT NORMALIZATION MAPPINGS
# =============================================================================

# Map various unit spellings to standard abbreviations
UNIT_ALIASES = {
    # Volume units
    "milliliters": "ml",
    "milliliter": "ml",
    "millilitres": "ml",
    "millilitre": "ml",
    "mililiter": "ml",  # Common misspelling
    "cc": "ml",  # Cubic centimeters = milliliters
    
    # Weight units
    "milligrams": "mg",
    "milligram": "mg",
    "miligram": "mg",  # Common misspelling
    "micrograms": "mcg",
    "microgram": "mcg",
    "grams": "g",
    "gram": "g",
    
    # Other units
    "tablets": "tab",
    "tablet": "tab",
    "capsules": "cap",
    "capsule": "cap",
    "drops": "drop",

    # Teaspoon / tablespoon -- extremely common in South Asian
    # prescriptions (syrups). The model may output either form;
    # ground truth uses the other. Normalizing both to the same
    # short form eliminates the mismatch.
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",

    # International units (previously only handled in extract_dosage_core,
    # not here -- meant "5000 IU" vs "5000IU" never matched via
    # normalize_dosage even though the equivalent mg/ml case did)
    "international units": "iu",
    "international unit": "iu",
    "units": "unit",
}


# =============================================================================
# FREQUENCY NORMALIZATION MAPPINGS
# =============================================================================

# Numeric matrix notation (e.g., morning-afternoon-evening)
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


# Natural language frequency phrases (ordered longest-first for greedy matching)
# Target format: standardized English phrases for better evaluation matching
FREQUENCY_PHRASE_MAP = [
    # Multi-word phrases (must come first)
    ("three times a day", "three times a day"),
    ("three times daily", "three times a day"),
    ("thrice a day", "three times a day"),
    ("thrice daily", "three times a day"),
    ("thrice", "three times a day"),  # bare "thrice" without qualifier
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

    # NEW: "every N hours" phrasing for the remaining common intervals.
    # "every 12/24 hours" were already covered above, but "every 4/6/8
    # hours" (very common on real prescriptions, e.g. antibiotics dosed
    # Q6H/Q8H) had no phrase-level entry at all -- they only matched via
    # the exact-string abbreviation map, which fails the moment any extra
    # word ("every 6 hours after meals") is present. Listed here so the
    # substring scan in STEP 2 of normalize_frequency() catches them too.
    ("every 4 hours", "six times a day"),
    ("every 4 hrs", "six times a day"),
    ("every 6 hours", "four times a day"),
    ("every 6 hrs", "four times a day"),
    ("every 8 hours", "three times a day"),
    ("every 8 hrs", "three times a day"),

    # Medical abbreviations (must be exact for safety)
    ("as needed", "as needed"),
    ("when required", "as needed"),
    ("if needed", "as needed"),
    ("as necessary", "as needed"),

    # Dashboard notation (keep as-is for backward compatibility)
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
    # Latin abbreviations (case-insensitive)
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

    # Interval-based (q_h family) -- previously unmapped entirely, so
    # e.g. predicted "q8h" vs ground truth "three times a day" always
    # scored as a mismatch even though they mean the same thing.
    "q4h": "six times a day",
    "q6h": "four times a day",
    "q8h": "three times a day",
    "q12h": "twice a day",
    "q24h": "once a day",

    # STAT (single immediate dose) -- common in hospital prescriptions
    "stat": "immediately",

    # A.D. (abbreviation sometimes found in handwritten prescriptions,
    # exact meaning varies -- treat as once a day since that's the most
    # common interpretation in South Asian clinical practice)
    "ad": "once a day",
    "a.d.": "once a day",
    "a.d": "once a day",
}


# =============================================================================
# DURATION NORMALIZATION
# =============================================================================

# Spelled-out counts occasionally show up in ground truth/predictions
# ("Seven days" instead of "7 days"). Converting these to digits before
# comparison avoids an otherwise-guaranteed mismatch between two strings
# that mean exactly the same duration.
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


# =============================================================================
# CORE NORMALIZATION FUNCTIONS
# =============================================================================

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
    
    Examples
    --------
    >>> normalize_whitespace("hello    world\\n\\ntest")
    'hello world test'
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
    
    Examples
    --------
    >>> round_numbers("0.50 mg")
    '0.5 mg'
    >>> round_numbers("05 tablets")
    '5 tablets'
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
    """Normalize dosage format by standardizing units and adding proper spacing.
    
    This function:
    1. Adds space between numbers and units (e.g., "500mg" -> "500 mg")
    2. Standardizes unit names (e.g., "milliliters" -> "ml")
    3. Rounds numbers (e.g., "0.50" -> "0.5")
    4. Removes unnecessary punctuation
    
    Parameters
    ----------
    dosage : str
        Raw dosage string
    
    Returns
    -------
    str
        Normalized dosage string with proper spacing
    
    Examples
    --------
    >>> normalize_dosage("500mg")
    '500 mg'
    >>> normalize_dosage("1tab")
    '1 tab'
    >>> normalize_dosage("4.00 milliliters")
    '4 ml'
    """
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
    
    # CRITICAL: Add space between numbers and units if missing
    # This ensures "500mg" becomes "500 mg" for better evaluation matching
    text = re.sub(r'(\d)([a-z]+)\b', r'\1 \2', text)
    
    # Ensure single space (defensive cleanup)
    text = re.sub(r'(\d)\s+(ml|mg|mcg|g|tab|cap|drop|iu|unit)\b', r'\1 \2', text)
    
    # Round numbers
    text = round_numbers(text)
    
    return text.strip()


def extract_dosage_core(dosage: str) -> str:
    """Extract the core number+unit strength from a dosage string.

    Ground-truth dosage values are often verbose, e.g. "50 mg tab (take 1 tab)"
    or "200 mg/5mL - Day 1: 15 mL, Day 2: 7.5 mL", while the model is
    deliberately instructed to output just the clean strength (e.g. "50 mg").
    This function strips administration notes in parentheses and pulls out
    the first "<number> <unit>" token so the two representations can be
    compared on equal footing.

    Parameters
    ----------
    dosage : str
        Raw dosage string (from either prediction or ground truth)

    Returns
    -------
    str
        Normalized "<number> <unit>" core, or "unread" if nothing usable
        could be found

    Examples
    --------
    >>> extract_dosage_core("50 mg tab (take 1 tab)")
    '50 mg'
    >>> extract_dosage_core("625mg")
    '625 mg'
    """
    if not dosage or not isinstance(dosage, str):
        return "unread"

    text = dosage.lower().strip()

    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"

    # Drop parenthetical administration notes entirely -- these describe
    # HOW to take the dose, not the strength itself, and are not something
    # the extraction prompt asks the model to reproduce.
    text = re.sub(r'\([^)]*\)', ' ', text)
    text = normalize_whitespace(text)

    match = re.search(
        r'(\d+(?:\.\d+)?)\s*(mg|ml|mcg|g|iu|units?|tabs?|caps?|drops?|tsp|tbsp|teaspoons?|tablespoons?)\b',
        text
    )
    if not match:
        return "unread"

    num = round_numbers(match.group(1))
    unit = match.group(2).rstrip('s')  # "tabs" -> "tab", "units" -> "unit"
    # Normalize teaspoon/tablespoon variants
    if unit in ('teaspoon', 'tsp'):
        unit = 'tsp'
    elif unit in ('tablespoon', 'tbsp'):
        unit = 'tbsp'
    return f"{num} {unit}"


def dosages_match(pred_dosage: str, truth_dosage: str, fuzzy_threshold: int = 85) -> bool:
    """Check whether two dosage strings refer to the same underlying dose.

    Two dosages are treated as equal if:
    1. They are identical after standard normalization (spacing/units), OR
    2. Their core "<number> <unit>" strength matches, even if one side has
       extra administration notes the other doesn't, OR
    3. They are highly similar by fuzzy token-set matching (handles minor
       wording/order differences).

    This intentionally does NOT require a 100% literal string match --
    values with the same meaning (just different spacing, units written
    out longhand, or extra notes) are treated as equal.

    Parameters
    ----------
    pred_dosage : str
        Predicted dosage value
    truth_dosage : str
        Ground truth dosage value
    fuzzy_threshold : int, optional
        RapidFuzz similarity threshold for the final fallback, by default 85

    Returns
    -------
    bool
        True if the two dosages should be considered a match
    """
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

    # Containment check: the predicted core strength literally appears
    # somewhere in the (messier) ground truth string, e.g. pred "50 mg"
    # inside truth "50 mg tab take 1 tab".
    if pred_core != "unread" and pred_core.replace(' ', '') in truth_norm.replace(' ', ''):
        return True
    if truth_core != "unread" and truth_core.replace(' ', '') in pred_norm.replace(' ', ''):
        return True

    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(pred_norm, truth_norm) >= fuzzy_threshold
    except ImportError:
        return False


# Words describing dosage FORM (not the medicine identity itself) that
# commonly appear in raw ground-truth transcriptions but are deliberately
# excluded from the model's "medicine_name" output by the extraction prompt.
MEDICINE_FORM_WORDS = {
    'syr', 'syp', 'syrup', 'tab', 'tabs', 'tablet', 'tablets', 'cap', 'caps',
    'capsule', 'capsules', 'drop', 'drops', 'susp', 'suspension', 'inj',
    'injection', 'oint', 'ointment', 'supp', 'suppository', 'sol', 'solution',
    'lotion', 'cream', 'gel', 'spray', 'sachet', 'sachets', 'ear', 'eye',
    'nasal', 'rectal', 'oral', 'forte',
}


def strip_form_words(name: str) -> str:
    """Strip dosage-form / administration-route words from a medicine name.

    Ground truth often records the full clinical description (e.g.
    "Candibiotic Ear Drops", "Anmol Rectal Suppository") while the model is
    instructed to extract only the brand/generic name (e.g. "Candibiotic").
    Stripping these descriptor words lets the two be compared fairly.

    Parameters
    ----------
    name : str
        Raw medicine name

    Returns
    -------
    str
        Name with form/route words removed, lowercased

    Examples
    --------
    >>> strip_form_words("Candibiotic Ear Drops")
    'candibiotic'
    >>> strip_form_words("Syr Megacv Forte")
    'megacv'
    """
    if not name or not isinstance(name, str):
        return ""

    cleaned = re.sub(r'[^\w\s]', ' ', name.lower())
    tokens = [t for t in cleaned.split() if t not in MEDICINE_FORM_WORDS]

    result = ' '.join(tokens).strip()
    return result if result else name.lower().strip()


def medicine_names_match(pred_name: str, truth_name: str, fuzzy_threshold: int = 80) -> bool:
    """Check whether two medicine names refer to the same medicine.

    Compares names after stripping dosage-form/route words and whitespace
    differences, falling back to fuzzy token-set similarity so that names
    with the same meaning (but different formatting, word order, or extra
    descriptive words on one side) are treated as equal rather than
    penalized for not being a 100% literal match.

    Parameters
    ----------
    pred_name : str
        Predicted medicine name
    truth_name : str
        Ground truth medicine name
    fuzzy_threshold : int, optional
        RapidFuzz token-set similarity threshold, by default 88

    Returns
    -------
    bool
        True if the two names should be considered the same medicine
    """
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
    
    Examples
    --------
    >>> normalize_frequency("BD")
    'twice a day'
    >>> normalize_frequency("tid")
    'three times a day'
    >>> normalize_frequency("1-0-1")
    'twice a day'
    >>> normalize_frequency("morning and night")
    'twice a day'
    """
    if not frequency or not isinstance(frequency, str):
        return "unread"
    
    text = frequency.lower().strip()
    
    # Check for null-like values
    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"

    # Preserve the clinically meaningful loading-dose form used in IV
    # prescriptions.  Returning a canonical string here means variants such
    # as "STAT then OD" and "stat once then once daily" compare correctly
    # without pretending that a one-time loading dose is an ordinary daily
    # frequency.
    stat_then_daily = re.search(
        r'\bstat\b.*\b(?:od|once(?:\s+a)?\s+day|once\s+daily)\b', text
    )
    if stat_then_daily:
        return "stat once then once a day"

    # CRITICAL: strip parenthetical qualifiers FIRST, before any other
    # normalization. Ground truth frequently has patterns like
    # "Once daily (morning)", "PRN (if fever > 102F)", "Twice daily
    # (after food)", "SOS (for fever/pain)". The parenthetical is a
    # clinical qualifier, not the base frequency -- stripping it lets
    # the core frequency match on equal footing.
    text = re.sub(r'\s*\([^)]*\)', '', text).strip()
    
    # Remove dots and extra punctuation (but preserve hyphens in patterns like 1-0-1)
    text = re.sub(r'(?<!\d)\.(?!\d)', '', text)
    text = re.sub(r'[,;:\[\]]', '', text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)

    # CRITICAL: collapse spaced-out dash/plus matrix notation to the
    # canonical no-space form BEFORE lookup. Ground truth and predictions
    # frequently write "1 - 0 - 1" or "1 + 0 + 1" (with spaces) while
    # FREQUENCY_PHRASE_MAP only has the tight "1-0-1" / "1+0+1" keys, so
    # these previously fell through unmatched and were compared as raw
    # strings -- a likely contributor to the low frequency_accuracy.
    # Only touches separators sandwiched between digits, so word-based
    # phrases like "as-needed" are untouched.
    text = re.sub(r'(?<=\d)\s*[-+]\s*(?=\d)', '-', text)

    # Also handle plain space-separated matrix notation with no dash at
    # all, e.g. "1 0 1" -> "1-0-1" (2-4 single digits only, to avoid
    # accidentally rewriting unrelated numeric text).
    if re.fullmatch(r'\d(\s+\d){1,3}', text):
        text = re.sub(r'\s+', '-', text)

    # STEP 1: Check abbreviation map first (most precise) -- fast path when
    # the WHOLE string is just the bare abbreviation, e.g. "BD" or "prn".
    text_clean = text.replace(" ", "").replace(".", "").lower()
    if text_clean in FREQUENCY_ABBREVIATION_MAP:
        return FREQUENCY_ABBREVIATION_MAP[text_clean]
    
    # STEP 2: Check phrase mappings (longest first to avoid partial matches)
    for phrase, standardized in FREQUENCY_PHRASE_MAP:
        if phrase in text:
            return standardized

    # STEP 3 (FIX): token-level abbreviation match.
    # Real prescriptions (and this project's own ground truth) frequently
    # write an abbreviation together with a trailing clinical condition or
    # dosing threshold, e.g. "PRN (if fever > 102F)", "SOS for pain",
    # "TDS after meals". STEP 1 only matches when the ENTIRE cleaned string
    # equals a bare abbreviation, so any of those trailing words made the
    # whole match silently fail -- the text was then compared essentially
    # raw, and a semantically-identical prediction like "as needed" (which
    # the model produces per its own prompt instructions) was scored as a
    # mismatch purely because of the un-normalized ground truth /
    # prediction string. This was a major contributor to low
    # frequency_accuracy and, downstream, to exact_match_accuracy.
    # Scanning word-by-word and returning on the first recognized
    # abbreviation mirrors the same "keep only the base frequency, drop the
    # qualifier" behavior STEP 2 already applies to full phrases.
    for word in text.split():
        word_clean = word.strip(".")
        if word_clean in FREQUENCY_ABBREVIATION_MAP:
            return FREQUENCY_ABBREVIATION_MAP[word_clean]

    # STEP 4: Add space between number and "tab" or "cap" if missing
    # "1tab" -> "1 tab", "2cap" -> "2 cap"
    text = re.sub(r'(\d)(tab|cap)\b', r'\1 \2', text)
    
    # STEP 5: If still no match, return as-is (may be a custom instruction)
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
    
    Examples
    --------
    >>> normalize_duration("5day")
    '5 days'
    >>> normalize_duration("2weeks")
    '2 weeks'
    >>> normalize_duration("1month")
    '1 month'
    """
    if not duration or not isinstance(duration, str):
        return "unread"
    
    text = duration.lower().strip()
    
    # Check for null-like values
    if text in {"null", "none", "nan", "n/a", "na", "", "unread", "unknown"}:
        return "unread"

    # Dose-count courses occur in infusion/biologic prescriptions.  They are
    # valid finite treatment durations and should not be discarded merely
    # because they are not expressed in days or weeks.
    dose_count = re.fullmatch(r'\s*(\d+)\s+doses?\s+(?:total|only)\s*', text)
    if dose_count:
        count = dose_count.group(1)
        return f"{count} dose" if count == "1" else f"{count} doses total"

    # Handle special textual durations that can't be expressed as
    # "<number> <unit>" -- normalize to canonical forms so both sides
    # compare identically.
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

    # Strip parenthetical qualifiers FIRST -- ground truth sometimes has
    # patterns like "4 days (after loading dose)" where the parenthetical
    # is a clinical note, not the duration itself.
    text = re.sub(r'\s*\([^)]*\)', '', text).strip()
    
    # Remove extra punctuation
    text = re.sub(r'[,;:\[\]]', '', text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)

    # Convert spelled-out numbers ("seven days" -> "7 days") before anything
    # else, so downstream regexes that expect a digit still fire correctly.
    words = text.split()
    words = [WORD_NUMBER_MAP.get(w, w) for w in words]
    text = " ".join(words)

    # CRITICAL: split number-glued unit letters BEFORE alias lookup.
    # \b (word boundary) does NOT exist between a digit and a letter --
    # both are \w characters -- so "2wks" never matched \bwks\b below and
    # abbreviated units glued to a number silently failed to normalize.
    text = re.sub(r'(\d)([a-z]+)\b', r'\1 \2', text)

    # Standardize duration units (singular to plural, and abbreviations
    # like wk/wks/mo/yr to their full form)
    for singular, plural in DURATION_ALIASES.items():
        text = re.sub(rf'\b{singular}\b', plural, text)
    
    # CRITICAL: Add space between number and duration word if missing
    # "5days" -> "5 days", "2weeks" -> "2 weeks"
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
    
    Examples
    --------
    >>> normalize_field("dosage", "500 mg")
    '500mg'
    >>> normalize_field("frequency", "twice daily")
    '1-0-1'
    >>> normalize_field("medicine_name", "  Augmentin  ")
    'Augmentin'
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
    
    Examples
    --------
    >>> med = {"medicine_name": "Augmentin", "dosage": "625 mg", "frequency": "twice daily"}
    >>> normalize_medicine_dict(med)
    {'medicine_name': 'Augmentin', 'dosage': '625mg', 'frequency': '1-0-1'}
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
    
    # Fall back to fuzzy matching for remaining cases. token_set_ratio (rather
    # than token_sort_ratio) is used because it ignores extra tokens present
    # on only one side -- e.g. ground truth frequency notes like
    # "PRN (if fever > 102F)" vs a predicted "as needed" should still be
    # recognized as the same meaning where the core tokens overlap.
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


# =============================================================================
# CONVENIENCE ALIASES
# =============================================================================

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
    
    Examples
    --------
    >>> normalize_text("  Hello World  ")
    'Hello World'
    >>> normalize_text("unread")
    'unread'
    """
    return normalize_text_field(text)
