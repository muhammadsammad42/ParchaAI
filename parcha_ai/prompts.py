"""
Prompt templates for ParchaAI prescription extraction pipeline.

This module contains all system prompts and user prompt templates used for:
- Two-pass Gemini Vision extraction (medicine count + full extraction)
- Fallback verification with Groq Vision
- Few-shot prompting support
- Anti-hallucination guardrails
"""

from typing import Optional


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

SYSTEM_PROMPT = """You are a medical prescription reading assistant. You read handwritten \
doctor prescriptions and extract structured information with extreme care and honesty.

STRICT RULES:
- Never invent a medicine name that is not visibly written.
- Never guess a dosage, frequency, duration, or purpose.
- If any field cannot be read with confidence, set its value to the string "unread".
- Return valid JSON only. No markdown, no code fences, no explanations, no extra text.

FIELD ISOLATION RULE (important):
You must strictly isolate the raw medicine/brand name from its dosage strength. Never \
include milligrams, milliliters, or pill counts inside the "medicine_name" field -- that \
information belongs in "dosage" only.

Example:
If the prescription reads "Augmentin 625mg", your JSON output MUST be:
{"medicine_name": "Augmentin", "dosage": "625mg", ...}
NOT:
{"medicine_name": "Augmentin 625mg", "dosage": "unread", ...}
"""


# =============================================================================
# TWO-PASS EXTRACTION PROMPTS
# =============================================================================

PASS1_PROMPT = """Look at this handwritten prescription image very carefully.
How many distinct medicines are written on it?

Before answering, check the whole image methodically:
- Scan every line, including the top, margins, and the back of a line if the
  prescription continues there.
- Some prescriptions list two medicines on the SAME line (separated by a
  comma, "+", "&", or simply written close together) -- count each one
  separately.
- A medicine written across two lines (name on one line, dosage/frequency on
  the next) is still only ONE medicine.
- Faint, small, or crowded handwriting is easy to miss on a quick glance --
  look again at any line you are not sure about before finalizing your count.
- If truly uncertain between two counts, prefer the HIGHER count. This number
  is only used as a starting guide for a second, more careful pass -- it is
  better to slightly overcount here than to cause a real medicine to be
  skipped later.

Respond with ONLY a single JSON object: {"medicine_count": <integer>}
"""


