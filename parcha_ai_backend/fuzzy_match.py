
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Tuple
import pandas as pd
from rapidfuzz import process, fuzz

from .config import get_config
from .validation import MedicineDetail

logger = logging.getLogger(__name__)


class MedicineMatcher:
    """
    RapidFuzz-based medicine name matcher with local database lookup.
    
    This class loads the cleaned drug reference database and provides
    fuzzy string matching to correct OCR errors and retrieve medicine metadata.
    
    Attributes
    ----------
    df : pd.DataFrame
        Loaded drug reference database
    medicine_names : list[str]
        List of all medicine names for matching
    score_cutoff : int
        Minimum fuzzy match score (0-100) to accept a match
    
    Examples
    --------
     matcher = MedicineMatcher()
     result = matcher.match_medicine("Augmentin")
     print(result['official_name'])
    'Augmentin 625 Duo Tablet'
     print(result['composition'])
    'Amoxycillin (500mg) + Clavulanic Acid (125mg)'
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        score_cutoff: int = 85
    ):
        """
        Initialize the medicine matcher.
        
        Parameters
        ----------
        db_path : Path, optional
            Path to the drug reference database CSV.
            If None, uses default path from config.
        score_cutoff : int, optional
            Minimum fuzzy match score (0-100), by default 80
        
        Raises
        ------
        FileNotFoundError
            If database file doesn't exist
        ValueError
            If database is empty or missing required columns
        """
        self.score_cutoff = score_cutoff
        
        # Get database path
        if db_path is None:
            cfg = get_config()
            db_path = cfg.drug_reference_db
        
        self.db_path = db_path
        
        # Load database
        logger.info(f"Loading drug reference database from: {db_path}")
        self._load_database()
        
        logger.info(
            f"Medicine matcher initialized with {len(self.medicine_names)} medicines, "
            f"score_cutoff={self.score_cutoff}"
        )
    
    @property
    def drug_count(self) -> int:
        """Get the number of medicines in the database."""
        return len(self.medicine_names)
    
    def _load_database(self) -> None:
        """Load and validate the drug reference database.
        
        Raises
        ------
        FileNotFoundError
            If database file doesn't exist
        ValueError
            If database is invalid
        """
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Drug reference database not found: {self.db_path}\n"
                f"Please run: python datasets/clean_dataset.py"
            )
        
        # Load CSV
        try:
            self.df = pd.read_csv(self.db_path, encoding='utf-8')
        except Exception as e:
            raise ValueError(f"Failed to load database: {e}")
        
        # Validate required columns
        required_columns = [
            'Medicine Name',
            'Composition',
            'Uses',
            'Side_effects',
            'Manufacturer'
        ]
        
        missing_columns = [col for col in required_columns if col not in self.df.columns]
        if missing_columns:
            raise ValueError(
                f"Database missing required columns: {missing_columns}\n"
                f"Available columns: {list(self.df.columns)}"
            )
        
        # Check if database is empty
        if len(self.df) == 0:
            raise ValueError("Database is empty")
        
        # Build normalized matching column for robust fuzzy matching
        self.df['normalized_name'] = self.df['Medicine Name'].fillna('').astype(str).apply(
            self._normalize_name
        )

        # Extract medicine names for matching
        self.medicine_names = self.df['Medicine Name'].dropna().astype(str).tolist()
        self.normalized_medicine_names = self.df['normalized_name'].dropna().astype(str).tolist()

        self._normalized_name_to_original: Dict[str, str] = {}
        for _, row in self.df.iterrows():
            normalized_name = str(row.get('normalized_name', '')).strip()
            if normalized_name and normalized_name not in self._normalized_name_to_original:
                self._normalized_name_to_original[normalized_name] = str(row['Medicine Name']).strip()

        if not self.medicine_names:
            raise ValueError("No valid medicine names found in database")

        logger.info(f"Loaded {len(self.df)} medicines from database")
    
    def _normalize_name(self, name: str) -> str:
        """Normalize medicine names for robust fuzzy matching."""
        if not isinstance(name, str):
            return ""

        normalized = name.strip().lower()

        # Strip dosage values like 500mg / 5 ml
        normalized = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|ml|g|mcg|ug|iu)\b", "", normalized)
        normalized = re.sub(r"\b\d+(?:\.\d+)?\s*(?:tablet|tablets|capsule|capsules|syrup|syrups|injection|injections|drops|drop|cream|creams|suspension|suspensions)\b", "", normalized)

        # Strip trailing formulation words and common database suffixes
        formulations = [
            "tablet", "tablets", "cap", "capsule", "capsules", "syrup", "syrups",
            "inj", "injection", "injections", "drop", "drops", "cream", "creams",
            "suspension", "suspensions", "susp", "solution", "solutions",
            "powder", "powders", "gel", "gels", "ointment", "ointments"
        ]
        normalized = re.sub(rf"\b(?:{'|'.join(formulations)})\b", "", normalized)

        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def match_medicine(
        self,
        query: str,
        score_cutoff: Optional[int] = None
    ) -> Optional[Dict[str, any]]:
        """
        Match a medicine name against the database using fuzzy matching.
        
        This method:
        1. Uses RapidFuzz to find the best match in the database
        2. Returns the official name and metadata if match score >= cutoff
        3. Returns None if no good match is found
        
        Parameters
        ----------
        query : str
            Medicine name to match (possibly misspelled or incomplete)
        score_cutoff : int, optional
            Override the default score cutoff for this query
        
        Returns
        -------
        dict or None
            Dictionary containing match results, or None if no match
            
            Dictionary structure:
            {
                'official_name': str,        # Corrected medicine name
                'composition': str,          # Active ingredients
                'uses': str,                 # Medical uses
                'side_effects': str,         # Adverse effects
                'manufacturer': str,         # Company name
                'match_score': int,          # Fuzzy match score (0-100)
                'query': str                 # Original query
            }
        
        """
        if not query or not isinstance(query, str):
            logger.warning(f"Invalid query: {query}")
            return None
        
        query = query.strip()
        if not query:
            return None
        
        # Use provided cutoff or default
        cutoff = score_cutoff if score_cutoff is not None else self.score_cutoff
        normalized_query = self._normalize_name(query)

        # Perform fuzzy matching on normalized names using a token-based scorer
        try:
            match_result = process.extractOne(
                normalized_query,
                self.normalized_medicine_names,
                scorer=fuzz.WRatio,
                score_cutoff=cutoff
            )
        except Exception as e:
            logger.error(f"Fuzzy matching failed for query '{query}': {e}")
            return None

        # Check if match was found
        if match_result is None:
            logger.debug(f"No match found for '{query}' (cutoff={cutoff})")
            return None

        matched_normalized_name, match_score, _ = match_result
        matched_name = self._normalized_name_to_original.get(
            matched_normalized_name,
            matched_normalized_name
        )

        logger.info(f"Matched '{query}' -> '{matched_name}' (score={match_score})")

        # Retrieve full record from database
        record = self._get_medicine_record(matched_name)
        
        if record is None:
            logger.warning(f"Matched name '{matched_name}' not found in database")
            return None
        
        return {
            'official_name': matched_name,
            'composition': record.get('Composition', 'unread'),
            'uses': record.get('Uses', 'unread'),
            'side_effects': record.get('Side_effects', 'unread'),
            'manufacturer': record.get('Manufacturer', 'unread'),
            'match_score': match_score,
            'query': query
        }
    
    def _get_medicine_record(self, medicine_name: str) -> Optional[Dict[str, any]]:
        """
        Retrieve full database record for a medicine name.
        
        Parameters
        ----------
        medicine_name : str
            Exact medicine name from database
        
        Returns
        -------
        dict or None
            Medicine record as dictionary, or None if not found
        """
        # Find matching row
        matches = self.df[self.df['Medicine Name'] == medicine_name]
        
        if matches.empty:
            return None
        
        record = matches.iloc[0].to_dict()
        
        # Normalize null values to "unread"
        for key, value in record.items():
            if pd.isna(value) or str(value).strip().lower() in {'null', 'none', 'nan', ''}:
                record[key] = 'unread'
            else:
                record[key] = str(value).strip()
        
        return record
    
    def enrich_medicine(
        self,
        medicine: MedicineDetail,
        auto_correct_name: bool = True
    ) -> MedicineDetail:
        
        # Attempt to match medicine
        match_result = self.match_medicine(medicine.medicine_name)
        
        if match_result is None:
            # No match found
            logger.debug(f"No database match for: {medicine.medicine_name}")
            medicine.found_in_local_db = False
            return medicine
        
        # Match found - enrich the medicine
        logger.info(
            f"Enriching '{medicine.medicine_name}' with database info "
            f"(match_score={match_result['match_score']})"
        )
        
        # Auto-correct name if requested and match score is high
        if auto_correct_name and match_result['match_score'] >= 85:
            original_name = medicine.medicine_name
            medicine.medicine_name = match_result['official_name']
            logger.info(f"Auto-corrected: '{original_name}' -> '{medicine.medicine_name}'")
        
        # Fill in metadata
        medicine.composition = match_result['composition']
        medicine.uses = match_result['uses']
        medicine.side_effects = match_result['side_effects']
        medicine.manufacturer = match_result['manufacturer']
        medicine.found_in_local_db = True
        
        return medicine
    
    def batch_match(
        self,
        queries: list[str],
        score_cutoff: Optional[int] = None
    ) -> Dict[str, Optional[Dict[str, any]]]:
        """
        Match multiple medicine names in batch.
        
        Parameters
        ----------
        queries : list[str]
            List of medicine names to match
        score_cutoff : int, optional
            Override default score cutoff
        
        Returns
        -------
        dict
            Mapping of query -> match result (or None)
        
        """
        results = {}
        
        for query in queries:
            results[query] = self.match_medicine(query, score_cutoff)
        
        return results
    
    def get_statistics(self) -> Dict[str, any]:
        """
        Get statistics about the loaded database.
        
        Returns
        -------
        dict
            Database statistics
        """
        return {
            'total_medicines': len(self.df),
            'unique_manufacturers': self.df['Manufacturer'].nunique(),
            'medicines_with_composition': (self.df['Composition'] != 'unread').sum(),
            'medicines_with_uses': (self.df['Uses'] != 'unread').sum(),
            'medicines_with_side_effects': (self.df['Side_effects'] != 'unread').sum(),
            'score_cutoff': self.score_cutoff,
            'database_path': str(self.db_path)
        }
    
    def reload_database(self) -> None:
        """
        Reload the database from disk.
        
        Useful if the database file has been updated.
        """
        logger.info("Reloading drug reference database")
        self._load_database()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_global_matcher: Optional[MedicineMatcher] = None


def get_matcher(reload: bool = False) -> MedicineMatcher:

    global _global_matcher
    
    if _global_matcher is None or reload:
        _global_matcher = MedicineMatcher()
    
    return _global_matcher


def quick_match(query: str, score_cutoff: int = 80) -> Optional[Dict[str, any]]:

    matcher = get_matcher()
    return matcher.match_medicine(query, score_cutoff)


def quick_enrich(medicine: MedicineDetail) -> MedicineDetail:

    matcher = get_matcher()
    return matcher.enrich_medicine(medicine)