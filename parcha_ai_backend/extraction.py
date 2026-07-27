"""
Two-pass extraction engine for ParchaAI prescription analysis.

This module implements:
- Pass 1: Count medicines in prescription
- Pass 2: Extract structured data for each medicine
- Primary model: Google Gemini (gemini-3.1-flash-lite)
- Fallback model: Groq Vision (qwen/qwen3.6-27b)
- JSON caching by image hash
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from groq import AsyncGroq

try:
    from groq import RateLimitError, APIConnectionError, APIStatusError
except ImportError: 
    RateLimitError = APIConnectionError = APIStatusError = Exception

from .config import get_config
from .preprocessing import create_data_url, encode_image_to_base64, upscale_for_vlm
from .prompts import (
    build_fallback_verification_prompt,
    get_counting_prompt,
    get_extraction_prompt,
)

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Custom exception for extraction errors."""
    pass


_REASONING_TAG_PATTERN = re.compile(
    r"<(think|thinking|reasoning|analysis)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

_CODE_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*(.*?)```",
    re.IGNORECASE | re.DOTALL,
)


def _strip_reasoning_wrapper(text: str) -> str:
    cleaned = text

    cleaned = _REASONING_TAG_PATTERN.sub("", cleaned).strip()

    fence_match = _CODE_FENCE_PATTERN.search(cleaned)
    if fence_match:
        fenced_content = fence_match.group(1).strip()
        if fenced_content:
            return fenced_content
        
    if not cleaned.startswith("{") and not cleaned.startswith("["):
        brace_idx = cleaned.find("{")
        bracket_idx = cleaned.find("[")
        candidates = [i for i in (brace_idx, bracket_idx) if i != -1]
        if candidates:
            cleaned = cleaned[min(candidates):]

    return cleaned.strip()


class GeminiVisionExtractor:

    # Maps file extensions to the MIME types Gemini's inline_data expects.
    _MIME_TYPE_MAP = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'webp': 'image/webp',
    }
    _CACHE_SCHEMA_VERSION = "v2_reviewed_schedule_prompt"

    def __init__(self):
        """Initialize the vision extractor with the Gemini API key."""
        config = get_config()

        if not config.gemini_api_key:
            raise ExtractionError("GEMINI_API_KEY not configured")

        self.api_key = config.gemini_api_key
        self.api_base_url = config.gemini_api_url
        self.model = config.gemini_model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.max_retries = config.gemini_max_retries
        self.retry_base_delay = config.gemini_retry_base_delay
        self.timeout = 60.0

        self.cache_dir = config.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized GeminiVisionExtractor with model: {self.model}")

    def _get_mime_type(self, image_input) -> str:

        if not isinstance(image_input, (str, Path)):
            return 'image/png'
        extension = Path(image_input).suffix.lower().lstrip('.')
        return self._MIME_TYPE_MAP.get(extension, 'image/jpeg')

    def _compute_image_hash(self, image_path: Union[str, Path]) -> str:
        """
        Compute SHA256 hash of image file for cache key.

        Parameters
        ----------
        image_path : str or Path
            Path to image file

        Returns
        -------
        str
            SHA256 hash as hex string
        """
        with open(image_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _get_cache_path(self, image_hash: str, pass_number: int) -> Path:
        cache_filename = (
            f"{image_hash}_{self._CACHE_SCHEMA_VERSION}_pass{pass_number}.json"
        )
        return self.cache_dir / cache_filename

    def _load_from_cache(
        self,
        image_hash: str,
        pass_number: int
    ) -> Optional[Dict[str, Any]]:

        cache_path = self._get_cache_path(image_hash, pass_number)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"Loaded from cache: {cache_path.name}")
            return data

        except Exception as e:
            logger.warning(f"Failed to load cache {cache_path.name}: {e}")
            return None

    def _save_to_cache(
        self,
        image_hash: str,
        pass_number: int,
        response: str,
        elapsed: float
    ) -> None:

        cache_path = self._get_cache_path(image_hash, pass_number)

        try:
            cache_data = {
                'response': response,
                'elapsed': elapsed,
                'timestamp': time.time(),
                'model': self.model
            }

            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved to cache: {cache_path.name}")

        except Exception as e:
            logger.warning(f"Failed to save cache {cache_path.name}: {e}")

    async def _call_gemini_vision(
        self,
        image_input,
        prompt: str,
        temperature: float = 0.1,
        max_output_tokens: int = 2048
    ) -> Tuple[str, float]:

        start_time = time.time()
        last_error: Optional[Exception] = None

        image_b64 = encode_image_to_base64(image_input)
        mime_type = self._get_mime_type(image_input)

        url = f"{self.api_base_url}/{self.model}:generateContent"

        payload = {
            'contents': [
                {
                    'role': 'user',
                    'parts': [
                        {'text': prompt},
                        {
                            'inline_data': {
                                'mime_type': mime_type,
                                'data': image_b64
                            }
                        }
                    ]
                }
            ],
            'generationConfig': {
                'temperature': temperature,
                'maxOutputTokens': max_output_tokens
            }
        }
        headers = {
            'x-goog-api-key': self.api_key,
            'Content-Type': 'application/json'
        }

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()

                elapsed = time.time() - start_time

                candidates = data.get('candidates') or []
                if not candidates:
                    raise ExtractionError("Empty response from Gemini API")

                finish_reason = candidates[0].get('finishReason')
                parts = candidates[0].get('content', {}).get('parts', [])
                text_parts = [p['text'] for p in parts if 'text' in p]

                if not text_parts:
                    raise ExtractionError("No content in Gemini response")

                content = ''.join(text_parts)
                if finish_reason == 'MAX_TOKENS':
                    logger.warning(
                        f"Gemini response was TRUNCATED (finishReason=MAX_TOKENS, "
                        f"max_output_tokens={max_output_tokens}). Output is likely incomplete JSON."
                    )
                    truncated_error = ExtractionError("Response truncated at max_output_tokens")
                    truncated_error.truncated = True
                    truncated_error.partial_content = content.strip()
                    raise truncated_error

                logger.debug(f"Gemini API call completed in {elapsed:.2f}s (attempt {attempt + 1})")
                return content.strip(), elapsed

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                if status == 429:
                    retry_after = self._extract_retry_after(e.response)
                    delay = retry_after if retry_after is not None else self.retry_base_delay * (2 ** attempt)
                    logger.warning(
                        f"Gemini rate limit hit (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Waiting {delay:.1f}s before retrying."
                    )
                    if attempt < self.max_retries:
                        await asyncio.sleep(delay)
                        continue
                    break
                elif status >= 500:
                    delay = self.retry_base_delay * (2 ** attempt)
                    logger.warning(
                        f"Gemini server error {status} (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Retrying in {delay:.1f}s"
                    )
                    if attempt < self.max_retries:
                        await asyncio.sleep(delay)
                        continue
                    break
                else:
                    logger.error(f"Gemini API error: {status} - {e.response.text[:300]}")
                    raise ExtractionError(f"Failed to call Gemini Vision API: {e}")

            except httpx.TimeoutException as e:
                last_error = e
                delay = self.retry_base_delay * (2 ** attempt)
                logger.warning(
                    f"Gemini connection issue (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
                    continue
                break

            except ExtractionError:
                raise

            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                raise ExtractionError(f"Failed to call Gemini Vision API: {e}")

        logger.error(f"Gemini API call failed after {self.max_retries + 1} attempts: {last_error}")
        raise ExtractionError(
            f"Failed to call Gemini Vision API after {self.max_retries + 1} attempts "
            f"(likely rate-limit exhaustion): {last_error}"
        )

    @staticmethod
    def _extract_retry_after(response: httpx.Response) -> Optional[float]:
        try:
            if response is not None and 'retry-after' in response.headers:
                return float(response.headers['retry-after'])
        except (TypeError, ValueError):
            pass
        return None

    async def pass1_count_medicines(
        self,
        image_path: Union[str, Path]
    ) -> Tuple[int, float]:
        image_path = Path(image_path)
        image_hash = self._compute_image_hash(image_path)

        # Check cache
        cached = self._load_from_cache(image_hash, pass_number=1)
        if cached:
            # Parse count from cached response
            count = self._parse_count_from_response(cached['response'])
            return count, cached['elapsed']

        # Get prompt
        logger.info(f"Pass 1: Counting medicines in {image_path.name}")
        prompt = get_counting_prompt()

        # Call API
        response, elapsed = await self._call_gemini_vision(
            image_input=image_path,
            prompt=prompt,
            temperature=0.1,
            max_output_tokens=512
        )

        # Save to cache
        self._save_to_cache(image_hash, pass_number=1, response=response, elapsed=elapsed)

        # Parse count
        count = self._parse_count_from_response(response)

        logger.info(f"Pass 1 complete: Found {count} medicine(s) in {elapsed:.2f}s")
        return count, elapsed

    def _parse_count_from_response(self, response: str) -> int:

        patterns = [
            r'(?:count|total|number)[:\s]+(\d+)',
            r'(\d+)\s+(?:medicine|medication|drug|item)',
            r'\b(\d+)\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, response.lower())
            if match:
                count = int(match.group(1))
                if 0 <= count <= 50:  
                    return count

        numbers = re.findall(r'\d+', response)
        if numbers:
            count = int(numbers[0])
            if 0 <= count <= 50:
                return count

        logger.warning(f"Could not parse count from response: {response}")
        raise ExtractionError(f"Failed to parse medicine count from: {response[:100]}")

    async def pass2_extract_medicines(
        self,
        image_path: Union[str, Path],
        medicine_count: int
    ) -> Tuple[str, float]:
        image_path = Path(image_path)
        image_hash = self._compute_image_hash(image_path)

        # Check cache
        cached = self._load_from_cache(image_hash, pass_number=2)
        if cached:
            return cached['response'], cached['elapsed']

        # Preprocess (upscale small/blurry images before sending to the VLM)
        logger.info(f"Pass 2: Extracting {medicine_count} medicine(s) from {image_path.name}")
        preprocessed_image = upscale_for_vlm(image_path)

        # Get prompt
        prompt = get_extraction_prompt(medicine_count)

        pass2_max_tokens = self.max_tokens
        try:
            response, elapsed = await self._call_gemini_vision(
                image_input=preprocessed_image,
                prompt=prompt,
                temperature=0.1,
                max_output_tokens=pass2_max_tokens
            )
        except ExtractionError as e:
            if getattr(e, 'truncated', False):
                logger.warning(
                    f"Pass 2 truncated for {image_path.name}; retrying once "
                    f"with max_output_tokens=4096"
                )
                response, elapsed = await self._call_gemini_vision(
                    image_input=preprocessed_image,
                    prompt=prompt,
                    temperature=0.1,
                    max_output_tokens=4096
                )
            else:
                raise

        # Save to cache
        self._save_to_cache(image_hash, pass_number=2, response=response, elapsed=elapsed)

        logger.info(f"Pass 2 complete in {elapsed:.2f}s")
        return response, elapsed

    async def extract(
        self,
        image_path: Union[str, Path]
    ) -> Tuple[str, Dict[str, float]]:
        total_start = time.time()

        # Pass 1: Count
        count, pass1_time = await self.pass1_count_medicines(image_path)

        # Pass 2: Extract
        json_response, pass2_time = await self.pass2_extract_medicines(
            image_path,
            medicine_count=count
        )

        parsed_medicines = parse_json_response(json_response)
        if len(parsed_medicines) > count:
            logger.info(
                f"Pass 2 found {len(parsed_medicines)} medicine(s), more than "
                f"Pass 1's count of {count}. Keeping all of Pass 2's results "
                f"(Pass 1 is a guide, not a hard cap) to avoid dropping real "
                f"medicines and hurting recall."
            )

        total_time = time.time() - total_start

        timings = {
            'pass1': pass1_time,
            'pass2': pass2_time,
            'total': total_time
        }

        return json_response, timings


class GroqFallbackExtractor:

    def __init__(self):
        """Initialize Groq fallback extractor."""
        config = get_config()

        self.api_key = config.groq_api_key
        self.model = config.groq_model_name
        self.max_output_tokens = config.fallback_max_new_tokens
        self.temperature = config.fallback_temperature
        self.max_retries = config.groq_max_retries
        self.retry_base_delay = config.groq_retry_base_delay
        self.reasoning_effort = config.groq_reasoning_effort

        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None

        if not self.api_key:
            logger.warning("Groq fallback not configured (missing GROQ_API_KEY)")

        logger.info(
            f"Initialized GroqFallbackExtractor: {self.model} "
            f"(max_tokens={self.max_output_tokens}, reasoning_effort={self.reasoning_effort})"
        )

    async def _create_completion(
        self,
        prompt: str,
        image_data_url: str,
        use_reasoning_param: bool
    ):

        kwargs = dict(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url}
                        }
                    ]
                }
            ],
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
        )
        if use_reasoning_param:
            kwargs["reasoning_effort"] = self.reasoning_effort

        return await self.client.chat.completions.create(**kwargs)

    async def verify_extraction(
        self,
        image_path: Union[str, Path],
        medicine_count: int,
        previous_medicines: Optional[List[Dict[str, Any]]] = None,
        confidence_threshold: float = 0.85,
    ) -> Tuple[Optional[str], float]:
        """
        Verify/re-extract using Groq Vision.

        Parameters
        ----------
        image_path : str or Path
            Path to prescription image
        medicine_count : int
            Expected medicine count

        Returns
        -------
        tuple of (str or None, float)
            JSON response (or None if failed) and elapsed time
        """
        if not self.client:
            logger.warning("Groq fallback not configured, skipping")
            return None, 0.0

        logger.info(f"Calling Groq fallback for {Path(image_path).name}")

        if previous_medicines is not None:
            previous_json = json.dumps(
                {"medicines": previous_medicines}, ensure_ascii=False
            )
            prompt = build_fallback_verification_prompt(
                previous_json=previous_json,
                confidence_threshold=confidence_threshold,
            )
        else:
            prompt = get_extraction_prompt(medicine_count)
        prompt = (
            prompt
            + "\n\nIMPORTANT: After you finish reasoning, output ONLY the "
              "final JSON object as your very last content, with nothing "
              "after it -- no closing remarks, no explanation."
        )
        image_data_url = create_data_url(image_path)

        start_time = time.time()
        last_error: Optional[Exception] = None
        use_reasoning_param = True

        for attempt in range(self.max_retries + 1):
            try:
                try:
                    response = await self._create_completion(
                        prompt, image_data_url, use_reasoning_param
                    )
                except TypeError as e:
                    if use_reasoning_param:
                        logger.warning(
                            f"Groq SDK rejected 'reasoning_effort' param ({e}); "
                            f"retrying without it."
                        )
                        use_reasoning_param = False
                        response = await self._create_completion(
                            prompt, image_data_url, use_reasoning_param
                        )
                    else:
                        raise
                except APIStatusError as e:
                    if use_reasoning_param and getattr(e, "status_code", None) == 400:
                        logger.warning(
                            f"Groq API rejected 'reasoning_effort' param ({e}); "
                            f"retrying without it."
                        )
                        use_reasoning_param = False
                        response = await self._create_completion(
                            prompt, image_data_url, use_reasoning_param
                        )
                    else:
                        raise

                elapsed = time.time() - start_time

                if not response.choices:
                    logger.warning("Empty response from Groq fallback")
                    return None, elapsed

                message = response.choices[0].message
                content = getattr(message, "content", None)
                content_stripped = content.strip() if content else ""
                if not content_stripped:
                    reasoning_text = getattr(message, "reasoning", None)
                    if reasoning_text:
                        logger.warning(
                            "Groq fallback returned only reasoning text with "
                            "no final content -- likely ran out of tokens "
                            "before answering. Consider raising "
                            "FALLBACK_MAX_NEW_TOKENS further."
                        )
                    logger.warning("No usable content in Groq fallback response")
                    return None, elapsed

                logger.info(f"Groq fallback completed in {elapsed:.2f}s")
                return content_stripped, elapsed

            except RateLimitError as e:
                last_error = e
                retry_after = self._extract_retry_after(e)
                delay = retry_after if retry_after is not None else self.retry_base_delay * (2 ** attempt)
                logger.warning(
                    f"Groq fallback rate limit hit (attempt {attempt + 1}/{self.max_retries + 1}). "
                    f"Waiting {delay:.1f}s before retrying."
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
                    continue
                break

            except (APIConnectionError, httpx.TimeoutException) as e:
                last_error = e
                delay = self.retry_base_delay * (2 ** attempt)
                logger.warning(
                    f"Groq fallback connection issue (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
                    continue
                break

            except Exception as e:
                logger.error(f"Groq fallback error: {e}")
                return None, time.time() - start_time

        logger.error(f"Groq fallback call failed after {self.max_retries + 1} attempts: {last_error}")
        return None, time.time() - start_time

    @staticmethod
    def _extract_retry_after(error: Exception) -> Optional[float]:
        try:
            headers = getattr(getattr(error, 'response', None), 'headers', None)
            if headers and 'retry-after' in headers:
                return float(headers['retry-after'])
        except (TypeError, ValueError):
            pass
        return None


def parse_json_response(response: str) -> List[Dict[str, Any]]:

    cleaned = _strip_reasoning_wrapper(response.strip())

    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        if lines[0].strip() in ['```json', '```']:
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        cleaned = '\n'.join(lines).strip()

    # Try to parse JSON
    try:
        data = json.loads(cleaned)

        # Handle different response structures
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Check for common wrapper keys
            if 'medicines' in data:
                return data['medicines']
            elif 'extracted_medicines' in data:
                return data['extracted_medicines']
            elif 'data' in data:
                return data['data']
            else:
                # Single medicine object
                return [data]
        else:
            raise ExtractionError(f"Unexpected JSON type: {type(data)}")

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.debug(f"Raw response: {response[:500]}")
        recovered = _recover_partial_medicines(cleaned)
        if not recovered:
            recovered = _recover_partial_medicines(response.strip())

        if recovered:
            logger.warning(
                f"Recovered {len(recovered)} complete medicine object(s) "
                f"from an otherwise unparseable/truncated response."
            )
            return recovered

        raise ExtractionError(f"Failed to parse JSON: {e}")


def _recover_partial_medicines(text: str) -> List[Dict[str, Any]]:
    start = text.find('[')
    if start == -1:
        return []

    recovered: List[Dict[str, Any]] = []
    depth = 0
    obj_start: Optional[int] = None
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                candidate = text[obj_start:i + 1]
                try:
                    recovered.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass
                obj_start = None

    return recovered


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def extract_prescription(
    image_path: Union[str, Path]
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:

    extractor = GeminiVisionExtractor()
    json_response, timings = await extractor.extract(image_path)
    medicines = parse_json_response(json_response)
    return medicines, timings


async def extract_with_fallback(
    image_path: Union[str, Path],
    trigger_fallback: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:

    metadata = {'used_fallback': False, 'timings': {}}

    # Primary extraction (Gemini, two-pass)
    primary_extractor = GeminiVisionExtractor()
    json_response, timings = await primary_extractor.extract(image_path)

    metadata['timings']['primary'] = timings

    # If fallback not triggered, return primary result
    if not trigger_fallback:
        medicines = parse_json_response(json_response)
        return medicines, metadata

    # Try fallback (Groq, single call)
    fallback_extractor = GroqFallbackExtractor()
    count = len(parse_json_response(json_response))  # Use primary count

    fallback_response, fallback_time = await fallback_extractor.verify_extraction(
        image_path,
        medicine_count=count
    )

    metadata['timings']['fallback'] = fallback_time

    if fallback_response:
        metadata['used_fallback'] = True
        medicines = parse_json_response(fallback_response)
        logger.info("Using fallback extraction result")
    else:
        medicines = parse_json_response(json_response)
        logger.info("Fallback failed, using primary extraction result")

    return medicines, metadata