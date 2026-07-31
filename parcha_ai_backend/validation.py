
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pathlib import Path


def normalize_null(value) -> str:

    if value is None:
        return "unread"
    
    if not isinstance(value, str):
        value = str(value)
    
    value = value.strip()
    
    null_like = {"null", "none", "nan", "n/a", "na", "", "unknown"}
    if value.lower() in null_like:
        return "unread"
    
    return value


class MedicineDetail(BaseModel):
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )
    
    # =========================================================================
    # EXTRACTED FIELDS 
    # =========================================================================
    
    medicine_name: str = Field(
        ...,
        description="Brand or generic name of the medicine",
        min_length=1,
        examples=["Augmentin", "Paracetamol", "Azithromycin"]
    )
    
    dosage: str = Field(
        default="unread",
        description="Strength/amount (e.g., 625mg, 5ml, 1 tab)",
        examples=["625mg", "500mg", "5ml", "1 tab"]
    )
    
    frequency: str = Field(
        default="unread",
        description="Dosing schedule (e.g., twice daily, 1-0-1, prn)",
        examples=["1-0-1", "twice daily", "three times daily", "prn"]
    )
    
    duration: str = Field(
        default="unread",
        description="Treatment length (e.g., 5 days, 2 weeks)",
        examples=["5 days", "7 days", "2 weeks", "1 month"]
    )
    
    purpose: str = Field(
        default="unread",
        description="Indication/reason for medication",
        examples=["bacterial infection", "fever", "pain relief", "hypertension"]
    )
    
    # =========================================================================
    # ENRICHED FIELDS 
    # =========================================================================
    
    composition: str = Field(
        default="unread",
        description="Active pharmaceutical ingredients",
        examples=["Amoxycillin (500mg) + Clavulanic Acid (125mg)", "Paracetamol (500mg)"]
    )
    
    uses: str = Field(
        default="unread",
        description="Medical uses and indications",
        examples=["Treatment of Bacterial infections", "Pain relief, Fever reduction"]
    )
    
    side_effects: str = Field(
        default="unread",
        description="Known adverse effects",
        examples=["Nausea, Vomiting, Diarrhea", "Dizziness, Headache"]
    )
    
    precautions: str = Field(
        default="unread",
        description="Warnings, contraindications, and safety information",
        examples=["Take with food", "Avoid alcohol", "Not for pregnant women"]
    )
    
    manufacturer: str = Field(
        default="unread",
        description="Manufacturing company name",
        examples=["GlaxoSmithKline", "Cipla", "Abbott"]
    )
    
    # =========================================================================
    # URDU SUMMARIES 
    # =========================================================================
    
    uses_urdu_short: Optional[str] = Field(
        default=None,
        description="Simple 2-3 sentence Urdu summary of uses (for display only when present)"
    )
    
    side_effects_urdu_short: Optional[str] = Field(
        default=None,
        description="Simple 2-3 sentence Urdu summary of side effects (for display only when present)"
    )
    
    precautions_urdu_short: Optional[str] = Field(
        default=None,
        description="Simple 2-3 sentence Urdu summary of precautions (for display only when present)"
    )
    
    # =========================================================================
    # COMPUTED FIELD
    # =========================================================================
    
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Extraction quality score (0.0 to 1.0)"
    )

    
    extraction_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "The vision model's own self-reported confidence for this medicine "
            "at extraction time (before any database validation). Reflects "
            "handwriting legibility, not database coverage."
        )
    )
    
    # =========================================================================
    # STATUS TRACKING FLAGS
    # =========================================================================
    
    found_in_local_db: bool = Field(
        default=False,
        description="Whether medicine was matched in local database (11K South Asian medicines)"
    )
    
    found_in_openfda: bool = Field(
        default=False,
        description="Whether medicine was found in OpenFDA API (global drug database)"
    )
    
    low_confidence: bool = Field(
        default=False,
        description="Flag indicating extraction confidence below threshold (requires verification)"
    )
    
    requires_human_review: bool = Field(
        default=False,
        description="Flag indicating manual review needed (unidentified drug or low quality extraction)"
    )
    
    # =========================================================================
    # VALIDATORS
    # =========================================================================
    
    @field_validator('medicine_name', mode='before')
    @classmethod
    def validate_medicine_name(cls, v):
        """Ensure medicine name is not empty or null-like."""
        v = normalize_null(v)
        if v == "unread":
            raise ValueError(
                "medicine_name cannot be empty or unread. "
                "A valid medicine name must be extracted."
            )
        return v
    
    @field_validator(
        'dosage', 'frequency', 'duration', 'purpose',
        'composition', 'uses', 'side_effects', 'precautions', 'manufacturer',
        mode='before'
    )
    @classmethod
    def normalize_text_fields(cls, v):
        """Normalize text fields to 'unread' if null-like."""
        return normalize_null(v)
    
    @field_validator('confidence', mode='before')
    @classmethod
    def clamp_confidence(cls, v):
        """Ensure confidence is between 0.0 and 1.0."""
        if v is None:
            return 0.0
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, v))
    
    @field_validator('low_confidence', mode='after')
    @classmethod
    def auto_set_low_confidence_flag(cls, v, info):
        """Automatically set low_confidence flag if confidence is below 0.7."""
        # Access confidence from the instance data
        if 'confidence' in info.data:
            confidence = info.data['confidence']
            if confidence < 0.7:
                return True
        return v
    
    @field_validator('requires_human_review', mode='after')
    @classmethod
    def auto_set_review_flag(cls, v, info):
        """Automatically set review flag if drug is unidentified or confidence is very low."""
        data = info.data
        
        # Unidentified drug (not in DB and not in FDA)
        if not data.get('found_in_local_db') and not data.get('found_in_openfda'):
            return True
        
        # Very low confidence
        if data.get('confidence', 0.0) < 0.5:
            return True
        
        # Low confidence flag already set
        if data.get('low_confidence'):
            return True
        
        return v
    
    def to_dict(self) -> dict:
        """Convert model to dictionary.
        
        Returns
        -------
        dict
            Dictionary representation of the medicine
        """
        return self.model_dump()
    
    def is_complete(self) -> bool:

        fields_to_check = [
            self.medicine_name,
            self.dosage,
            self.frequency,
            self.duration,
            self.purpose,
            self.composition,
            self.uses,
            self.side_effects,
            self.precautions,
            self.manufacturer
        ]
        
        return all(field != "unread" for field in fields_to_check)
    
    def get_missing_fields(self) -> List[str]:

        missing = []
        
        field_map = {
            'medicine_name': self.medicine_name,
            'dosage': self.dosage,
            'frequency': self.frequency,
            'duration': self.duration,
            'purpose': self.purpose,
            'composition': self.composition,
            'uses': self.uses,
            'side_effects': self.side_effects,
            'precautions': self.precautions,
            'manufacturer': self.manufacturer
        }
        
        for field_name, field_value in field_map.items():
            if field_value == "unread":
                missing.append(field_name)
        
        return missing