PASS2_PROMPT_TEMPLATE = """You are analyzing a handwritten prescription image. A quick first pass over
this same image counted approximately {count} medicine(s), but that count can be wrong --
especially when medicines share a line, continue across lines, or are faint/crowded.

CRITICAL ANTI-HALLUCINATION RULES:
1. Extract EVERY medicine actually visible in the image, whether that is exactly
   {count}, or more, or fewer than {count}. Use {count} only as a rough guide, not a
   hard limit -- if you can clearly see an additional medicine the first pass missed,
   include it (protects Recall). Do not invent a medicine just to reach {count}, and
   do not drop a medicine you can clearly see just to match {count} (protects Precision).
2. If handwriting is illegible or ambiguous, write "unread" for that field - NEVER guess.
3. For enrichment fields (composition, uses, side_effects, precautions, manufacturer), ALWAYS write "unread" - a downstream database will provide these.- Do not include any medicine not visible in the image. If you are not confident a line is a medicine, exclude it rather than guess.
- If a qualifier is parenthetical, such as a condition, threshold, or maximum daily limit, extract it into the relevant field if it is visibly present.

LINE ASSOCIATION AND COMPLEX-SCHEDULE RULES (read before extracting):
- Work top-to-bottom. For each medicine, first identify its complete visual
  line/block, then copy ONLY the dose, frequency and duration attached to that
  same block. Never borrow a frequency or duration from the line above/below.
- A line can contain a loading/taper schedule. Preserve a legible schedule in
  the appropriate field instead of replacing it with "unread". Examples:
  "200 mg STAT then 100 mg OD" -> dosage "200 mg STAT, then 100 mg" and
  frequency "STAT once then once a day"; "Day 1: 15 mL, Day 2: 7.5 mL" ->
  dosage "Day 1: 15 mL, Day 2: 7.5 mL".
- If the prescription says a finite course, dose count, or follow-up duration
  (for example "3 weeks", "4 days", "2 doses total"), copy it into duration.
  Do not omit a duration merely because it is written at the far right of the
  medicine line or once for a grouped list.
- Dosage FORM (syrup, drops, tablet, injection, cream) is part of the visible
  medicine identification when needed to distinguish entries. Keep it in
  medicine_name if it is written with the brand; never put the numeric strength
  in medicine_name.
STRICT FIELD EXTRACTION RULES:

medicine_name:
- Extract ONLY the brand/generic name (e.g., "Augmentin", "Paracetamol")
- NEVER include dosage strength in the name (that goes in "dosage")
- If illegible: write "unread"

dosage:
- Extract strength/amount with SPACE between number and unit (e.g., "500 mg", "5 ml", "1 tab")
- Common units: mg, ml, g, mcg, tab, cap, iu
- Handwritten digits are easy to confuse -- double check each digit before
  finalizing: 1 vs 7, 0 vs 6 vs 8, 4 vs 9, 3 vs 5. If two digits could
  plausibly be either one, lower your confidence score rather than guessing.
- If illegible: write "unread"

frequency:
- Convert abbreviations to full English phrases with proper spacing:
  * "OD" or "od" → "once a day"
  * "BD" or "BID" or "bid" → "twice a day"
  * "TDS" or "TID" or "tid" → "three times a day"
  * "QID" or "qid" → "four times a day"
  * "PRN" or "prn" or "SOS" or "sos" → "as needed"
  * "Q4H" or "every 4 hours" → "six times a day"
  * "Q6H" or "every 6 hours" → "four times a day"
  * "Q8H" or "every 8 hours" → "three times a day"
  * "Q12H" or "every 12 hours" → "twice a day"
  * "Q24H", "OD", or "every 24 hours" → "once a day"
- These conversions apply EVEN IF the frequency is followed by an extra
  condition or note (e.g. "PRN if fever", "TDS after meals", "Q6H max 4
  doses/day") -- convert the abbreviation itself and drop the trailing note
  from this field (the condition, if clinically important, belongs in
  "purpose" instead, not concatenated into "frequency").
- Write out patterns: "1-0-1" or "morning and night" → "twice a day"
- Add SPACE: "1tab" → "1 tab"
- IMPORTANT - do not let a complex DOSAGE schedule make you mark frequency
  as unread: dosage and frequency are separate fields. If the dosage
  involves a taper or multi-day schedule (e.g. "Day 1: 15 mL, Day 2: 7.5
  mL") but a base frequency word IS legibly written somewhere on that line
  (e.g. "once daily", "OD", "BD"), still extract that frequency normally --
  do not mark frequency "unread" just because the dosage amount changes
  over time. Only write "unread" for frequency when no frequency word or
  abbreviation is legible at all, not merely because the dosage is complex.
- If illegible: write "unread"

duration:
- Write with SPACE between number and unit (e.g., "5 days", "2 weeks", "1 month")
- If illegible: write "unread"

purpose:
- Extract indication if visible (e.g., "fever", "pain", "infection")
- If not mentioned: write "unread"

ENRICHMENT FIELDS (ALWAYS "unread" - database will fill these):
- composition: ALWAYS write "unread"
- uses: ALWAYS write "unread"
- side_effects: ALWAYS write "unread"
- precautions: ALWAYS write "unread"
- manufacturer: ALWAYS write "unread"

confidence:
- Your honest self-assessment (0.0 to 1.0)
- High (0.8-1.0): Clear, legible handwriting
- Medium (0.5-0.8): Some ambiguity but reasonable confidence
- Low (0.0-0.5): Difficult handwriting, multiple "unread" fields

OUTPUT FORMAT:
Return ONLY valid JSON. No markdown fences, no explanations, no extra text.

{{
  "medicines": [
    {{
      "medicine_name": "...",
      "dosage": "...",
      "frequency": "...",
      "duration": "...",
      "purpose": "...",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.0
    }}
  ]
}}

REMEMBER:
- {count} is only a rough starting guide from a quick first pass, NOT a hard
  target. Extract every medicine you can actually see, even if that means
  the final list has more or fewer entries than {count}. Missing a real
  medicine to match {count} is a worse error than including one extra.
- When in doubt, write "unread" - NEVER guess
- Use proper spacing: "500 mg" not "500mg", "5 days" not "5days"
- Format numbers and units with a single space: "500 mg", "5 ml", "1 tab"
- Convert abbreviations: "BD" → "twice a day"
- All enrichment fields MUST be "unread"

Now analyze the prescription image and extract the medicines following these strict rules.
"""


