"""Safe Urdu medication-instruction generation for ParchaAI.

Every generated instruction follows a fixed, non-negotiable chronological
structure so patients always hear information in the same order:

    [Medicine Name] -> [Dosage] -> [Frequency & Timing] -> [Duration] -> [Safety Guardrail]

"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from groq import AsyncGroq

from .config import get_config
from .validation import MedicineDetail, PrescriptionResponse

logger = logging.getLogger(__name__)


class UrduExplanationError(Exception):
    """Raised when a safe Urdu instruction cannot be generated."""


# =============================================================================
# PROMPT TEMPLATE
# =============================================================================

URDU_INSTRUCTION_TEMPLATE = """آپ ایک پاکستانی مریض کے لیے ایک دوا کی محفوظ صوتی ہدایت لکھتے ہیں۔
صرف اردو رسم الخط میں لکھیں (رومن اردو، انگریزی، ہیڈنگ، مارک ڈاؤن یا بلٹ پوائنٹس بالکل استعمال نہ کریں)۔

آپ کو نیچے دیے گئے پانچ حصوں کی اسی ترتیب میں پابندی کرنی ہے۔ ترتیب بدلنا، کسی حصے کو
ملانا، چھوڑنا، یا اپنی طرف سے کوئی معلومات شامل کرنا سختی سے منع ہے:

1) اعلان (Announcement): دوا کا نام بتائیں: "{ordinal_phrase} {medicine_name} ہے۔"
2) مقدار (Dosage): بتائیں کتنی مقدار لینی ہے (مثلاً "ایک گولی"، "پانچ ملی لیٹر")۔
   Dosage فیلڈ: {dosage}
3) وقت اور تعدد (Frequency & Timing): بتائیں دن میں کتنی بار اور کب لینی ہے۔
   اگر Frequency فیلڈ میں "as needed" / "SOS" / "PRN" / "ضرورت" جیسا اشارہ ہو تو
   یہ حصہ یوں بیان کریں: "صرف ضرورت کے وقت لیں" اور اگر Purpose فیلڈ میں کوئی وجہ
   دی گئی ہو تو مختصراً وہ وجہ شامل کریں (مثلاً بخار ہونے کی صورت میں)۔
   Frequency فیلڈ: {frequency}
   Purpose فیلڈ (صرف حوالے کے لیے، الگ جملہ نہ بنائیں): {purpose}
4) دورانیہ (Duration): بتائیں کتنے دن یا ہفتے تک دوا جاری رکھنی ہے۔
   اگر Duration فیلڈ "unread" ہو یا خالی ہو تو یہ پورا جملہ بالکل شامل نہ کریں۔
   Duration فیلڈ: {duration}
5) حفاظتی ہدایت (Safety Guardrail): جملے کا اختتام بالکل اسی جملے پر کریں:
   "دوا لینے سے پہلے اپنے فارماسسٹ یا ڈاکٹر سے تصدیق کر لیں۔"

اصول:
- کل تین یا چار مختصر جملے بنائیں جو اوپر دی گئی ترتیب میں ہوں، نہ زیادہ نہ کم۔
- کوئی بھی خوراک، وقت، یا دورانیہ کا اندازہ نہ لگائیں -- صرف وہی معلومات بولیں جو
  اوپر فیلڈز میں دی گئی ہیں۔
- اردو کے مکمل رکے ہوئے وقفوں کے لیے "۔" استعمال کریں۔
- دوا کا نام بالکل یوں لکھیں: {urdu_pronunciation} — اسے تبدیل، ترجمہ یا دوبارہ ہجے نہ کریں۔