class PrescriptionResponse(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )
    
    # =========================================================================
    # METADATA FIELDS
    # =========================================================================
    
    prescription_id: str = Field(
        ...,
        description="Unique identifier for this prescription (typically image filename)",
        examples=["rx_01.jpg", "prescription_20240710_001"]
    )
    
    image_path: Optional[str] = Field(
        default=None,
        description="Path to the prescription image file"
    )
    
    extraction_timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the extraction was performed"
    )
    
    # =========================================================================
    # CORE DATA
    # =========================================================================
    
    extracted_medicines: List[MedicineDetail] = Field(
        default_factory=list,
        description="List of all medicines extracted from this prescription"
    )
    
    # =========================================================================
    # COMPUTED FIELDS
    # =========================================================================
    
    total_medicines: int = Field(
        default=0,
        description="Count of medicines extracted",
        ge=0
    )
    
    average_confidence: float = Field(
        default=0.0,
        description="Average confidence score across all medicines",
        ge=0.0,
        le=1.0
    )
    
    requires_review: bool = Field(
        default=False,
        description="Whether any medicine requires human review"
    )
    
    # =========================================================================
    # PERFORMANCE METRICS
    # =========================================================================
    
    extraction_time_seconds: Optional[float] = Field(
        default=None,
        description="Time taken for extraction in seconds",
        ge=0.0
    )
    
    fallback_model_used: bool = Field(
        default=False,
        description="Whether fallback/verification model was triggered"
    )
    
    # =========================================================================
    # VALIDATORS
    # =========================================================================
    
    @field_validator('total_medicines', mode='after')
    @classmethod
    def compute_total_medicines(cls, v, info):
        """Auto-compute total medicines from list length."""
        if 'extracted_medicines' in info.data:
            return len(info.data['extracted_medicines'])
        return v
    
    @field_validator('average_confidence', mode='after')
    @classmethod
    def compute_average_confidence(cls, v, info):
        """Auto-compute average confidence from medicines list."""
        if 'extracted_medicines' in info.data:
            medicines = info.data['extracted_medicines']
            if medicines:
                total_conf = sum(m.confidence for m in medicines)
                return total_conf / len(medicines)
        return 0.0
    
    @field_validator('requires_review', mode='after')
    @classmethod
    def compute_requires_review(cls, v, info):
        """Auto-compute review flag from medicines list."""
        if 'extracted_medicines' in info.data:
            medicines = info.data['extracted_medicines']
            return any(m.requires_human_review for m in medicines)
        return v
    
    def to_dict(self) -> dict:

        return self.model_dump()
    
    def get_high_confidence_medicines(self, threshold: float = 0.85) -> List[MedicineDetail]:

        return [m for m in self.extracted_medicines if m.confidence >= threshold]
    
    def get_low_confidence_medicines(self, threshold: float = 0.85) -> List[MedicineDetail]:

        return [m for m in self.extracted_medicines if m.confidence < threshold]
    
    def get_review_required_medicines(self) -> List[MedicineDetail]:

        return [m for m in self.extracted_medicines if m.requires_human_review]
    
    def get_unidentified_medicines(self) -> List[MedicineDetail]:

        return [
            m for m in self.extracted_medicines
            if not m.found_in_local_db and not m.found_in_openfda
        ]
    
    def summary(self) -> str:

        lines = [
            f"Prescription: {self.prescription_id}",
            f"Medicines Extracted: {self.total_medicines}",
            f"Average Confidence: {self.average_confidence:.2f}",
            f"Requires Review: {'Yes' if self.requires_review else 'No'}",
        ]
        
        if self.extraction_time_seconds:
            lines.append(f"Extraction Time: {self.extraction_time_seconds:.2f}s")
        
        if self.fallback_model_used:
            lines.append("Fallback Model: Used")
        
        # Add medicine details
        lines.append("\nMedicines:")
        for i, med in enumerate(self.extracted_medicines, 1):
            status = "✓" if med.confidence >= 0.85 else "⚠"
            lines.append(
                f"  {status} {i}. {med.medicine_name} - {med.dosage} - "
                f"{med.frequency} - {med.duration} (conf: {med.confidence:.2f})"
            )
        
        return "\n".join(lines)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_medicine_from_extraction(
    extraction_data: dict,
    confidence: float = 0.0
) -> MedicineDetail:

    return MedicineDetail(
        medicine_name=extraction_data.get("medicine_name", ""),
        dosage=extraction_data.get("dosage", "unread"),
        frequency=extraction_data.get("frequency", "unread"),
        duration=extraction_data.get("duration", "unread"),
        purpose=extraction_data.get("purpose", "unread"),
        confidence=confidence
    )


def create_prescription_response(
    prescription_id: str,
    medicines: List[MedicineDetail],
    image_path: Optional[str] = None,
    extraction_time: Optional[float] = None,
    fallback_used: bool = False
) -> PrescriptionResponse:

    return PrescriptionResponse(
        prescription_id=prescription_id,
        image_path=image_path,
        extracted_medicines=medicines,
        extraction_time_seconds=extraction_time,
        fallback_model_used=fallback_used
    )