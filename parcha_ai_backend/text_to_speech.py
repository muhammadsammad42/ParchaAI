
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


class TTSError(Exception):
    """Raised when audio synthesis fails on all available backends."""
    pass


def sanitize_filename(name: str, max_length: int = 60) -> str:
    """
    Turn an arbitrary string (medicine name, prescription id) into a
    filesystem-safe filename stem.

    Parameters
    ----------
    name : str
    max_length : int, optional

    Returns
    -------
    str
    """
    name = name.strip().lower()
    name = re.sub(r"[^\w\-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return (name or "audio")[:max_length]


def prepare_urdu_for_tts(text: str) -> str:
    """Normalize Urdu text into short, pause-friendly speech sentences.

    gTTS pronounces Urdu best when it receives native Urdu script with clear
    punctuation.  This deliberately does not attempt unsafe transliteration
    of medicine names; the Urdu generator is responsible for that.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("...", "۔").replace("!", "۔").replace("?", "؟")
    text = re.sub(r"\s*[,،]\s*", "، ", text)
    text = re.sub(r"\s*[.۔]\s*", "۔ ", text)
    return text.strip()


class TextToSpeechEngine:
    """
    Generates Urdu audio from text.

    Primary backend: gTTS (Google TTS, free, requires internet).
    Fallback backend: Coqui TTS (offline), used only if gTTS raises
    and a Coqui model is available in the environment.
    """

    def __init__(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        lang: str = "ur",
        use_coqui_fallback: bool = True,
    ):
        # Lazy-imported below so this module can be imported even if
        # gTTS/Coqui aren't installed yet (e.g. while wiring up config).
        try:
            from .config import get_config
            config = get_config()
            self.output_dir = Path(output_dir) if output_dir else config.outputs_dir / "audio"
        except Exception:
            # Fallback for standalone use outside the package.
            self.output_dir = Path(output_dir) if output_dir else Path("./outputs/audio")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lang = lang
        self.use_coqui_fallback = use_coqui_fallback
        try:
            from .config import get_config
            self.slow = get_config().urdu_tts_slow
        except Exception:
            self.slow = False
        self._coqui_model = None  # lazy-loaded on first fallback use

        logger.info(f"Initialized TextToSpeechEngine (lang={lang}, output_dir={self.output_dir})")

    # -------------------------------------------------------------------
    # PRIMARY: gTTS
    # -------------------------------------------------------------------
    def _synthesize_gtts(self, text: str, output_path: Path) -> Path:
        from gtts import gTTS  # local import: keeps module importable without gTTS installed

        tts = gTTS(text=text, lang=self.lang, slow=self.slow)
        tts.save(str(output_path))
        if not output_path.exists() or output_path.stat().st_size < 512:
            raise TTSError("gTTS returned an empty or invalid audio file")
        return output_path

    # -------------------------------------------------------------------
    # FALLBACK: Coqui TTS (offline)
    # -------------------------------------------------------------------
    def _synthesize_coqui(self, text: str, output_path: Path) -> Path:

        from TTS.api import TTS  

        if self._coqui_model is None:
            import os
            model_name = os.getenv("COQUI_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
            logger.info(f"Loading Coqui TTS fallback model: {model_name}")
            self._coqui_model = TTS(model_name)

        wav_path = output_path.with_suffix(".coqui.wav")
        self._coqui_model.tts_to_file(text=text, file_path=str(wav_path))
        try:
            from pydub import AudioSegment
            AudioSegment.from_wav(str(wav_path)).export(str(output_path), format="mp3")
        except Exception as exc:
            raise TTSError(f"Could not convert Coqui WAV to MP3: {exc}") from exc
        finally:
            if wav_path.exists():
                wav_path.unlink()
        if not output_path.exists() or output_path.stat().st_size < 512:
            raise TTSError("Coqui produced an empty audio file")
        return output_path

    # -------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------
    def synthesize(self, text: str, filename_stem: str) -> Path:
        """
        Synthesize one piece of text to an .mp3 file, trying gTTS first
        and falling back to Coqui TTS if gTTS fails.

        Parameters
        ----------
        text : str
            Urdu text to speak.
        filename_stem : str
            Used to name the output file (sanitized automatically).

        Returns
        -------
        Path
            Path to the generated .mp3 file.
        """
        text = prepare_urdu_for_tts(text)
        if not text:
            raise TTSError("Cannot synthesize empty text")

        stem = sanitize_filename(filename_stem)
        output_path = self.output_dir / f"{stem}.mp3"

        start = time.time()
        try:
            self._synthesize_gtts(text, output_path)
            logger.info(f"gTTS synthesized '{output_path.name}' in {time.time() - start:.2f}s")
            return output_path
        except Exception as gtts_error:
            logger.warning(f"gTTS failed for '{stem}': {gtts_error}")

            if not self.use_coqui_fallback:
                raise TTSError(f"gTTS failed and Coqui fallback disabled: {gtts_error}")

            try:
                self._synthesize_coqui(text, output_path)
                logger.info(f"Coqui TTS (fallback) synthesized '{output_path.name}'")
                return output_path
            except Exception as coqui_error:
                raise TTSError(
                    f"Both TTS backends failed. gTTS: {gtts_error} | Coqui: {coqui_error}"
                )

    def synthesize_batch(
        self,
        texts: List[str],
        filename_stems: List[str],
    ) -> List[Optional[Path]]:

        if len(texts) != len(filename_stems):
            raise ValueError("texts and filename_stems must be the same length")

        results: List[Optional[Path]] = []
        for text, stem in zip(texts, filename_stems):
            try:
                results.append(self.synthesize(text, stem))
            except TTSError as e:
                logger.error(f"Failed to synthesize audio for '{stem}': {e}")
                results.append(None)
        return results

    def combine_audio(self, mp3_paths: List[Path], output_stem: str) -> Optional[Path]:

        valid_paths = [p for p in mp3_paths if p is not None]
        if not valid_paths:
            return None

        try:
            from pydub import AudioSegment
        except ImportError:
            logger.warning("pydub not installed; skipping combined audio file (per-medicine .mp3s still saved)")
            return None

        try:
            combined = AudioSegment.empty()
            pause = AudioSegment.silent(duration=700)  # 0.7s gap between medicines
            for i, path in enumerate(valid_paths):
                combined += AudioSegment.from_mp3(str(path))
                if i < len(valid_paths) - 1:
                    combined += pause

            output_path = self.output_dir / f"{sanitize_filename(output_stem)}_full.mp3"
            combined.export(str(output_path), format="mp3")
            logger.info(f"Combined {len(valid_paths)} clips into {output_path.name}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to combine audio: {e}")
            return None