# =============================================================================
# FALLBACK VERIFICATION PROMPT (for secondary vision model)
# =============================================================================

FALLBACK_SYSTEM_PROMPT = SYSTEM_PROMPT + """
You are now acting as an independent VERIFIER for a low-confidence extraction made by \
another model. Look at the prescription image yourself and treat it as the ground truth.
"""


FALLBACK_VERIFICATION_PROMPT_TEMPLATE = """A previous extraction of this same prescription image \
produced the JSON below, but it was flagged LOW CONFIDENCE (below {threshold}).

Previous (low-confidence) extraction:
{previous_json}

Look carefully at the image yourself and produce a corrected final answer:
- If a field in the previous extraction is already correct, keep it exactly as it is.
- Fix only fields that are actually wrong based on what you can see in the image.
- Re-scan every medication line, including faint lower/right-margin entries.
  Add a medicine only when its name is visibly present; remove a previous item
  only when it is clearly not a medicine in the image.
- Check dose, frequency and duration independently for every medicine. Do not
  copy a schedule from an adjacent line. Preserve visible loading/taper plans
  (for example "STAT then OD", "Day 1 / Day 2", or "2 doses total") rather
  than flattening them or marking them unread.
- Never invent a medicine name, dosage, frequency, duration, or purpose that is not visibly \
written on the prescription.
- If something genuinely cannot be read, use the exact string "unread".
- Make sure the medicine name field never contains dosage strength -- that belongs in "dosage".
- Include a "confidence" field per medicine (0 to 1) reflecting YOUR OWN confidence after \
reviewing the image.

Return ONLY valid JSON in this exact shape, with no markdown and no commentary:
{{
  "medicines": [
    {{
      "medicine_name": "...",
      "dosage": "...",
      "frequency": "...",
      "duration": "...",
      "purpose": "...",
      "confidence": 0.0
    }}
  ]
}}
"""


# =============================================================================
# FEW-SHOT EXAMPLES (Optional - can be prepended to prompts)
# =============================================================================

