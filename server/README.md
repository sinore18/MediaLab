
# Bleeper API

FastAPI service for video uploads, cleanup processing, and audio transcription.

## Audio transcription

`POST /api/v1/transcriptions` accepts an audio file as multipart field `file` and returns the transcript, media duration, and word-level start/end times. It uses the configured Gnani-compatible STT provider (`STT_PROVIDER=gnani`, or the existing `vachana` alias) with `language_code=indic-auto` for automatic language detection, followed by torchaudio MMS_FA alignment. This endpoint omits the video-cleanup pipeline's domain-specific substitutions and bias terms to keep transcripts verbatim. It accepts audio up to `MAX_UPLOAD_SIZE_MB` (100 MB by default) and `MAX_AUDIO_DURATION_SECONDS` (30 seconds by default). It requires `STT_API_KEY`, FFmpeg/ffprobe, and the alignment model dependencies. Audio is staged temporarily on the API host and removed after processing.

## Spoken PII redaction

`POST /api/v1/pii-redactions` accepts an audio upload as multipart field `file`.

## Run locally

From `server/`, run `uv run server` to start the API at `http://localhost:8000`. API docs are at `/docs`.

The root `.env` is loaded by the server. Video uploads use the same multipart API flow in every environment: the API validates the file, extracts audio with FFmpeg, sends the audio to Vachana STT for transcription using model `prisma-v3.0`, aligns the transcript with torchaudio MMS_FA on a second pass over the audio, asks Gemini to identify profanities in the transcript, renders a cleaned MP4, and returns that output. `PROD` only changes logging levels; it does not switch storage or processing architecture. Audio is sent to `https://api.vachana.ai/stt/v3`; configure `STT_API_KEY` with the Vachana API key ID and `STT_LANGUAGE_CODE` (defaults to `hi-IN`). Set `GEMINI_API_KEY` to a Google AI Studio API key; `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`. Gemini receives the aligned transcript tokens and returns standardized `profanity_spans` entries with inclusive `start_index` and `end_index` token indexes plus `type: "word"` or `"phrase"`. Single-word profanities are bleeped for that word's timing; phrase entries bleep continuously from the first token through the last, including the phrase's inter-word gaps. Gemini considers context and local-language expressions, and normal surrounding words are not included. `STT_PROVIDER` defaults to `vachana`; `gnani` is accepted as an alias for the Vachana endpoint, and `local` or `whisper` selects local Whisper transcription instead. The first alignment request downloads the MMS_FA model and caches it locally, so the API host needs internet access once. Install FFmpeg (including `ffprobe`) on the API host. Set `LOCAL_ALIGNMENT_DEVICE` to select the MMS_FA inference device; Hindi transcripts are romanized with uroman before alignment. Set `LOCAL_STT_MODEL`, `LOCAL_STT_DEVICE`, and `LOCAL_STT_LANGUAGE` to configure local Whisper transcription. The Vachana response `timestamp` is request metadata and is ignored; word timing comes from the MMS_FA alignment stage. In production, the API still stages uploads and outputs on its local filesystem and returns the processed video directly to the client.

## Processing architecture

`ProcessingPipeline` separates transcription, word alignment, profanity detection, and bleep rendering. Detector plugins implement `detect` over aligned words (`word`, `start`, `end`, and optional `conf`) and return categorized spans with inclusive word indexes, times, and optional confidence. `GeminiProfanityDetector` implements this contract; its existing `find_matches` method remains available for compatibility. Vachana provides the transcript by default; torchaudio MMS_FA aligns that text against a second pass over the audio to produce word-level times. Gemini returns structured word or phrase profanity spans with inclusive transcript token indexes; the pipeline maps each entry to its MMS_FA timing interval, and FFmpeg replaces each complete interval with a tone while preserving the original video. This requires network access and a valid `GEMINI_API_KEY`. MMS_FA weights are cached by PyTorch under the user's model cache. CPU is the default alignment device. The MMS_FA checkpoint is licensed CC-BY-NC 4.0; commercial use requires appropriate permission.

Spoken-number normalization operates on raw aligned tokens and retains the originating word index for each output digit or letter. It currently recognizes English/Hinglish digit names, common Devanagari digit words and numerals, `double`/`triple` repetition, and spelled letters such as “A for Apple.”

The PII detector is a separate `DetectorPlugin`. It checks card candidates with Luhn, Aadhaar-shaped candidates with Verhoeff, and PAN, IFSC, and Indian mobile candidates with their structural validators. OTP-shaped sequences require a nearby code, OTP, PIN, password, or verification cue. Short pauses are kept within a digit run; long pauses split runs, and “no wait” / correction cues replace the preceding spoken digit.

The existing `FfmpegBleepRenderer` also exposes audio-only PII redaction. Its `render_audio` method defaults to beep mode, an 80 ms margin on both sides, a 150 ms merge gap, and 5 ms fades; callers can select silence mode and override those settings.

`POST /api/v1/pii-redactions` accepts an audio file in multipart field `file` and returns a ZIP containing `redacted_audio.wav`, `redacted_transcript.txt`, and `audit.json`. The transcript replaces detected spans with category tags. The audit stores span metadata and the SHA-256 digest of the original upload, not the detected values. Temporary inputs and outputs are removed after the response is sent, and this route disables raw transcript logging.

After rendering, the endpoint re-transcribes the redacted audio with the same STT provider and realigns/rechecks it. It logs category/time-only leaked detections, `pii_recall` (the fraction of initially detected spans not detected again), and `seconds_over_redacted` (redacted duration outside the union of detected PII spans). These verification metrics are also included in `audit.json`; raw PII values are not logged or audited.

Extracted WAV files are retained in `server/audio/` with unique filenames. Processing stage start/completion messages are written to the console and `server/logs/server.log` as each stage runs. The exact transcript returned by the configured STT provider is logged as a JSON-escaped string.

The renderer should preserve non-profane audio, replace matched spans with the configured bleep sample, and mux the result with the original video.

Run the focused API tests with `uv run pytest`.

Run the end-to-end redaction command from `server/`:

```powershell
uv run pii-redact call.wav --output-dir redacted-call --mode beep --margin-ms 80
```

The command uses the configured STT provider and environment variables, then writes `redacted_audio.wav`, `redacted_transcript.txt`, and `audit.json` into the output directory. `--mode` accepts `beep` or `silence`; `--margin-ms` configures padding on both sides of each detection. The command reverifies the result with the same STT provider and reports leaks, PII recall, and over-redacted seconds. Tests use synthetic number strings only.
