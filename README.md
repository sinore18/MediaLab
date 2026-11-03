# Spoken PII Redaction

Spoken account details are easy to overlook: a support call, voice note, or interview may contain a card number, an OTP, or another identifier even when the recording was never meant to disclose it. Sharing the original audio can expose that information, while manual review and editing are slow and difficult to audit.

This project turns spoken-PII cleanup into a repeatable workflow. Upload an audio recording and receive a version with detected identifiers replaced by beeps, a transcript with sensitive spans masked, and a metadata-only audit file. It is designed to help people review and minimize exposure before sharing recordings—not to guarantee that every sensitive detail has been found.

## What it does

The PII redaction workspace is available at https://redact.dhwani.site/. It accepts audio uploads and returns a ZIP containing:

- `redacted_audio.wav` — normalized audio with detected spans replaced by a tone.
- `redacted_transcript.txt` — aligned transcript with detections replaced by category tags such as `[CARD]` or `[OTP]`.
- `audit.json` — the original file's SHA-256 digest, detection categories and timestamps, and reverification metrics. Detected values are not included.

The detector currently targets:

| Category | Detection approach |
| --- | --- |
| Payment card | 13–19 spoken digits with a valid Luhn checksum |
| Aadhaar | 12-digit candidate with the expected first digit and valid Verhoeff checksum |
| Indian mobile | 10-digit candidate beginning with 6–9 |
| PAN | Indian PAN structural pattern |
| IFSC | Indian IFSC structural pattern |
| OTP | 4–8 digits near a cue such as “OTP”, “code”, “PIN”, “password”, or “verification” |

Spoken digit normalization includes English, common Hinglish, and Devanagari number words and numerals. It also handles common spoken-number repetition and correction patterns. These are targeted heuristics, not a general-purpose detector: names, addresses, email addresses, and arbitrary identifiers are not currently in scope. A checksum or format match does not establish that an identifier is real or belongs to anyone.

## How it works

```text
Browser
  └─ multipart audio upload
       └─ FastAPI validation and temporary workspace
            ├─ FFmpeg: normalize audio to mono 16 kHz WAV
            ├─ STT: Vachana/Gnani API or local Whisper
            ├─ torchaudio MMS_FA + uroman: word-level timings
            ├─ spoken-number normalization and PII validation
            ├─ FFmpeg: replace padded/merged PII intervals with beeps
            ├─ repeat STT, alignment, and detection on redacted audio
            └─ ZIP redacted audio, masked transcript, and audit metadata
```

The FastAPI endpoint uses STT with automatic Indic language detection (`indic-auto`) when using Vachana. The MMS_FA aligner is local; it aligns the transcript to audio so detected words can be redacted at their timestamps. Redactions include an 80 ms margin on either side by default, are clipped to the recording, and nearby intervals are merged.

Reverification measures whether the same detector finds initial detections again after redaction. `pii_recall` in the audit is the fraction of initial spans *not* detected again; `leaked_items` lists any remaining detections by category and time; `seconds_over_redacted` estimates redacted time outside the original detected spans. These are useful checks, not a proof of complete redaction: STT and detection can miss speech, and reverification uses the same pipeline.

## Privacy and operational considerations

- The PII route suppresses transcript logging and excludes detected source values from the transcript tags and audit. The audit still contains categories, timings, confidence/validator metadata, and the original audio's SHA-256 digest.
- Input, normalized audio, and intermediate outputs are staged in a temporary directory on the API host and removed after request completion. A forced process/host shutdown can leave temporary files behind; secure the host and its temporary storage accordingly.
- With `STT_PROVIDER=vachana` (or `gnani`), the audio is sent to the configured Vachana STT service for transcription. Review that provider's data handling and retention terms before uploading sensitive recordings. Use `STT_PROVIDER=local` to run Whisper locally instead; local models may be downloaded the first time they are used.
- The browser receives the ZIP and can preview/download its contents. Use HTTPS in production and limit access to the app/API if recordings are sensitive. This project does not provide user authentication, rate limiting, or a compliance certification.
- Set upload limits and host capacity deliberately. Audio is processed synchronously; long or concurrent jobs consume CPU, memory, temporary disk, and may require significant time. The default audio limit is 600 seconds and the default upload limit is 500 MB.

## Run locally

### Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm
- FFmpeg, including `ffprobe`, available on `PATH`
- An STT provider:
  - Vachana/Gnani API key ID (`STT_PROVIDER=vachana` and `STT_API_KEY`), or
  - Local Whisper (`STT_PROVIDER=local`; configure its model and language as needed)
- Network access on first use to fetch the MMS_FA alignment model (and local Whisper model if selected)

From the repository root, copy `.env.example` to `.env` and configure the provider. For example:

```dotenv
STT_PROVIDER=vachana
STT_API_KEY=your-vachana-api-key-id
STT_LANGUAGE_CODE=indic-auto
MAX_UPLOAD_SIZE_MB=100
MAX_AUDIO_DURATION_SECONDS=30
CORS_ORIGINS=
NEXT_PUBLIC_API_BASE_URL=
```