FEW_SHOT_EXAMPLES = """
EXAMPLE 1:
Prescription reads:
- Augmentin 625mg - 1 tab - Twice daily - 5 days
- Paracetamol 500mg - PRN (if fever)

Correct JSON:
{
  "medicines": [
    {
      "medicine_name": "Augmentin",
      "dosage": "625mg",
      "frequency": "Twice daily",
      "duration": "5 days",
      "purpose": "unread",
      "confidence": 0.95
    },
    {
      "medicine_name": "Paracetamol",
      "dosage": "500mg",
      "frequency": "PRN",
      "duration": "unread",
      "purpose": "if fever",
      "confidence": 0.90
    }
  ]
}

EXAMPLE 2:
Prescription reads (partially illegible):
- [unclear name] 10mg - Once daily
- Amoxicillin 500mg - [frequency unclear] - 7 days

Correct JSON:
{
  "medicines": [
    {
      "medicine_name": "unread",
      "dosage": "10mg",
      "frequency": "Once daily",
      "duration": "unread",
      "purpose": "unread",
      "confidence": 0.30
    },
    {
      "medicine_name": "Amoxicillin",
      "dosage": "500mg",
      "frequency": "unread",
      "duration": "7 days",
      "purpose": "unread",
      "confidence": 0.75
    }
  ]
}
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_counting_prompt() -> str:
    """
    Get the Pass 1 counting prompt.
    
    Returns
    -------
    str
        Counting prompt for Pass 1
    """
    return PASS1_PROMPT


def get_extraction_prompt(medicine_count: int, include_few_shot: bool = False) -> str:
    """
    Get the Pass 2 extraction prompt with strict anti-hallucination instructions.
    
    This prompt is designed to:
    - Maximize Precision by forcing "unread" for ambiguous fields
    - Maximize Recall by extracting exactly medicine_count items
    - Minimize Hallucination Rate through explicit constraints
    - Pre-standardize formats for better evaluation matching
    
    Parameters
    ----------
    medicine_count : int
        Number of medicines to extract (from Pass 1)
    include_few_shot : bool, optional
        Whether to include few-shot examples, by default False
    
    Returns
    -------
    str
        Complete extraction prompt for Pass 2
    """
    return build_pass2_prompt_enhanced(medicine_count, include_few_shot)


def build_pass2_prompt_enhanced(medicine_count: int, include_few_shot: bool = False) -> str:
    """Build the enhanced Pass 2 extraction prompt with anti-hallucination rules.
    
    Parameters
    ----------
    medicine_count : int
        Number of medicines detected in Pass 1
    include_few_shot : bool, optional
        Whether to prepend few-shot examples, by default False
    
    Returns
    -------
    str
        Complete Pass 2 prompt with strict extraction rules
    """
    prompt = PASS2_PROMPT_TEMPLATE.format(count=medicine_count)
    
    if include_few_shot:
        prompt = FEW_SHOT_EXAMPLES_ENHANCED + "\n\n" + prompt
    
    return prompt


# Enhanced few-shot examples showing proper formatting
FEW_SHOT_EXAMPLES_ENHANCED = """
EXAMPLE 1 - Clear Prescription:
Image shows:
- Augmentin 625mg - 1 tab BD - 5 days
- Paracetamol 500mg - PRN (if fever)

Correct Output:
{{
  "medicines": [
    {{
      "medicine_name": "Augmentin",
      "dosage": "625 mg",
      "frequency": "twice a day",
      "duration": "5 days",
      "purpose": "unread",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.95
    }},
    {{
      "medicine_name": "Paracetamol",
      "dosage": "500 mg",
      "frequency": "as needed",
      "duration": "unread",
      "purpose": "fever",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.90
    }}
  ]
}}

EXAMPLE 2 - Partially Illegible:
Image shows:
- [unclear name] 10mg - OD - 7 days
- Amoxicillin 500mg - [frequency unclear]

Correct Output:
{{
  "medicines": [
    {{
      "medicine_name": "unread",
      "dosage": "10 mg",
      "frequency": "once a day",
      "duration": "7 days",
      "purpose": "unread",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.40
    }},
    {{
      "medicine_name": "Amoxicillin",
      "dosage": "500 mg",
      "frequency": "unread",
      "duration": "unread",
      "purpose": "unread",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.65
    }}
  ]
}}

EXAMPLE 3 - Format Standardization:
Bad Input: "500mg" "BD" "5days"
Good Output: "500 mg" "twice a day" "5 days"

Bad Input: "tid" "1tab"
Good Output: "three times a day" "1 tab"

EXAMPLE 4 - Parenthetical Qualifiers:
Image shows:
- Amlodipine 5mg (for hypertension) - 1 tab OD
- Metformin 500mg (max 2g/day) - 1 tab BD

