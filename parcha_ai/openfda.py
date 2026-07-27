"""
Asynchronous OpenFDA API client for global drug validation and safety information.

This module provides integration with the FDA's openFDA drug label API to:
1. Validate international/rare drugs not in local database
2. Retrieve safety information (warnings, precautions, adverse reactions)
3. Enrich prescription data with authoritative medical information

The client handles rate limiting, timeouts, and network errors gracefully.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from urllib.parse import urlencode
import httpx

from .config import get_config
from .validation import MedicineDetail

logger = logging.getLogger(__name__)


class OpenFDAClient:
    """
    Asynchronous client for OpenFDA Drug Label API.
    
    This client provides methods to:
    - Search for drugs by brand name or active ingredient
    - Retrieve safety information (warnings, precautions, adverse reactions)
    - Enrich MedicineDetail objects with FDA data
    
    The FDA API is used as a global fallback when medicines are not found
    in the local South Asian database.
    
    Attributes
    ----------
    base_url : str
        Base URL for OpenFDA API
    timeout : int
        Request timeout in seconds
    max_retries : int
        Maximum number of retry attempts
    
    Examples
    --------
    >>> client = OpenFDAClient()
    >>> result = await client.search_drug("Aspirin")
    >>> if result:
    ...     print(result['warnings'])
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 10,
        max_retries: int = 2
    ):
        """
        Initialize the OpenFDA client.
        
        Parameters
        ----------
        base_url : str, optional
            Base URL for OpenFDA API. If None, uses default from config.
        timeout : int, optional
            Request timeout in seconds, by default 10
        max_retries : int, optional
            Maximum retry attempts for failed requests, by default 2
        """
        # Get configuration
        cfg = get_config()
        self.base_url = base_url or cfg.openfda_api_url
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Statistics tracking
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'cache_hits': 0,
            'timeouts': 0,
            'rate_limits': 0
        }

        cfg = get_config()
        self.cache_dir = cfg.cache_dir / 'openfda'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Simple in-memory cache
        self._cache: Dict[str, Dict] = {}

        logger.info(
            f"OpenFDA client initialized: base_url={self.base_url}, "
            f"timeout={self.timeout}s, max_retries={self.max_retries}"
        )
    
    def _get_cache_key(self, query: str, search_field: str) -> str:
        """Create a stable SHA-256 cache key for OpenFDA queries."""
        payload = f"{search_field}:{query.lower()}".encode('utf-8')
        return hashlib.sha256(payload).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the JSON cache file path for a query."""
        return self.cache_dir / f"{cache_key}.json"

    def _load_cached_result(self, cache_key: str) -> Optional[Dict[str, any]]:
        """Load a cached OpenFDA result from disk if present."""
        cache_path = self._get_cache_path(cache_key)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning(f"Failed to read OpenFDA cache {cache_path.name}: {exc}")
            return None

    def _save_cached_result(self, cache_key: str, result: Dict[str, any]) -> None:
        """Persist an OpenFDA result to disk."""
        cache_path = self._get_cache_path(cache_key)
        try:
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"Failed to write OpenFDA cache {cache_path.name}: {exc}")

    async def search_drug(
        self,
        query: str,
        search_field: str = "openfda.brand_name",
        limit: int = 1
    ) -> Optional[Dict[str, any]]:
        """
        Search for a drug in the OpenFDA database.
        
        Parameters
        ----------
        query : str
            Drug name to search (brand name or generic name)
        search_field : str, optional
            Field to search in, by default "openfda.brand_name"
            Options: "openfda.brand_name", "openfda.generic_name"
        limit : int, optional
            Maximum number of results to return, by default 1
        
        Returns
        -------
        dict or None
            Drug information if found, None otherwise
            
            Dictionary structure:
            {
                'drug_name': str,
                'warnings': str,
                'precautions': str,
                'adverse_reactions': str,
                'indications_and_usage': str,
                'purpose': str,
                'active_ingredient': str
            }
        
        Examples
        --------
        >>> client = OpenFDAClient()
        >>> result = await client.search_drug("Aspirin")
        >>> if result:
        ...     print(result['warnings'])
        """
        if not query or not isinstance(query, str):
            logger.warning(f"Invalid query: {query}")
            return None
        
        query = query.strip()
        if not query:
            return None
        
        # Check in-memory cache first, then disk cache
        cache_key = self._get_cache_key(query, search_field)
        if cache_key in self._cache:
            logger.debug(f"Cache hit for: {query}")
            self.stats['cache_hits'] += 1
            return self._cache[cache_key]

        cached_result = self._load_cached_result(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for: {query}")
            self.stats['cache_hits'] += 1
            self._cache[cache_key] = cached_result
            return cached_result
        
        # Build query parameters
        params = {
            'search': f'{search_field}:"{query}"',
            'limit': limit
        }
        
        url = f"{self.base_url}?{urlencode(params)}"
        
        # Perform request with retries
        response_data = await self._request_with_retry(url)
        
        if response_data is None:
            return None
        
        # Parse response
        result = self._parse_response(response_data, query)
        
        # Cache result
        if result:
            self._cache[cache_key] = result
            self._save_cached_result(cache_key, result)

        return result
    
    async def _request_with_retry(
        self,
        url: str
    ) -> Optional[Dict]:
        """
        Perform HTTP request with retry logic.
        
        Parameters
        ----------
        url : str
            Full URL to request
        
        Returns
        -------
        dict or None
            Response JSON data or None if failed
        """
        self.stats['total_requests'] += 1
        
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug(f"Requesting: {url} (attempt {attempt + 1})")
                    
                    response = await client.get(url)
                    
                    # Handle different status codes
                    if response.status_code == 200:
                        self.stats['successful_requests'] += 1
                        return response.json()
                    
                    elif response.status_code == 404:
                        # Not found - don't retry
                        logger.debug(f"Drug not found in OpenFDA: {url}")
                        self.stats['failed_requests'] += 1
                        return None
                    
                    elif response.status_code == 429:
                        # Rate limited - wait and retry
                        self.stats['rate_limits'] += 1
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(
                            f"Rate limited by OpenFDA. Waiting {wait_time}s before retry..."
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    
                    else:
                        # Other error - retry
                        logger.warning(
                            f"OpenFDA request failed with status {response.status_code}: {url}"
                        )
                        if attempt < self.max_retries:
                            await asyncio.sleep(1)
                            continue
                        else:
                            self.stats['failed_requests'] += 1
                            return None
            
            except httpx.TimeoutException:
                self.stats['timeouts'] += 1
                logger.warning(f"Timeout requesting OpenFDA (attempt {attempt + 1}): {url}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1)
                    continue
                else:
                    self.stats['failed_requests'] += 1
                    return None
            
            except Exception as e:
                logger.error(f"OpenFDA request error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1)
                    continue
                else:
                    self.stats['failed_requests'] += 1
                    return None
        
        return None
    
    def _parse_response(
        self,
        response_data: Dict,
        query: str
    ) -> Optional[Dict[str, str]]:
        """
        Parse OpenFDA API response and extract relevant fields.
        
        Parameters
        ----------
        response_data : dict
            Raw API response
        query : str
            Original query (for logging)
        
        Returns
        -------
        dict or None
            Parsed drug information
        """
        try:
            # Check if results exist
            if 'results' not in response_data or not response_data['results']:
                logger.debug(f"No results in OpenFDA response for: {query}")
                return None
            
            # Get first result
            result = response_data['results'][0]
            
            # Extract fields with fallback to "unread"
            def get_field(data: Dict, *keys: str) -> str:
                """Extract field from nested dict, return 'unread' if not found."""
                for key in keys:
                    if key in data:
                        value = data[key]
                        # Handle lists
                        if isinstance(value, list):
                            value = ' '.join(str(v) for v in value)
                        # Handle strings
                        value = str(value).strip()
                        if value:
                            return value
                return "unread"
            
            # Build result dictionary
            parsed = {
                'drug_name': query,
                'warnings': get_field(result, 'warnings', 'boxed_warning'),
                'precautions': get_field(result, 'precautions', 'general_precautions'),
                'adverse_reactions': get_field(result, 'adverse_reactions'),
                'indications_and_usage': get_field(result, 'indications_and_usage'),
                'purpose': get_field(result, 'purpose'),
                'active_ingredient': get_field(result, 'active_ingredient'),
            }
            
            # If we have at least one useful field, return result
            useful_fields = [
                parsed['warnings'],
                parsed['precautions'],
                parsed['adverse_reactions']
            ]
            
            if any(field != "unread" for field in useful_fields):
                logger.info(f"Found OpenFDA data for: {query}")
                return parsed
            else:
                logger.debug(f"OpenFDA result for '{query}' has no useful fields")
                return None
        
        except Exception as e:
            logger.error(f"Error parsing OpenFDA response for '{query}': {e}")
            return None
    
    async def verify_medicine(
        self,
        query: str,
        search_field: str = "openfda.brand_name",
        limit: int = 1
    ) -> Optional[Dict[str, any]]:
        """Run a verification-only OpenFDA lookup for a medicine name."""
        return await self.search_drug(query, search_field=search_field, limit=limit)

    async def enrich_medicine(
        self,
        medicine: MedicineDetail,
        search_by_composition: bool = True
    ) -> MedicineDetail:
        """
        Enrich a MedicineDetail object with OpenFDA information.
        
        This method:
        1. Searches OpenFDA by medicine name (and optionally composition)
        2. Fills in safety information (warnings, precautions, adverse reactions)
        3. Sets found_in_openfda flag
        
        Parameters
        ----------
        medicine : MedicineDetail
            Medicine object to enrich
        search_by_composition : bool, optional
            If initial search fails, try searching by composition/generic name,
            by default True
        
        Returns
        -------
        MedicineDetail
            Enriched medicine object (modified in place and returned)
        
        Examples
        --------
        >>> client = OpenFDAClient()
        >>> med = MedicineDetail(medicine_name="Aspirin", dosage="500mg")
        >>> enriched = await client.enrich_medicine(med)
        >>> print(enriched.precautions)
        >>> print(enriched.found_in_openfda)
        True
        """
        # Verification call: check whether the drug exists in OpenFDA
        result = await self.verify_medicine(medicine.medicine_name, "openfda.brand_name")
        
        # If not found and composition is available, try generic name
        if result is None and search_by_composition:
            if medicine.composition != "unread":
                # Extract first ingredient from composition
                # e.g., "Amoxycillin (500mg) + Clavulanic Acid (125mg)" -> "Amoxycillin"
                generic = medicine.composition.split('(')[0].strip().split('+')[0].strip()
                
                if generic:
                    logger.debug(f"Searching OpenFDA by generic name: {generic}")
                    result = await self.verify_medicine(generic, "openfda.generic_name")
        
        # If still not found, return unchanged
        if result is None:
            logger.debug(f"No OpenFDA data found for: {medicine.medicine_name}")
            medicine.found_in_openfda = False
            return medicine
        
        # Enrich medicine with FDA data
        logger.info(f"Enriching '{medicine.medicine_name}' with OpenFDA data")
        
        # Enrichment action: merge safety information into the medicine record
        if medicine.precautions == "unread":
            medicine.precautions = result.get('precautions', 'unread')

        if medicine.precautions == "unread" and result.get('warnings', 'unread') != "unread":
            medicine.precautions = result['warnings']

        if medicine.side_effects == "unread" and result.get('adverse_reactions', 'unread') != "unread":
            medicine.side_effects = result['adverse_reactions']

        if medicine.purpose == 'unread' and result.get('purpose', 'unread') != 'unread':
            medicine.purpose = result['purpose']
        elif medicine.purpose == 'unread' and result.get('indications_and_usage', 'unread') != 'unread':
            medicine.purpose = result['indications_and_usage']

        if medicine.composition == 'unread' and result.get('active_ingredient', 'unread') != 'unread':
            medicine.composition = result['active_ingredient']

        medicine.found_in_openfda = True
        
        return medicine
    
    async def batch_search(
        self,
        queries: List[str]
    ) -> Dict[str, Optional[Dict]]:
        """
        Search for multiple drugs in batch.
        
        Parameters
        ----------
        queries : list[str]
            List of drug names to search
        
        Returns
        -------
        dict
            Mapping of query -> result (or None)
        
        Examples
        --------
        >>> client = OpenFDAClient()
        >>> results = await client.batch_search(["Aspirin", "Ibuprofen"])
        """
        tasks = [self.search_drug(query) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        output = {}
        for query, result in zip(queries, results):
            if isinstance(result, Exception):
                logger.error(f"Batch search error for '{query}': {result}")
                output[query] = None
            else:
                output[query] = result
        
        return output
    
    def get_statistics(self) -> Dict[str, any]:
        """
        Get client statistics.
        
        Returns
        -------
        dict
            Statistics about API usage
        """
        return {
            **self.stats,
            'cache_size': len(self._cache),
            'success_rate': (
                self.stats['successful_requests'] / self.stats['total_requests']
                if self.stats['total_requests'] > 0 else 0.0
            )
        }
    
    def clear_cache(self) -> None:
        """Clear the internal response cache."""
        self._cache.clear()
        for cache_path in self.cache_dir.glob('*.json'):
            cache_path.unlink(missing_ok=True)
        logger.info("OpenFDA cache cleared")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Global client instance (singleton pattern)
_global_client: Optional[OpenFDAClient] = None


def get_client() -> OpenFDAClient:
    """
    Get or create the global OpenFDAClient instance.
    
    Returns
    -------
    OpenFDAClient
        Global client instance
    """
    global _global_client
    
    if _global_client is None:
        _global_client = OpenFDAClient()
    
    return _global_client


async def quick_search(query: str) -> Optional[Dict[str, any]]:
    """
    Quick drug search using global client.
    
    Parameters
    ----------
    query : str
        Drug name to search
    
    Returns
    -------
    dict or None
        Drug information or None
    
    Examples
    --------
    >>> result = await quick_search("Aspirin")
    >>> if result:
    ...     print(result['warnings'])
    """
    client = get_client()
    return await client.search_drug(query)


async def quick_enrich(medicine: MedicineDetail) -> MedicineDetail:
    """
    Quick enrichment using global client.
    
    Parameters
    ----------
    medicine : MedicineDetail
        Medicine to enrich
    
    Returns
    -------
    MedicineDetail
        Enriched medicine
    
    Examples
    --------
    >>> med = MedicineDetail(medicine_name="Aspirin", dosage="500mg")
    >>> enriched = await quick_enrich(med)
    """
    client = get_client()
    return await client.enrich_medicine(medicine)


# =============================================================================
# DUAL-TIER VALIDATION ORCHESTRATOR
# =============================================================================

async def validate_and_enrich_medicine(
    medicine: MedicineDetail,
    local_matcher=None,
    fda_client: Optional[OpenFDAClient] = None,
    auto_correct_name: bool = True
) -> MedicineDetail:
    """
    Complete dual-tier validation: Local DB → OpenFDA → Safety fallback.
    
    This function orchestrates the complete validation pipeline:
    1. Try local database matching (RapidFuzz)
    2. If not found, try OpenFDA API
    3. If still not found, mark for human review and set safety defaults
    
    Parameters
    ----------
    medicine : MedicineDetail
        Medicine to validate and enrich
    local_matcher : MedicineMatcher, optional
        Local database matcher. If None, creates one.
    fda_client : OpenFDAClient, optional
        FDA API client. If None, creates one.
    auto_correct_name : bool, optional
        Whether to auto-correct medicine name from database, by default True
    
    Returns
    -------
    MedicineDetail
        Fully validated and enriched medicine
    
    Examples
    --------
    >>> med = MedicineDetail(medicine_name="Augmentin", dosage="625mg")
    >>> enriched = await validate_and_enrich_medicine(med)
    >>> print(f"Found in DB: {enriched.found_in_local_db}")
    >>> print(f"Found in FDA: {enriched.found_in_openfda}")
    >>> print(f"Needs review: {enriched.requires_human_review}")
    """
    # Import here to avoid circular dependency
    from .fuzzy_match import get_matcher as get_local_matcher
    
    # Get instances
    if local_matcher is None:
        local_matcher = get_local_matcher()
    
    if fda_client is None:
        fda_client = get_client()
    
    # Step 1: Try local database
    logger.info(f"Validating medicine: {medicine.medicine_name}")
    medicine = local_matcher.enrich_medicine(medicine, auto_correct_name)
    
    if medicine.found_in_local_db:
        logger.info(f"✓ Found in local database: {medicine.medicine_name}")
        return medicine
    
    # Step 2: Try OpenFDA
    logger.info(f"Not in local DB, trying OpenFDA: {medicine.medicine_name}")
    medicine = await fda_client.enrich_medicine(medicine)
    
    if medicine.found_in_openfda:
        logger.info(f"✓ Found in OpenFDA: {medicine.medicine_name}")
        return medicine
    
    # Step 3: Unidentified drug - apply safety rules
    logger.warning(
        f"⚠ UNIDENTIFIED DRUG: {medicine.medicine_name} not found in local DB or OpenFDA"
    )
    
    # CRITICAL SAFETY RULE: Preserve original name but mark metadata as unread
    # DO NOT discard the medicine name - it came from the prescription
    # Force all enriched fields to "unread" to prevent hallucinated medical data
    medicine.composition = "unread"
    medicine.uses = "unread"
    medicine.side_effects = "unread"
    medicine.precautions = "unread"
    medicine.manufacturer = "unread"
    
    # Set flags for human review
    medicine.low_confidence = True
    medicine.requires_human_review = True
    
    logger.warning(
        f"Set all metadata to 'unread' and flagged for human review: {medicine.medicine_name}"
    )
    
    return medicine