Keep `.env` out of version control and do not put provider secrets in `NEXT_PUBLIC_*` variables. For local Whisper instead, set `STT_PROVIDER=local`, remove the need for `STT_API_KEY`, and configure `LOCAL_STT_MODEL`, `LOCAL_STT_DEVICE`, and `LOCAL_STT_LANGUAGE`. The local aligner uses `LOCAL_ALIGNMENT_DEVICE` (CPU by default).

Start the API and web client in separate terminals:

```powershell
cd server
uv sync
uv run server
```

```powershell
cd client
npm ci
npm run dev
```

## Host with Docker Compose

The repository includes Dockerfiles for a Next.js standalone client and a FastAPI server. The server runtime image installs FFmpeg and the Python dependencies; Compose persists the Torch model cache in a named volume.

1. Install Docker Engine and the Docker Compose plugin on the host. Ensure the host has enough memory, CPU, and temporary disk for audio processing and the alignment model.
2. Create and configure the root `.env` as above. For an internet-facing deployment, set `CORS_ORIGINS` to the exact browser origin(s). Set `NEXT_PUBLIC_API_BASE_URL` to a URL the user's browser can reach; this value is embedded in the client at image build time.
3. Build the runtime image, then build and start the application:

   ```powershell
   docker compose --profile runtime-build build server-runtime
   docker compose build
   docker compose up -d
   ```

4. Verify `http://localhost:8000/health` and open `http://localhost:3000/bleeper/pii-redactions`.

The default Compose client API URL is `http://localhost:8000/api/v1`, suitable for local access. For a public site behind the included Caddy configuration, set the build-time browser URL to your HTTPS API path, for example:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://redact.dhwani.site/api/v1
CORS_ORIGINS=https://redact.dhwani.site
```

Then rebuild the client (`docker compose build client`) and recreate it (`docker compose up -d client`). The root `Caddyfile` serves `dhwani.site`, `redact.dhwani.site`, and `transcribe.dhwani.site`, routes `/api/*` to the API, and sends the other requests to the client. The PII subdomain redirects its root to `/bleeper/pii-redactions`. Replace these domains with yours; point DNS to the host, allow inbound ports 80/443, and configure Caddy to load the file. Caddy can provision HTTPS certificates automatically when DNS and ports are correct.

The Compose file publishes ports 3000 and 8000. In production, restrict direct access to those ports at the host firewall or bind them to loopback and expose only the reverse proxy. Keep API credentials in the server environment, not in client build arguments other than the public API URL.

For code-only server updates, rebuild and recreate just the server. If Python dependencies change, rebuild the runtime image first:

```powershell
docker compose build server
docker compose up -d server
```

```powershell
docker compose --profile runtime-build build server-runtime
docker compose build server
docker compose up -d server
```

## API

`POST /api/v1/pii-redactions` accepts an audio file as multipart field `file` and returns `application/zip`. The route checks for an `audio/*` content type and enforces `MAX_UPLOAD_SIZE_MB` and `MAX_AUDIO_DURATION_SECONDS`. Unsupported uploads return HTTP 415; size/duration violations return HTTP 413. FFmpeg probe failures return HTTP 422, while STT and redaction failures return HTTP 502.

Example:

```bash
curl.exe -f -X POST http://localhost:8000/api/v1/pii-redactions \
  -F "file=@recording.wav" \
  -o pii-redaction.zip
```

Other settings read from the root `.env`:

| Setting | Default | Purpose |
| --- | --- | --- |
| `STT_PROVIDER` | `vachana` | `vachana`/`gnani` for remote STT; `local`/`whisper` for local Whisper |
| `STT_API_KEY` | empty | Vachana API key ID; required for the remote provider |
| `STT_LANGUAGE_CODE` | `indic-auto` | Language selection passed to Vachana |
| `LOCAL_STT_MODEL` | `base` | Whisper model name when using local STT |
| `LOCAL_STT_DEVICE` | `cpu` | Whisper inference device |
| `LOCAL_STT_LANGUAGE` | `en` | Whisper language and local alignment language |
| `LOCAL_ALIGNMENT_DEVICE` | `cpu` | MMS_FA inference device |
| `MAX_UPLOAD_SIZE_MB` | `500` | API upload size limit |
| `MAX_AUDIO_DURATION_SECONDS` | `600` | API audio duration limit |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | Browser API URL, embedded when building the client |

`GEMINI_API_KEY` and `GEMINI_MODEL` configure the separate profanity-cleanup workflow; they are not required for spoken PII redaction.

## Command-line redaction

The server package also provides `pii-redact` for processing a local audio file with the same STT, alignment, detection, and reverification pipeline:

```powershell
cd server
uv run pii-redact recording.wav --output-dir redacted-recording --mode beep --margin-ms 80
```

The output directory contains `redacted_audio.wav`, `redacted_transcript.txt`, and `audit.json`. `--mode` accepts `beep` or `silence`; `--margin-ms` sets padding on both sides of each detection. Configure the provider and duration limit in the root `.env` as for the API.

## Development and tests

Run the API test suite and client lint/build checks:

```powershell
cd server
uv run pytest
```

```powershell
cd client
npm run lint
npm run build
```

The server also serves the existing transcription and video-cleanup routes. Those workflows have their own provider settings and are outside the scope of this PII redaction guide.