Correct Output:
{{
  "medicines": [
    {{
      "medicine_name": "Amlodipine",
      "dosage": "5 mg",
      "frequency": "once a day",
      "duration": "unread",
      "purpose": "hypertension",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.92
    }},
    {{
      "medicine_name": "Metformin",
      "dosage": "500 mg",
      "frequency": "twice a day",
      "duration": "unread",
      "purpose": "max 2g/day",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.90
    }}
  ]
}}

EXAMPLE 5 - Exclude Uncertain Lines:
Image shows one clearly visible medicine line and one uncertain scribble.
Correct Output:
{{
  "medicines": [
    {{
      "medicine_name": "Paracetamol",
      "dosage": "500 mg",
      "frequency": "twice a day",
      "duration": "5 days",
      "purpose": "unread",
      "composition": "unread",
      "uses": "unread",
      "side_effects": "unread",
      "precautions": "unread",
      "manufacturer": "unread",
      "confidence": 0.88
    }}
  ]
}}
"""


def build_pass2_prompt(medicine_count: int, include_few_shot: bool = False) -> str:
    """Build the Pass 2 extraction prompt (legacy function - redirects to enhanced version).
    
    Parameters
    ----------
    medicine_count : int
        Number of medicines detected in Pass 1
    include_few_shot : bool, optional
        Whether to prepend few-shot examples, by default False
    
    Returns
    -------
    str
        Complete Pass 2 prompt
    """
    # Redirect to enhanced version for better metrics
    return build_pass2_prompt_enhanced(medicine_count, include_few_shot)


def build_fallback_verification_prompt(
    previous_json: str,
    confidence_threshold: float,
    include_few_shot: bool = False
) -> str:
    """Build the fallback verification prompt for secondary model.
    
    Parameters
    ----------
    previous_json : str
        JSON string from the previous (low-confidence) extraction
    confidence_threshold : float
        The confidence threshold that triggered this verification
    include_few_shot : bool, optional
        Whether to prepend few-shot examples, by default False
    
    Returns
    -------
    str
        Complete fallback verification prompt
    """
    prompt = FALLBACK_VERIFICATION_PROMPT_TEMPLATE.format(
        previous_json=previous_json,
        threshold=confidence_threshold
    )
    
    if include_few_shot:
        prompt = FEW_SHOT_EXAMPLES + "\n\n" + prompt
    
    return prompt


# =============================================================================
# PROMPT VALIDATION & ANTI-HALLUCINATION CHECKS
# =============================================================================

HALLUCINATION_PREVENTION_CHECKLIST = [
    "✓ Prompt explicitly forbids inventing medicine names",
    "✓ Prompt requires 'unread' for unidentifiable fields",
    "✓ Prompt separates medicine name from dosage strength",
    "✓ Prompt forbids markdown/conversational wrappers",
    "✓ Prompt includes confidence scoring requirement",
    "✓ Few-shot examples demonstrate 'unread' usage",
]


def validate_prompt_safety(prompt: str) -> tuple[bool, list[str]]:
    """Validate that a prompt contains anti-hallucination safeguards.
    
    Parameters
    ----------
    prompt : str
        The prompt text to validate
    
    Returns
    -------
    tuple[bool, list[str]]
        (is_safe, list_of_warnings)
        is_safe is False if critical safeguards are missing
    """
    warnings = []
    
    # Check for key anti-hallucination phrases
    required_phrases = [
        "never invent",
        "unread",
        "cannot be read",
    ]
    
    for phrase in required_phrases:
        if phrase.lower() not in prompt.lower():
            warnings.append(f"Missing anti-hallucination safeguard: '{phrase}'")
    
    # Check for field isolation instructions
    if "medicine_name" in prompt and "dosage" in prompt:
        if "isolate" not in prompt.lower() and "separate" not in prompt.lower():
            warnings.append("Missing explicit field isolation instructions")
    
    is_safe = len(warnings) == 0
    return is_safe, warnings
