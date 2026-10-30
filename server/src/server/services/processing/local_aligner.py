import re
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from server.domain.schemas import WordTiming


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
        for index, word in enumerate(original_words):
            romanized = romanizer.romanize_string(word, lcode=self._romanization_language())
            romanized_words = re.findall(r"[a-z]+(?:'[a-z]+)?", romanized.casefold())
            if not romanized_words and any(unicodedata.category(character)[0] in {"L", "N"} for character in word):
                raise LocalAlignmentError(f"MMS_FA cannot normalize transcript word {word!r}.")
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

        frame_duration = waveform.size(1) / bundle.sample_rate / emission.size(1)
        timings: list[WordTiming] = []
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

        for index, word in enumerate(original_words):
            frame_range = word_frames.get(index)
            if frame_range is None:
                if index in word_indexes:
                    raise LocalAlignmentError(f"MMS_FA returned no timing for transcript word {word!r}.")
                continue
            start_frame, end_frame = frame_range
            if end_frame <= start_frame:
                continue
            timings.append(
                WordTiming(
                    word=word,
                    start_seconds=start_frame * frame_duration,
                    end_seconds=end_frame * frame_duration,
                )
            )

        if not timings:
            raise LocalAlignmentError("MMS_FA did not return any word-level timestamps.")
        return timings

    def _romanization_language(self) -> str | None:
        language = self.language.strip().lower().replace("_", "-")
        base_language = language.split("-", 1)[0]
        iso_639_3 = {"en": "eng", "hi": "hin"}
        if base_language in iso_639_3:
            return iso_639_3[base_language]
        return base_language if len(base_language) == 3 else None
