"use client";

import Link from "next/link";
import {
  ArrowDownToLine,
  AudioLines,
  Check,
  ChevronRight,
  Clock3,
  FileAudio2,
  FileText,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024;
const MAX_DURATION_SECONDS = 10 * 60;
const EXPECTED_FILES = [
  "redacted_audio.wav",
  "redacted_transcript.txt",
  "audit.json",
] as const;

type AuditLog = {
  original_sha256: string;
  detections: {
    category: string;
    start: number;
    end: number;
    confidence: number | null;
    validator_result: boolean | null;
  }[];
  verification?: {
    leaked_items: {
      category: string;
      start: number;
      end: number;
      confidence: number | null;
    }[];
    pii_recall: number;
    seconds_over_redacted: number;
  };
};

type RedactionResult = {
  audioUrl: string;
  audioBlob: Blob;
  transcript: string;
  audit: AuditLog;
};

type WorkState = "idle" | "processing" | "done" | "error";

function formatTime(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(safeSeconds / 60)).padStart(2, "0")}:${String(
    safeSeconds % 60,
  ).padStart(2, "0")}`;
}

function formatBytes(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatPreciseTime(seconds: number) {
  return `${seconds.toFixed(2)}s`;
}

function extractStoredZipEntries(zip: ArrayBuffer): Map<string, Blob> {
  const view = new DataView(zip);
  const bytes = new Uint8Array(zip);
  const decoder = new TextDecoder();
  const entries = new Map<string, Blob>();
  let offset = 0;

  while (offset + 30 <= view.byteLength && view.getUint32(offset, true) === 0x04034b50) {
    const flags = view.getUint16(offset + 6, true);
    const compression = view.getUint16(offset + 8, true);
    const compressedSize = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const extraLength = view.getUint16(offset + 28, true);
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const dataEnd = dataStart + compressedSize;
    const name = decoder.decode(bytes.subarray(nameStart, nameStart + nameLength));

    if ((flags & 0x0008) !== 0 || compression !== 0 || dataEnd > view.byteLength) {
      throw new Error("The server returned an unsupported archive format.");
    }

    if (EXPECTED_FILES.some((expectedName) => expectedName === name)) {
      entries.set(
        name,
        new Blob([bytes.slice(dataStart, dataEnd)], {
          type: name.endsWith(".wav") ? "audio/wav" : "application/octet-stream",
        }),
      );
    }
    offset = dataEnd;
  }

  if (!EXPECTED_FILES.every((name) => entries.has(name))) {
    throw new Error("The server response did not include all redaction outputs.");
  }
  return entries;
}

function parseAudit(value: unknown): AuditLog {
  if (
    typeof value !== "object" ||
    value === null ||
    !("original_sha256" in value) ||
    typeof value.original_sha256 !== "string" ||
    !("detections" in value) ||
    !Array.isArray(value.detections) ||
    !value.detections.every(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        "category" in item &&
        typeof item.category === "string" &&
        "start" in item &&
        typeof item.start === "number" &&
        "end" in item &&
        typeof item.end === "number",
    )
  ) {
    throw new Error("The server returned an audit log in an unexpected format.");
  }
  return value as AuditLog;
}

export default function PiiRedactionsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const audioUrlRef = useRef<string | null>(null);
  const resultUrlRef = useRef<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [workState, setWorkState] = useState<WorkState>("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<RedactionResult | null>(null);

  useEffect(
    () => () => {
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
      if (resultUrlRef.current) URL.revokeObjectURL(resultUrlRef.current);
    },
    [],
  );

  function clearResult() {
    if (resultUrlRef.current) URL.revokeObjectURL(resultUrlRef.current);
    resultUrlRef.current = null;
    setResult(null);
  }

  function selectAudio(nextFile?: File) {
    if (workState === "processing" || !nextFile) return;
    setMessage("");
    clearResult();
    if (!nextFile.type.toLowerCase().startsWith("audio/")) {
      setWorkState("error");
      setMessage("Choose an audio file to continue.");
      return;
    }
    if (nextFile.size > MAX_FILE_SIZE_BYTES) {
      setWorkState("error");
      setMessage("This audio is over the 500 MB upload limit.");
      return;
    }

    const metadataAudio = document.createElement("audio");
    const objectUrl = URL.createObjectURL(nextFile);
    metadataAudio.preload = "metadata";
    metadataAudio.onloadedmetadata = () => {
      URL.revokeObjectURL(objectUrl);
      if (!Number.isFinite(metadataAudio.duration) || metadataAudio.duration <= 0) {
        setWorkState("error");
        setMessage("We couldn’t read this recording. Try another audio format.");
        return;
      }
      if (metadataAudio.duration > MAX_DURATION_SECONDS) {
        setWorkState("error");
        setMessage("This recording is over the 10 minute duration limit.");
        return;
      }
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
      const previewUrl = URL.createObjectURL(nextFile);
      audioUrlRef.current = previewUrl;
      setSourceUrl(previewUrl);
      setFile(nextFile);
      setDurationSeconds(metadataAudio.duration);
      setWorkState("idle");
    };
    metadataAudio.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      setWorkState("error");
      setMessage("We couldn’t open this recording. Try another audio format.");
    };
    metadataAudio.src = objectUrl;
  }

  function removeAudio() {
    if (workState === "processing") return;
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioUrlRef.current = null;
    setSourceUrl(null);
    setFile(null);
    setDurationSeconds(0);
    setWorkState("idle");
    setMessage("");
    clearResult();
  }

  async function redactAudio() {
    if (!file || workState === "processing") return;
    setWorkState("processing");
    setMessage("Scanning the recording, redacting sensitive spans, and verifying the result…");
    clearResult();
    try {
      const formData = new FormData();
      formData.append("file", file, file.name);
      const response = await fetch(`${API_BASE_URL}/pii-redactions`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Redaction couldn’t be completed.");
      }

      const entries = extractStoredZipEntries(await response.arrayBuffer());
      const audioBlob = entries.get("redacted_audio.wav");
      const transcriptBlob = entries.get("redacted_transcript.txt");
      const auditBlob = entries.get("audit.json");
      if (!audioBlob || !transcriptBlob || !auditBlob) {
        throw new Error("The server response did not include all redaction outputs.");
      }

      const audioUrl = URL.createObjectURL(audioBlob);
      resultUrlRef.current = audioUrl;
      setResult({
        audioUrl,
        audioBlob,
        transcript: await transcriptBlob.text(),
        audit: parseAudit(JSON.parse(await auditBlob.text())),
      });
      setWorkState("done");
      setMessage("Redaction complete. Review or download your results below.");
    } catch (error) {
      setWorkState("error");
      setMessage(error instanceof Error ? error.message : "The audio could not be redacted.");
    }
  }

  function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function downloadAudit() {
    if (!result) return;
    downloadBlob(
      new Blob([JSON.stringify(result.audit, null, 2)], { type: "application/json" }),
      "audit.json",
    );
  }

  const detectionCount = result?.audit.detections.length ?? 0;

  return (
    <main className="pii-page">
      <header className="pii-topbar">
        <Link className="pii-brand" href="/" aria-label="Bleeper home">
          <span className="pii-brand-mark"><AudioLines size={18} strokeWidth={2.2} /></span>
          <span>bleeper<span className="pii-brand-divider">/</span>secure audio</span>
        </Link>
        <nav className="pii-nav" aria-label="Studio navigation">
          <Link className="is-current" href="/pii-redactions"><ShieldCheck size={15} /> PII redaction</Link>
          <Link href="/transcribe"><AudioLines size={15} /> Transcription</Link>
          <Link href="/upload"><FileAudio2 size={15} /> Video cleanup</Link>
        </nav>
        <span className="pii-privacy"><LockKeyhole size={14} /> PRIVATE WORKSPACE</span>
      </header>

      <div className="pii-content">
        <section className="pii-hero">
          <div className="pii-hero-copy">
            <p className="pii-eyebrow"><span /> BANKING CALLS <i /> PRIVACY TOOLKIT / 01</p>
            <h1>Keep the call.<br /><em>Lose the identifiers.</em></h1>
            <p className="pii-intro">
              Find spoken account details, redact them from the audio, and keep a clean,
              reviewable transcript.
            </p>
          </div>
          <div className="pii-hero-stamp" aria-label="Privacy pipeline">
            <span className="pii-stamp-icon"><ShieldCheck size={21} /></span>
            <span><strong>Private by design</strong><small>Temporary processing · no raw PII in audit</small></span>
            <span className="pii-stamp-check"><Check size={14} /></span>
          </div>
        </section>

        <div className="pii-layout">
          <section className="pii-panel pii-source" aria-labelledby="pii-source-title">
            <div className="pii-panel-head">
              <div>
                <p className="pii-kicker">01 / SOURCE RECORDING</p>
                <h2 id="pii-source-title">Start with audio</h2>
              </div>
              <span className="pii-step">01 <i>—</i> 02</span>
            </div>

            <input
              ref={fileInputRef}
              className="pii-file-input"
              type="file"
              accept="audio/*"
              aria-label="Choose audio recording"
              disabled={workState === "processing"}
              onChange={(event) => {
                selectAudio(event.currentTarget.files?.[0]);
                event.currentTarget.value = "";
              }}
            />
            <div
              className={`pii-dropzone${isDragging ? " is-dragging" : ""}${file ? " has-file" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                selectAudio(event.dataTransfer.files[0]);
              }}
              onClick={() => {
                if (workState !== "processing") fileInputRef.current?.click();
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              role="button"
              tabIndex={0}
              aria-label={file ? "Replace selected recording" : "Choose or drop an audio recording"}
            >
              {file ? (
                <div className="pii-selected-file">
                  <span className="pii-file-icon"><FileAudio2 size={19} /></span>
                  <span className="pii-file-info">
                    <strong>{file.name}</strong>
                    <small>{formatBytes(file.size)} <i /> {formatTime(durationSeconds)}</small>
                  </span>
                  <button
                    className="pii-icon-button"
                    type="button"
                    aria-label="Remove recording"
                    disabled={workState === "processing"}
                    onClick={(event) => {
                      event.stopPropagation();
                      removeAudio();
                    }}
                  >
                    <X size={16} />
                  </button>
                </div>
              ) : (
                <>
                  <span className="pii-upload-icon"><Upload size={19} /></span>
                  <strong>Drop a recording to begin</strong>
                  <small>or browse audio files on your device</small>
                  <span className="pii-browse">Choose recording <ChevronRight size={14} /></span>
                </>
              )}
            </div>

            {sourceUrl && (
              <div className="pii-audio-preview">
                <div className="pii-mini-label"><AudioLines size={13} /> ORIGINAL PREVIEW</div>
                <audio src={sourceUrl} controls preload="metadata" />
              </div>
            )}

            <div className="pii-file-limits">
              <span><Check size={13} /> Up to 500 MB</span>
              <span><Clock3 size={13} /> Up to 10 minutes</span>
              <span>WAV · MP3 · M4A · WebM</span>
            </div>
            <div className="pii-processing-note">
              <span><LockKeyhole size={15} /></span>
              <p><strong>Your source stays yours.</strong> Audio is staged temporarily for processing; raw PII is not included in the audit log.</p>
            </div>
            <button
              className="pii-submit"
              type="button"
              disabled={!file || workState === "processing"}
              onClick={() => void redactAudio()}
            >
              {workState === "processing" ? (
                <><LoaderCircle size={16} className="pii-spinner" /> Redacting recording</>
              ) : workState === "done" ? (
                <><RotateCcw size={16} /> Redact again</>
              ) : (
                <><ShieldCheck size={16} /> Redact spoken PII <ChevronRight size={16} /></>
              )}
            </button>
            {message && (
              <p className={`pii-status${workState === "error" ? " is-error" : workState === "done" ? " is-success" : ""}`} role="status">
                {workState === "done" && <Check size={14} />}
                {message}
              </p>
            )}
          </section>

          <section className={`pii-panel pii-results${result ? " has-result" : ""}`} aria-labelledby="pii-result-title">
            <div className="pii-panel-head pii-result-head">
              <div>
                <p className="pii-kicker">02 / REDACTED OUTPUT</p>
                <h2 id="pii-result-title">Your clean copy</h2>
              </div>
              {result ? (
                <span className="pii-ready"><i /> READY</span>
              ) : (
                <span className="pii-lock-badge"><LockKeyhole size={13} /> PRIVATE</span>
              )}
            </div>
            {result ? (
              <div className="pii-result-content">
                <div className="pii-output-audio">
                  <span className="pii-output-icon"><AudioLines size={17} /></span>
                  <div className="pii-output-main">
                    <div className="pii-output-topline">
                      <strong>Redacted recording</strong>
                      <button
                        type="button"
                        className="pii-download-link"
                        onClick={() => downloadBlob(result.audioBlob, "redacted_audio.wav")}
                        aria-label="Download redacted audio"
                      >
                        <ArrowDownToLine size={14} /> Download
                      </button>
                    </div>
                    <audio src={result.audioUrl} controls preload="metadata" />
                  </div>
                </div>

                <div className="pii-transcript-card">
                  <div className="pii-section-head">
                    <span><FileText size={14} /> REDACTED TRANSCRIPT</span>
                    <button
                      type="button"
                      className="pii-download-link"
                      onClick={() => downloadBlob(new Blob([result.transcript], { type: "text/plain" }), "redacted_transcript.txt")}
                    >
                      <ArrowDownToLine size={14} /> TXT
                    </button>
                  </div>
                  <p className="pii-transcript-text">{result.transcript || "No transcript text was returned."}</p>
                </div>

                <div className="pii-audit-grid">
                  <div className="pii-stat">
                    <span>PII SPANS</span>
                    <strong>{detectionCount}</strong>
                  </div>
                  <div className="pii-stat">
                    <span>REDACTION CHECK</span>
                    <strong>{result.audit.verification ? `${Math.round(result.audit.verification.pii_recall * 100)}%` : "—"}</strong>
                  </div>
                  <div className="pii-stat">
                    <span>OVER-REDACTED</span>
                    <strong>{result.audit.verification ? `${result.audit.verification.seconds_over_redacted.toFixed(2)}s` : "—"}</strong>
                  </div>
                </div>

                {result.audit.verification?.leaked_items.length ? (
                  <div className="pii-leaks" role="status">
                    <strong>{result.audit.verification.leaked_items.length} possible leak(s) found</strong>
                    <span>Review the timestamps before sharing this recording.</span>
                    {result.audit.verification.leaked_items.map((leak, index) => (
                      <small key={`${leak.category}-${leak.start}-${index}`}>
                        {leak.category} · {formatPreciseTime(leak.start)}–{formatPreciseTime(leak.end)}
                      </small>
                    ))}
                  </div>
                ) : (
                  <div className="pii-verified"><ShieldCheck size={15} /> Re-transcription found no matching PII spans.</div>
                )}

                <details className="pii-audit-details">
                  <summary><span>Audit details <small>{detectionCount} detections</small></span><ChevronRight size={14} /></summary>
                  <div className="pii-detection-list">
                    {result.audit.detections.length ? result.audit.detections.map((detection, index) => (
                      <div className="pii-detection-row" key={`${detection.category}-${detection.start}-${index}`}>
                        <strong>[{detection.category}]</strong>
                        <span>{formatPreciseTime(detection.start)} – {formatPreciseTime(detection.end)}</span>
                        <small>{detection.validator_result ? "Validated" : "Review"}</small>
                      </div>
                    )) : <p>No PII spans detected.</p>}
                    <code>SHA-256 · {result.audit.original_sha256}</code>
                    <button
                      type="button"
                      className="pii-audit-download"
                      onClick={downloadAudit}
                    >
                      <ArrowDownToLine size={14} /> Download audit.json
                    </button>
                  </div>
                </details>
              </div>
            ) : (
              <div className="pii-empty">
                <span className="pii-empty-core"><ShieldCheck size={23} /></span>
                <h3>A safer version starts here.</h3>
                <p>Upload an audio file to receive redacted playback and a tagged transcript.</p>
                <div className="pii-empty-flow"><span>DETECT</span><i /><span>REDACT</span><i /><span>VERIFY</span></div>
              </div>
            )}
            <div className="pii-result-foot">
              <span><ShieldCheck size={13} /> NO RAW PII IN AUDIT</span>
              <span>ENGLISH · HINDI · HINGLISH</span>
            </div>
          </section>
        </div>

        <footer className="pii-footer">
          <span>Designed for sensitive conversations.</span>
          <Link href="/transcribe">Explore transcription <ChevronRight size={14} /></Link>
        </footer>
      </div>
    </main>
  );
}
