# Bleeper

Video profanity-cleanup starter with a Next.js client and a Python/FastAPI API.

## Start locally

1. Leave `PROD=false` in the root `.env` for local testing. This mode sends the selected video to the local API, validates its size and duration, returns it to the browser for preview, and does not call Azure.
2. Install FFmpeg so `ffprobe` is available on `PATH`.
3. In one terminal, run `cd server` and `uv run server`.
4. In another terminal, run `cd client` and `npm run dev`.
5. Open `http://localhost:3000`.

The audio workspace is available at `http://localhost:3000/transcribe`. It supports microphone recording and audio uploads, then sends the audio to the configured Gnani-compatible STT provider and torchaudio MMS_FA aligner via `POST /api/v1/transcriptions`. Select Hindi or English in the workspace so Gnani and the aligner use the same language; verbatim transcription omits the video-cleanup pipeline's custom substitutions and keyword bias. Configure `STT_PROVIDER=gnani`, `STT_API_KEY`, and `STT_LANGUAGE_CODE` in the root `.env`; FFmpeg/ffprobe and the MMS_FA model dependencies must be available to the API.

Set `PROD=true` to switch to Azure Blob SAS uploads. Configure the Azure account credentials in `.env`, and allow browser `PUT` from `http://localhost:3000` in Blob Storage CORS with the `x-ms-blob-type` and `content-type` headers. Restart both dev servers after changing `PROD` so the API setting and public client mode flag are refreshed.

## Run with Docker Compose

Copy `.env.example` to `.env` and set the required API credentials. Build the server runtime once on the VM; it contains the OS packages and Python dependencies:

```bash
docker compose --profile runtime-build build server-runtime
```

Build and start the application images:

```bash
docker compose build
docker compose up -d
```

For later server code changes, rebuild only the small server image and recreate that service; the runtime image and installed dependencies are reused:

```bash
docker compose build server
docker compose up -d server
```

If `pyproject.toml` or `uv.lock` changes, rebuild the runtime first, then rebuild the server:

```bash
docker compose --profile runtime-build build server-runtime
docker compose build server
docker compose up -d server
```

Open `http://localhost:3000`; the API is available at `http://localhost:8000`. The client image uses Next.js standalone output, and the server runtime includes FFmpeg/ffprobe. Audio, logs, and the downloaded PyTorch alignment model are stored in Compose-managed volumes. Set `NEXT_PUBLIC_API_BASE_URL` in the root `.env` to the browser-accessible API URL before building if it is not `http://localhost:8000/api/v1`.

The Compose services are capped at a combined 1 vCPU and 512 MB RAM: the API gets 0.75 CPU / 384 MB and the client gets 0.25 CPU / 128 MB. These are strict container limits, not recommendations for reliable transcription. The API loads the torchaudio MMS_FA alignment model in memory, so transcription may be slow or the API may be killed for exceeding its memory limit. Increase the API memory allocation (and the overall VPS memory) if that occurs. Image builds are not subject to these runtime container limits.

## Processing status

Local mode transcribes audio, aligns the transcript with torchaudio MMS_FA for word-level timestamps, asks Gemini to identify profanity in any language, and bleeps the corresponding word or complete multi-word phrase. Gemini returns a standardized JSON object containing `profanity_spans` with inclusive token indexes and a `word` or `phrase` type. Configure `GEMINI_API_KEY` in the root `.env` (the default model is `gemini-3.5-flash-lite`). Keep Azure credentials server-only; only the non-secret production mode flag is exposed to the client.

Run API tests with `cd server && uv run pytest`. Run client checks with `cd client && npm run lint && npm run build`.