مثال کے طور پر ساخت کچھ یوں ہوگی (الفاظ نقل نہ کریں، صرف ترتیب کی مثال ہے):
"آپ کی پہلی دوا ازیتھرومائسن پانچ سو ملی گرام ہے۔ ایک گولی دن میں ایک بار صبح کھانے کے بعد لیں۔ یہ دوا پانچ دن تک جاری رکھیں۔ دوا لینے سے پہلے اپنے فارماسسٹ یا ڈاکٹر سے تصدیق کر لیں۔"
"""


@dataclass
class UrduPromptTemplate:
    """PromptTemplate-compatible formatter with an optional LangChain bridge."""

    template: str = URDU_INSTRUCTION_TEMPLATE
    input_variables: tuple = (
        "medicine_name", "dosage", "frequency", "duration", "purpose", "ordinal_phrase", "urdu_pronunciation"
    )

    def format(self, **kwargs) -> str:
        missing = [name for name in self.input_variables if name not in kwargs]
        if missing:
            raise UrduExplanationError(f"Missing template variables: {missing}")
        return self.template.format(**kwargs)

    def as_langchain(self):
        """Return a real LangChain PromptTemplate when LangChain is installed."""
        from langchain_core.prompts import PromptTemplate

        return PromptTemplate(
            template=self.template, input_variables=list(self.input_variables)
        )


class UrduExplainer:
    """Generate validated, structurally-consistent Urdu-script instructions with Groq."""

    DISCLAIMER = "دوا لینے سے پہلے اپنے فارماسسٹ یا ڈاکٹر سے تصدیق کر لیں۔"
    SAFE_FALLBACK = "اس دوا کی ہدایات کی تصدیق ضروری ہے۔"

    # Frequency-field keywords that indicate an "as needed" / PRN medicine.
    _PRN_KEYWORDS = ("sos", "prn", "as needed", "when needed", "ضرورت")

    def __init__(self, prompt_template: Optional[UrduPromptTemplate] = None):
        config = get_config()
        if not config.groq_api_key:
            raise UrduExplanationError("GROQ_API_KEY not configured")

        self.client = AsyncGroq(api_key=config.groq_api_key)
        self.model = config.urdu_model
        self.temperature = config.urdu_temperature
        self.max_tokens = config.urdu_max_tokens
        self.max_retries = config.groq_max_retries
        self.retry_base_delay = config.groq_retry_base_delay
        self.prompt_template = prompt_template or UrduPromptTemplate()

    async def _call_groq_text(self, prompt: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                content = response.choices[0].message.content if response.choices else None
                if not content:
                    raise UrduExplanationError("Empty Groq Urdu response")
                return content.strip()
            except Exception as exc:
                last_error = exc
                status = getattr(exc, "status_code", None)
                transient = status in {429, 500, 502, 503, 504} or status is None
                if attempt < self.max_retries and transient:
                    delay = self.retry_base_delay * (2 ** attempt)
                    logger.warning("Urdu generation retry %s in %.1fs: %s", attempt + 1, delay, exc)
                    await asyncio.sleep(delay)
                    continue
                break
        raise UrduExplanationError(f"Groq Urdu generation failed: {last_error}")

    @staticmethod
    def _is_urdu_script(text: str) -> bool:
        urdu_letters = re.findall(r"[\u0600-\u06FF]", text)
        all_letters = re.findall(r"[A-Za-z\u0600-\u06FF]", text)
        return len(urdu_letters) >= 12 and len(urdu_letters) / max(1, len(all_letters)) >= 0.85

    def _sanitize_urdu_text(self, text: str) -> str:
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"\s+", " ", text).strip(" \n-*#")
        if not self._is_urdu_script(text):
            raise UrduExplanationError("Model response was not usable Urdu script")
        if "فارماسسٹ" not in text and "ڈاکٹر" not in text:
            text = text.rstrip("۔. ") + "۔ " + self.DISCLAIMER
        return text

    @staticmethod
    def _ordinal_phrase(position: int) -> str:
        """
        Build the Urdu "your first medicine is / your next medicine is"
        announcement lead-in based on 0-indexed position in the prescription.

        Parameters
        ----------
        position : int
            0 for the first medicine in the prescription, 1+ for subsequent ones.
        """
        return "آپ کی پہلی دوا" if position == 0 else "آپ کی اگلی دوا"

    def is_prn(self, medicine: MedicineDetail) -> bool:
        """Detect 'as needed' / SOS / PRN medicines from the frequency field."""
        freq = (medicine.frequency or "").strip().lower()
        return any(keyword in freq for keyword in self._PRN_KEYWORDS)

    async def explain(self, medicine: MedicineDetail, position: int = 0) -> str:

        # Resolve pronunciation BEFORE LLM call (fixes inconsistent transliteration)
        from .pronunciation import resolve_pronunciation
        
        urdu_pronunciation = resolve_pronunciation(medicine.medicine_name)
        
        prompt = self.prompt_template.format(
            medicine_name=medicine.medicine_name,
            dosage=medicine.dosage,
            frequency=medicine.frequency,
            duration=medicine.duration,
            purpose=medicine.purpose,
            ordinal_phrase=self._ordinal_phrase(position),
            urdu_pronunciation=urdu_pronunciation, 
        )
        start = time.time()
        text = self._sanitize_urdu_text(await self._call_groq_text(prompt))
        logger.info("Generated Urdu explanation for '%s' in %.2fs", medicine.medicine_name, time.time() - start)
        return text

    async def explain_all(self, medicines: List[MedicineDetail]) -> List[str]:
        delay = get_config().inter_request_delay_seconds
        results: List[str] = []
        for index, medicine in enumerate(medicines):
            try:
                results.append(await self.explain(medicine, position=index))
            except UrduExplanationError as exc:
                logger.error("Urdu explanation failed for '%s': %s", medicine.medicine_name, exc)
                results.append(f"{self.SAFE_FALLBACK} {self.DISCLAIMER}")
            if delay and index < len(medicines) - 1:
                await asyncio.sleep(delay)
        return results

    async def explain_prescription(self, prescription: PrescriptionResponse) -> List[str]:
        return await self.explain_all(prescription.extracted_medicines)