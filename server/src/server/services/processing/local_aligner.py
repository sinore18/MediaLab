import logging
import re
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from server.domain.schemas import WordTiming
from server.services.processing.alignment_text import fill_unaligned, spoken_pieces

logger = logging.getLogger(__name__)

_ISO_639_3 = {
    "en": "eng", "hi": "hin", "bn": "ben", "gu": "guj", "kn": "kan",
    "ml": "mal", "mr": "mar", "pa": "pan", "ta": "tam", "te": "tel",
}


class LocalAlignmentError(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _load_alignment_components(device: str) -> tuple[Any, Any, Any, Any]:
    try:
        import torchaudio
        import uroman
    except ImportError as error:
        raise LocalAlignmentError(
            "Install the server dependencies to use torchaudio MMS_FA word alignment."
        ) from error

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).to(device)
    model.eval()
    return model, bundle.get_tokenizer(), bundle.get_aligner(), uroman.Uroman()


class LocalMMSWordAligner:
    def __init__(self, device: str = "cpu", language: str = "en") -> None:
        self.device = device
        self.language = language
        self._components: tuple[Any, Any, Any, Any] | None = None
        self._word_cache: dict[str, list[str]] = {}

    def warmup(self) -> None:
        """Load the model and run one tiny forward pass so the first real request is not slow.

        Call once at application startup (e.g. in the FastAPI lifespan, via run_in_threadpool).
        """
        import torch

        if self._components is None:
            self._components = _load_alignment_components(self.device)
        with torch.inference_mode():
            self._components[0](torch.zeros(1, 16000, device=self.device))

    def align(self, audio_path: Path, transcript: str) -> list[WordTiming]:
        if not transcript.strip():
            return []

        try:
            if self._components is None:
                self._components = _load_alignment_components(self.device)
            model, tokenizer, aligner, romanizer = self._components
            return self._align(audio_path, transcript, model, tokenizer, aligner, romanizer)
        except LocalAlignmentError:
            raise
        except Exception as error:
            raise LocalAlignmentError(f"torchaudio MMS_FA word alignment failed: {error}") from error

    def _romanize_word(self, word: str, romanizer: Any) -> list[str]:
        """Return the MMS_FA-compatible (a-z) words for one transcript word, expanding digits."""
        cached = self._word_cache.get(word)
        if cached is not None:
            return cached
        normalized: list[str] = []
        lcode = self._romanization_language()
        for piece in spoken_pieces(word, self.language):
            romanized = piece if piece.isascii() else romanizer.romanize_string(piece, lcode=lcode)
            normalized.extend(re.findall(r"[a-z]+(?:'[a-z]+)?", romanized.casefold()))
        if len(self._word_cache) > 10_000:
            self._word_cache.clear()
        self._word_cache[word] = normalized
        return normalized

    def _align(
        self,
        audio_path: Path,
        transcript: str,
        model: Any,
        tokenizer: Any,
        aligner: Any,
        romanizer: Any,
    ) -> list[WordTiming]:
        import torch
        import torchaudio

        original_words = transcript.split()
        normalized_words: list[str] = []
        word_indexes: list[int] = []
        unaligned: set[int] = set()  # words MMS_FA cannot place; their timing is interpolated
        for index, word in enumerate(original_words):
            romanized_words = self._romanize_word(word, romanizer)
            if not romanized_words:
                if any(unicodedata.category(character)[0] in {"L", "N"} for character in word):
                    unaligned.add(index)
                    logger.warning("MMS_FA cannot normalize transcript word %r; interpolating its timing.", word)
                continue  # punctuation-only words are skipped, as before
            normalized_words.extend(romanized_words)
            word_indexes.extend([index] * len(romanized_words))

        if not normalized_words:
            raise LocalAlignmentError("The transcript contains no words supported by MMS_FA.")

        bundle = torchaudio.pipelines.MMS_FA
        try:
            decoded_audio = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(audio_path),
                    "-f",
                    "f32le",
                    "-acodec",
                    "pcm_f32le",
                    "-ac",
                    "1",
                    "-ar",
                    str(bundle.sample_rate),
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as error:
            raise LocalAlignmentError("FFmpeg is required to decode audio for MMS_FA alignment.") from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode("utf-8", errors="replace").strip()
            reason = f" {detail}" if detail else ""
            raise LocalAlignmentError(f"FFmpeg could not decode audio for MMS_FA alignment.{reason}") from error
        if not decoded_audio.stdout:
            raise LocalAlignmentError("The audio file contains no samples to align.")

        waveform = torch.frombuffer(bytearray(decoded_audio.stdout), dtype=torch.float32).unsqueeze(0)
        if waveform.ndim != 2 or waveform.size(1) == 0:
            raise LocalAlignmentError("The audio file contains no samples to align.")
        waveform = waveform.to(self.device)

        tokens = tokenizer(normalized_words)
        if len(tokens) != len(normalized_words) or any(not word_tokens for word_tokens in tokens):
            raise LocalAlignmentError("MMS_FA could not tokenize every transcript word.")

        with torch.inference_mode():
            emission, _ = model(waveform)
        token_spans = aligner(emission[0], tokens)
        if len(token_spans) != len(normalized_words):
            raise LocalAlignmentError("MMS_FA returned an unexpected number of word alignments.")

        audio_seconds = waveform.size(1) / bundle.sample_rate
        frame_duration = audio_seconds / emission.size(1)
        word_frames: dict[int, tuple[int, int]] = {}
        for index, spans in zip(word_indexes, token_spans, strict=True):
            if not spans:
                continue
            start_frame = min(span.start for span in spans)
            end_frame = max(span.end for span in spans)
            previous = word_frames.get(index)
            if previous:
                word_frames[index] = (min(previous[0], start_frame), max(previous[1], end_frame))
            else:
                word_frames[index] = (start_frame, end_frame)

        # A spoken word must never silently disappear (it would escape redaction): anything the
        # aligner left without a usable timing is interpolated and flagged approximate.
        aligned: dict[int, tuple[float, float]] = {}
        for index in set(word_indexes):
            frames = word_frames.get(index)
            if frames is not None and frames[1] > frames[0]:
                aligned[index] = (frames[0] * frame_duration, frames[1] * frame_duration)
            else:
                unaligned.add(index)
                logger.warning("MMS_FA returned no usable timing for %r; interpolating.", original_words[index])
        if not aligned:
            raise LocalAlignmentError("MMS_FA did not return any word-level timestamps.")
        filled = fill_unaligned(aligned, unaligned, audio_seconds)

        timings: list[WordTiming] = []
        for index, word in enumerate(original_words):
            span = aligned.get(index)
            approximate = False
            if span is None:
                span = filled.get(index)
                approximate = True
            if span is None:
                continue  # punctuation-only word
            timings.append(
                WordTiming(
                    word=word,
                    start_seconds=span[0],
                    end_seconds=span[1],
                    approximate=approximate,  # add `approximate: bool = False` to WordTiming
                )
            )
        return timings

    def _romanization_language(self) -> str | None:
        language = self.language.strip().lower().replace("_", "-")
        base_language = language.split("-", 1)[0]
        if base_language in _ISO_639_3:
            return _ISO_639_3[base_language]
        return base_language if len(base_language) == 3 else None