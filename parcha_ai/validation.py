"""
Pydantic V2 validation schemas for ParchaAI prescription extraction pipeline.

This module defines the complete data models for prescription extraction results,
including all 11 target fields plus metadata and status tracking flags.

Key Models
----------
- MedicineDetail: Complete medicine information with all 11 fields
- PrescriptionResponse: Root response model containing list of medicines
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pathlib import Path


def normalize_null(value) -> str:
    """Normalize null-like values to 'unread' string.
    
    Parameters
    ----------
    value : any
        Value to normalize
    
    Returns
    -------
    str
        Normalized value or 'unread'
    """
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
    """
    Complete medicine information model with all 11 target fields.
    
    This model represents a single extracted medicine with:
    - 5 extracted fields (from prescription image)
    - 5 enriched fields (from database/API lookups)
    - 1 computed field (confidence score)
    - 4 status tracking flags
    
    Attributes
    ----------
    medicine_name : str
        Brand or generic name of the medicine (REQUIRED, extracted from image)
    dosage : str
        Strength/amount (e.g., "625mg", "5ml"), extracted from image
    frequency : str
        Dosing schedule (e.g., "1-0-1", "twice daily"), extracted from image
    duration : str
        Treatment length (e.g., "5 days", "2 weeks"), extracted from image
    purpose : str
        Indication/reason for medication, extracted from image
    composition : str
        Active pharmaceutical ingredients, from database
    uses : str
        Medical uses/indications, from database
    side_effects : str
        Known adverse effects, from database or FDA
    precautions : str
        Warnings and contraindications, from FDA API
    manufacturer : str
        Manufacturing company name, from database
    confidence : float
        Extraction quality score (0.0 to 1.0), computed
    found_in_local_db : bool
        Whether medicine was matched in local database
    found_in_openfda : bool
        Whether medicine was found in OpenFDA API
    low_confidence : bool
        Flag indicating confidence below threshold
    requires_human_review : bool
        Flag indicating manual review needed
    
    Examples
    --------
     med = MedicineDetail(
         medicine_name="Augmentin",
         dosage="625mg",
         frequency="1-0-1",
         duration="5 days",
         purpose="bacterial infection",
         composition="Amoxycillin (500mg) + Clavulanic Acid (125mg)",
         uses="Treatment of Bacterial infections",
         side_effects="Nausea, Vomiting, Diarrhea",
         precautions="Take with food",
         manufacturer="GSK",
         confidence=0.92,
         found_in_local_db=True,
         found_in_openfda=False,
         low_confidence=False,
         requires_human_review=False
     )
    """
    
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
    # ENRICHED FIELDS (from database or API lookups)
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
        """Check if all required fields are filled (not 'unread').
        
        Returns
        -------
        bool
            True if all 11 fields contain actual data
        """
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
        """Get list of field names that are 'unread'.
        
        Returns
        -------
        list[str]
            Names of fields containing 'unread'
        """
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
    """
    Root response model for prescription extraction results.
    
    This model contains metadata about the prescription and a list of
    all medicines extracted from it.
    
    Attributes
    ----------
    prescription_id : str
        Unique identifier for this prescription (typically filename)
    image_path : Optional[str]
        Path to the prescription image file
    extraction_timestamp : datetime
        When the extraction was performed
    extracted_medicines : List[MedicineDetail]
        List of all medicines extracted from this prescription
    total_medicines : int
        Count of medicines extracted (auto-computed)
    average_confidence : float
        Average confidence across all medicines (auto-computed)
    requires_review : bool
        Whether any medicine requires human review (auto-computed)
    extraction_time_seconds : Optional[float]
        Time taken for extraction in seconds
    fallback_model_used : bool
        Whether fallback/verification model was triggered
    
    Examples
    --------
     response = PrescriptionResponse(
         prescription_id="rx_01.jpg",
         image_path="/path/to/rx_01.jpg",
         extracted_medicines=[med1, med2, med3]
     )
    """
    
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
        """Convert model to dictionary.
        
        Returns
        -------
        dict
            Dictionary representation including all nested medicines
        """
        return self.model_dump()
    
    def get_high_confidence_medicines(self, threshold: float = 0.85) -> List[MedicineDetail]:
        """Get medicines with confidence above threshold.
        
        Parameters
        ----------
        threshold : float, optional
            Confidence threshold, by default 0.85
        
        Returns
        -------
        list[MedicineDetail]
            Medicines with confidence >= threshold
        """
        return [m for m in self.extracted_medicines if m.confidence >= threshold]
    
    def get_low_confidence_medicines(self, threshold: float = 0.85) -> List[MedicineDetail]:
        """Get medicines with confidence below threshold.
        
        Parameters
        ----------
        threshold : float, optional
            Confidence threshold, by default 0.85
        
        Returns
        -------
        list[MedicineDetail]
            Medicines with confidence < threshold
        """
        return [m for m in self.extracted_medicines if m.confidence < threshold]
    
    def get_review_required_medicines(self) -> List[MedicineDetail]:
        """Get medicines requiring human review.
        
        Returns
        -------
        list[MedicineDetail]
            Medicines flagged for review
        """
        return [m for m in self.extracted_medicines if m.requires_human_review]
    
    def get_unidentified_medicines(self) -> List[MedicineDetail]:
        """Get medicines not found in any database.
        
        Returns
        -------
        list[MedicineDetail]
            Medicines not found in local DB or OpenFDA
        """
        return [
            m for m in self.extracted_medicines
            if not m.found_in_local_db and not m.found_in_openfda
        ]
    
    def summary(self) -> str:
        """Generate a human-readable summary.
        
        Returns
        -------
        str
            Summary text
        """
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
    """Create a MedicineDetail instance from raw extraction data.
    
    Parameters
    ----------
    extraction_data : dict
        Dictionary containing extracted fields
    confidence : float, optional
        Confidence score, by default 0.0
    
    Returns
    -------
    MedicineDetail
        Validated medicine instance
    
    Examples
    --------
     data = {
         "medicine_name": "Augmentin",
         "dosage": "625mg",
         "frequency": "twice daily",
         "duration": "5 days"
     }
     med = create_medicine_from_extraction(data, confidence=0.9)
    """
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
    """Create a PrescriptionResponse instance.
    
    Parameters
    ----------
    prescription_id : str
        Prescription identifier
    medicines : list[MedicineDetail]
        List of extracted medicines
    image_path : str, optional
        Path to image file
    extraction_time : float, optional
        Time taken in seconds
    fallback_used : bool, optional
        Whether fallback model was used
    
    Returns
    -------
    PrescriptionResponse
        Complete prescription response
    """
    return PrescriptionResponse(
        prescription_id=prescription_id,
        image_path=image_path,
        extracted_medicines=medicines,
        extraction_time_seconds=extraction_time,
        fallback_model_used=fallback_used
    )