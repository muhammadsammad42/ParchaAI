
"""
Text-to-speech generation for ParchaAI (Week 3).

Converts Urdu instruction text (from urdu_explanation.py) into .mp3
audio using gTTS (lang='ur'), with an offline Coqui TTS fallback hook
for when gTTS is unreachable (no internet on-device, quota, etc.),
matching the Week 3 plan's "gTTS + Coqui fallback" deliverable.

Drop this file into the `parcha_ai` package next to preprocessing.py.

Usage
-----
    >>> from parcha_ai.text_to_speech import TextToSpeechEngine
    >>> engine = TextToSpeechEngine()
    >>> mp3_path = engine.synthesize("یہ دوا کھانے کے بعد لیں۔", "augmentin_01")
"""

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
        """
        Offline fallback. Coqui TTS does not ship an official Urdu model
        out of the box, so this is a best-effort hook: point
        COQUI_MODEL_NAME at any multilingual/Urdu-capable checkpoint you
        have available. If unavailable, this raises and the caller
        should treat the medicine as "audio unavailable" rather than
        silently producing wrong-language audio.
        """
        from TTS.api import TTS  # local import: optional heavy dependency

        if self._coqui_model is None:
            import os
            model_name = os.getenv("COQUI_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
            logger.info(f"Loading Coqui TTS fallback model: {model_name}")
            self._coqui_model = TTS(model_name)

        # Coqui writes WAV natively. Export through pydub so a file named
        # .mp3 is genuinely MP3 rather than WAV bytes with the wrong suffix.
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

        Raises
        ------
        TTSError
            If both backends fail.
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
        """
        Synthesize multiple texts. Failures are logged and returned as
        None at that index rather than aborting the whole batch, so one
        bad medicine doesn't take down the rest of the prescription's
        audio.

        Parameters
        ----------
        texts : list of str
        filename_stems : list of str
            Must be the same length as `texts`.

        Returns
        -------
        list of (Path or None)
        """
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
        """
        Concatenate several per-medicine .mp3 files into one
        per-prescription audio file, so a patient with 4 medicines gets
        a single voice note instead of 4. Requires pydub + ffmpeg.

        Returns None (and logs) if pydub/ffmpeg aren't available rather
        than raising, since per-medicine files are still usable on their
        own.
        """
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
