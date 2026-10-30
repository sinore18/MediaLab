
# Bleeper API

FastAPI service for video uploads, cleanup processing, and audio transcription.

## Audio transcription

`POST /api/v1/transcriptions` accepts an audio file as multipart field `file` and returns the transcript, media duration, and word-level start/end times. It uses the configured Gnani-compatible STT provider (`STT_PROVIDER=gnani`, or the existing `vachana` alias) with `language_code=indic-auto` for automatic language detection, followed by torchaudio MMS_FA alignment. This endpoint omits the video-cleanup pipeline's domain-specific substitutions and bias terms to keep transcripts verbatim. It accepts audio up to `MAX_UPLOAD_SIZE_MB` (100 MB by default) and `MAX_AUDIO_DURATION_SECONDS` (30 seconds by default). It requires `STT_API_KEY`, FFmpeg/ffprobe, and the alignment model dependencies. Audio is staged temporarily on the API host and removed after processing.

## Run locally

From `server/`, run `uv run server` to start the API at `http://localhost:8000`. API docs are at `/docs`.

The root `.env` is loaded by the server. Video uploads use the same multipart API flow in every environment: the API validates the file, extracts audio with FFmpeg, sends the audio to Vachana STT for transcription using model `prisma-v3.0`, aligns the transcript with torchaudio MMS_FA on a second pass over the audio, asks Gemini to identify profanities in the transcript, renders a cleaned MP4, and returns that output. `PROD` only changes logging levels; it does not switch storage or processing architecture. Audio is sent to `https://api.vachana.ai/stt/v3`; configure `STT_API_KEY` with the Vachana API key ID and `STT_LANGUAGE_CODE` (defaults to `hi-IN`). Set `GEMINI_API_KEY` to a Google AI Studio API key; `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`. Gemini receives the aligned transcript tokens and returns standardized `profanity_spans` entries with inclusive `start_index` and `end_index` token indexes plus `type: "word"` or `"phrase"`. Single-word profanities are bleeped for that word's timing; phrase entries bleep continuously from the first token through the last, including the phrase's inter-word gaps. Gemini considers context and local-language expressions, and normal surrounding words are not included. `STT_PROVIDER` defaults to `vachana`; `gnani` is accepted as an alias for the Vachana endpoint, and `local` or `whisper` selects local Whisper transcription instead. The first alignment request downloads the MMS_FA model and caches it locally, so the API host needs internet access once. Install FFmpeg (including `ffprobe`) on the API host. Set `LOCAL_ALIGNMENT_DEVICE` to select the MMS_FA inference device; Hindi transcripts are romanized with uroman before alignment. Set `LOCAL_STT_MODEL`, `LOCAL_STT_DEVICE`, and `LOCAL_STT_LANGUAGE` to configure local Whisper transcription. The Vachana response `timestamp` is request metadata and is ignored; word timing comes from the MMS_FA alignment stage. In production, the API still stages uploads and outputs on its local filesystem and returns the processed video directly to the client.

## Processing architecture

`ProcessingPipeline` separates transcription, word alignment, profanity detection, and bleep rendering. Vachana provides the transcript by default; torchaudio MMS_FA aligns that text against a second pass over the audio to produce word-level times. Gemini returns structured word or phrase profanity spans with inclusive transcript token indexes; the pipeline maps each entry to its MMS_FA timing interval, and FFmpeg replaces each complete interval with a tone while preserving the original video. This requires network access and a valid `GEMINI_API_KEY`. MMS_FA weights are cached by PyTorch under the user's model cache. CPU is the default alignment device. The MMS_FA checkpoint is licensed CC-BY-NC 4.0; commercial use requires appropriate permission.

Extracted WAV files are retained in `server/audio/` with unique filenames. Processing stage start/completion messages are written to the console and `server/logs/server.log` as each stage runs. The exact transcript returned by the configured STT provider is logged as a JSON-escaped string.

The renderer should preserve non-profane audio, replace matched spans with the configured bleep sample, and mux the result with the original video.

Run the focused API tests with `uv run pytest`.
