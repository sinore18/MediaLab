"use client";

import Link from "next/link";
import {
  ArrowDownToLine,
  AudioLines,
  Check,
  ChevronRight,
  Clock3,
  Copy,
  FileAudio2,
  FileText,
  Headphones,
  LoaderCircle,
  Mic,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Square,
  Upload,
  Waves,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024;
const MAX_DURATION_SECONDS = 10 * 60;
const waveformHeights = [
  18, 30, 24, 42, 27, 35, 54, 29, 47, 22, 38, 58, 31, 45, 25, 52, 34, 43, 61, 29, 40, 23, 49, 35,
  56, 27, 43, 32, 59, 24, 38, 51, 30, 46, 22, 54, 37, 28, 48, 34, 60, 25, 42, 31, 52, 23, 45, 36,
];

type WordTiming = { word: string; start_seconds: number; end_seconds: number };
type Transcription = { transcript: string; duration_seconds: number; words: WordTiming[] };
type SelectedAudio = { file: File; durationSeconds: number };
type WorkState = "idle" | "processing" | "done" | "error";
type RequestMode = "curl" | "http";

function formatTime(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(safeSeconds % 60).padStart(2, "0")}`;
}

function formatBytes(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatPreciseTime(seconds: number) {
  return `${seconds.toFixed(2)}s`;
}

function validateTranscription(value: unknown): Transcription {
  if (
    typeof value !== "object" ||
    value === null ||
    !("transcript" in value) ||
    !("duration_seconds" in value) ||
    !("words" in value) ||
    typeof value.transcript !== "string" ||
    typeof value.duration_seconds !== "number" ||
    !Array.isArray(value.words) ||
    !value.words.every(
      (word) =>
        typeof word === "object" &&
        word !== null &&
        "word" in word &&
        "start_seconds" in word &&
        "end_seconds" in word &&
        typeof word.word === "string" &&
        typeof word.start_seconds === "number" &&
        typeof word.end_seconds === "number",
    )
  ) {
    throw new Error("The server returned a transcript in an unexpected format.");
  }
  return value as Transcription;
}

export default function TranscribePage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const recordingStartedAtRef = useRef(0);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const [selectedAudio, setSelectedAudio] = useState<SelectedAudio | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [workState, setWorkState] = useState<WorkState>("idle");
  const [requestMode, setRequestMode] = useState<RequestMode>("curl");
  const [message, setMessage] = useState("");
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [activeWordIndex, setActiveWordIndex] = useState<number | null>(null);

  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  function setAudioPreview(file: File, durationSeconds: number) {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const url = URL.createObjectURL(file);
    previewUrlRef.current = url;
    setPreviewUrl(url);
    setSelectedAudio({ file, durationSeconds });
    setTranscription(null);
    setActiveWordIndex(null);
    setWorkState("idle");
    setMessage("");
  }

  function clearAudio() {
    if (workState === "processing") return;
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setPreviewUrl(null);
    setSelectedAudio(null);
    setTranscription(null);
    setActiveWordIndex(null);
    setWorkState("idle");
    setMessage("");
  }

  function selectAudio(file?: File) {
    if (workState === "processing") return;
    setMessage("");
    if (!file) return;
    if (!file.type.toLowerCase().startsWith("audio/")) {
      setWorkState("error");
      setMessage("Choose an audio file to continue.");
      return;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setWorkState("error");
      setMessage("This audio file is over the 500 MB upload limit.");
      return;
    }

    const probe = document.createElement("audio");
    const objectUrl = URL.createObjectURL(file);
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      URL.revokeObjectURL(objectUrl);
      if (!Number.isFinite(probe.duration) || probe.duration <= 0) {
        setWorkState("error");
        setMessage("We couldn’t read this audio file. Try another format.");
        return;
      }
      if (probe.duration > MAX_DURATION_SECONDS) {
        setWorkState("error");
        setMessage("This audio is over the 10 minute duration limit.");
        return;
      }
      setAudioPreview(file, probe.duration);
    };
    probe.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      setWorkState("error");
      setMessage("We couldn’t open this audio file. Try another format.");
    };
    probe.src = objectUrl;
  }

  function stopRecording() {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") recorder.stop();
  }

  async function startRecording() {
    setMessage("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setWorkState("error");
      setMessage("Voice recording isn’t supported in this browser. You can upload an audio clip instead.");
      return;
    }

    try {
      clearAudio();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recordingStartedAtRef.current = Date.now();
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
        recordingTimerRef.current = null;
        const durationSeconds = Math.min(
          MAX_DURATION_SECONDS,
          (Date.now() - recordingStartedAtRef.current) / 1000,
        );
        setRecordingSeconds(Math.floor(durationSeconds));
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (blob.size === 0) {
          setWorkState("error");
          setMessage("No audio was captured. Check your microphone and try again.");
          setIsRecording(false);
          return;
        }
        const extension = blob.type.includes("mp4") ? "m4a" : "webm";
        setAudioPreview(new File([blob], `voice-recording.${extension}`, { type: blob.type }), durationSeconds);
        setIsRecording(false);
      };
      recorder.start(250);
      setRecordingSeconds(0);
      setIsRecording(true);
      recordingTimerRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - recordingStartedAtRef.current) / 1000);
        setRecordingSeconds(elapsed);
        if (elapsed >= MAX_DURATION_SECONDS) stopRecording();
      }, 250);
    } catch (error) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setWorkState("error");
      setMessage(
        error instanceof Error && error.name === "NotAllowedError"
          ? "Microphone access was blocked. Allow microphone access or upload an audio clip."
          : "We couldn’t start the microphone. Check your device and try again.",
      );
    }
  }

  async function createTranscript() {
    if (!selectedAudio || workState === "processing") return;
    setWorkState("processing");
    setMessage("Sending audio to Gnani STT, then aligning every word…");
    setTranscription(null);
    try {
      const formData = new FormData();
      formData.append("file", selectedAudio.file, selectedAudio.file.name);
      const response = await fetch(`${API_BASE_URL}/transcriptions`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Transcription couldn’t be completed.");
      }
      const result = validateTranscription(await response.json());
      setTranscription(result);
      setWorkState("done");
      setMessage("Your transcript is ready, with word-level timing.");
    } catch (error) {
      setWorkState("error");
      setMessage(error instanceof Error ? error.message : "The audio could not be transcribed.");
    }
  }

  async function copyTranscript() {
    if (!transcription) return;
    try {
      await navigator.clipboard.writeText(transcription.transcript);
      setMessage("Transcript copied to your clipboard.");
    } catch {
      setMessage("Clipboard access was blocked. You can still select and copy the transcript.");
    }
  }

  function downloadTranscript() {
    if (!transcription) return;
    const blob = new Blob([JSON.stringify(transcription, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${selectedAudio?.file.name.replace(/\.[^.]+$/, "") || "transcript"}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function jumpToWord(word: WordTiming, index: number) {
    if (!audioRef.current) return;
    audioRef.current.currentTime = word.start_seconds;
    setActiveWordIndex(index);
    void audioRef.current.play().catch(() => {
      setMessage("Playback couldn’t start. Use the audio controls to try again.");
    });
  }

  function updateActiveWord() {
    if (!audioRef.current || !transcription) return;
    const time = audioRef.current.currentTime;
    const index = transcription.words.findIndex(
      (word) => time >= word.start_seconds && time < word.end_seconds,
    );
    setActiveWordIndex(index >= 0 ? index : null);
  }

  const waveformClass = `transcribe-waveform${isRecording ? " is-recording" : ""}`;
  const requestExample =
    requestMode === "curl"
      ? `curl --request POST "${API_BASE_URL}/transcriptions" --header "accept: application/json" --form "file=@audio.wav"`
      : `const apiBaseUrl = "${API_BASE_URL}";
const formData = new FormData();
formData.append("file", audioFile);

const response = await fetch(\`\${apiBaseUrl}/transcriptions\`, {
  method: "POST",
  body: formData,
});

if (!response.ok) {
  throw new Error(\`Transcription failed: \${response.status}\`);
}

const result = await response.json();`;

  return (
    <main className="transcribe-page">
      <header className="transcribe-topbar">
        <Link className="transcribe-brand" href="/" aria-label="Bleeper home">
          <span className="transcribe-brand-mark"><AudioLines size={18} strokeWidth={2.2} /></span>
          <span>bleeper<span className="brand-divider">/</span>studio</span>
        </Link>
        <nav className="transcribe-nav" aria-label="Studio navigation">
          <a className="nav-active" href="/transcribe"><Waves size={15} /> Transcription</a>
          <Link href="/upload"><FileAudio2 size={15} /> Video cleanup</Link>
        </nav>
        <span className="privacy-badge"><ShieldCheck size={14} /> Transcription workspace</span>
      </header>

      <div className="transcribe-content">
        <section className="transcribe-heading">
          <div>
            <p className="transcribe-eyebrow"><span className="live-dot" /> AUDIO WORKSPACE <span className="eyebrow-separator">/</span> 01</p>
            <h1>Words, <em>in sync.</em></h1>
            <p className="transcribe-subtitle">
              Turn a recording into a precise, word-by-word transcript. Start with your voice or bring an audio clip.
            </p>
          </div>
          <div className="pipeline-badges" aria-label="Transcription pipeline">
            <span><Sparkles size={14} /> Gnani STT</span>
            <ChevronRight size={14} className="pipeline-arrow" />
            <span><AudioLines size={14} /> MMS_FA aligner</span>
          </div>
        </section>

        <div className="transcribe-workspace">
          <section className="source-card" aria-labelledby="source-title">
            <div className="card-heading">
              <div>
                <p className="card-kicker">YOUR SOURCE</p>
                <h2 id="source-title">Start with audio</h2>
              </div>
              <span className="step-pill">01 <span> / 02</span></span>
            </div>

            <div className="source-tabs" aria-label="Choose audio source">
              <button
                className="source-tab source-tab-active"
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={workState === "processing"}
              >
                <Upload size={15} /> Upload audio
              </button>
              <span className="source-tab-divider">or</span>
              <button
                className={`record-toggle${isRecording ? " recording-active" : ""}`}
                type="button"
                onClick={isRecording ? stopRecording : () => void startRecording()}
                disabled={workState === "processing"}
              >
                {isRecording ? <Square size={13} fill="currentColor" /> : <Mic size={15} />}
                {isRecording ? "Stop recording" : "Record voice"}
              </button>
            </div>

            <input
              ref={fileInputRef}
              className="audio-file-input"
              type="file"
              accept="audio/*"
              aria-hidden="true"
              disabled={workState === "processing"}
              tabIndex={-1}
              onChange={(event) => {
                selectAudio(event.target.files?.[0]);
                event.currentTarget.value = "";
              }}
            />
            <div
              className={`audio-dropzone${isDragging ? " is-dragging" : ""}${selectedAudio ? " has-audio" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                selectAudio(event.dataTransfer.files[0]);
              }}
              onClick={(event) => {
                if (workState !== "processing" && event.target !== fileInputRef.current) fileInputRef.current?.click();
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              role={selectedAudio ? undefined : "button"}
              tabIndex={selectedAudio ? -1 : 0}
              aria-label={selectedAudio ? "Replace selected audio file" : "Choose or drop an audio file"}
            >
              {selectedAudio ? (
                <div className="audio-selected">
                  <span className="audio-file-icon"><FileAudio2 size={19} /></span>
                  <div className="audio-file-copy">
                    <span className="audio-file-name">{selectedAudio.file.name}</span>
                    <span className="audio-file-meta">{formatBytes(selectedAudio.file.size)} <i /> {formatTime(selectedAudio.durationSeconds)}</span>
                  </div>
                  <button
                    className="icon-button remove-audio"
                    type="button"
                    aria-label="Remove audio"
                    disabled={workState === "processing"}
                    onClick={(event) => { event.stopPropagation(); clearAudio(); }}
                  >
                    <X size={16} />
                  </button>
                </div>
              ) : (
                <>
                  <span className="drop-icon"><Upload size={19} /></span>
                  <strong>Drop your audio in here</strong>
                  <span className="drop-copy">or browse files on your device</span>
                  <span className="browse-audio-button">Choose audio <ChevronRight size={14} /></span>
                </>
              )}
            </div>

            {isRecording ? (
              <>
                <div className="recording-status" role="status">
                  <span className="recording-dot" />
                  <span>Recording in progress</span>
                  <strong>{formatTime(recordingSeconds)}</strong>
                  <span className="record-limit">of 10:00 max</span>
                </div>
                <span className={waveformClass} aria-hidden="true">
                  {waveformHeights.map((height, index) => (
                    <i key={index} style={{ height: `${height}px` }} />
                  ))}
                </span>
              </>
            ) : selectedAudio && previewUrl ? (
              <div className="audio-preview">
                <audio ref={audioRef} src={previewUrl} controls onTimeUpdate={updateActiveWord} />
                <span className={waveformClass} aria-hidden="true">
                  {waveformHeights.map((height, index) => (
                    <i key={index} style={{ height: `${height}px` }} />
                  ))}
                </span>
              </div>
            ) : (
              <div className="record-hint">
                <span className="mic-hint-icon"><Mic size={15} /></span>
                <span>Use your microphone for a quick voice note, or upload a clip instead.</span>
              </div>
            )}

            <div className="audio-limits">
              <span><Check size={13} /> Up to 500 MB</span>
              <span><Clock3 size={13} /> Up to 10 minutes</span>
              <span>WAV, MP3, M4A, WebM</span>
            </div>

            <button
              className="transcribe-button"
              type="button"
              disabled={!selectedAudio || isRecording || workState === "processing"}
              onClick={() => void createTranscript()}
            >
              {workState === "processing" ? (
                <><LoaderCircle size={16} className="loading-icon" /> Transcribing your audio</>
              ) : workState === "done" ? (
                <><RotateCcw size={16} /> Transcribe again</>
              ) : (
                <><Sparkles size={16} /> Generate transcript <ChevronRight size={16} /></>
              )}
            </button>
            {message && (
              <p className={`transcribe-message${workState === "error" ? " is-error" : workState === "done" ? " is-success" : ""}`} role="status">
                {workState === "done" && <Check size={14} />}
                {message}
              </p>
            )}
            <div className="source-foot"><ShieldCheck size={14} /> Gnani STT automatically detects the audio language; temporary API-host audio is removed after alignment.</div>
          </section>

          <section className={`result-card${transcription ? " has-result" : ""}`} aria-labelledby="result-title">
            <div className="card-heading result-heading">
              <div>
                <p className="card-kicker">THE RESULT</p>
                <h2 id="result-title">Your transcript</h2>
              </div>
              {transcription ? (
                <span className="ready-pill"><span /> READY</span>
              ) : (
                <span className="step-pill">02 <span> / 02</span></span>
              )}
            </div>

            {transcription ? (
              <>
                <div className="transcript-tools">
                  <span><Clock3 size={13} /> {formatTime(transcription.duration_seconds)}</span>
                  <span><AudioLines size={13} /> {transcription.words.length} words</span>
                  <div className="tool-actions">
                    <button className="tool-button" type="button" onClick={() => void copyTranscript()}><Copy size={14} /> Copy text</button>
                    <button className="tool-button" type="button" onClick={downloadTranscript}><ArrowDownToLine size={14} /> Export JSON</button>
                  </div>
                </div>
                <div className="transcript-body">
                  <div className="transcript-text" aria-label="Full transcript">{transcription.transcript}</div>
                </div>
                <div className="word-list-heading">
                  <span>WORD TIMINGS</span>
                  <span>Click a word to jump to that moment</span>
                </div>
                <div className="word-timings" aria-label="Word-level timestamps">
                  {transcription.words.map((word, index) => (
                    <button
                      className={`word-timing${activeWordIndex === index ? " is-active" : ""}`}
                      key={`${word.start_seconds}-${index}`}
                      type="button"
                      onClick={() => jumpToWord(word, index)}
                      title={`Play from ${formatPreciseTime(word.start_seconds)}`}
                    >
                      <span>{word.word}</span>
                      <small>{formatPreciseTime(word.start_seconds)}</small>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <div className="result-empty">
                <div className="empty-art" aria-hidden="true">
                  <span className="empty-orbit orbit-outer" />
                  <span className="empty-orbit orbit-inner" />
                  <span className="empty-core"><Headphones size={23} /></span>
                  <span className="empty-signal signal-one" />
                  <span className="empty-signal signal-two" />
                  <span className="empty-signal signal-three" />
                </div>
                <h3>Your words will land here.</h3>
                <p>Upload or record something to see your transcript, with every word synced to its moment.</p>
                <div className="empty-steps">
                  <span><span>01</span> Add audio</span>
                  <i />
                  <span><span>02</span> Get your transcript</span>
                </div>
              </div>
            )}
            <div className="result-foot">
              <span><FileText size={13} /> WORD-LEVEL PRECISION</span>
              <span>Gnani <i /> torchaudio MMS_FA</span>
            </div>
          </section>
        </div>

        <section className="api-guide" aria-labelledby="api-guide-title">
          <div className="api-guide-heading">
            <div>
              <p className="card-kicker">API QUICKSTART</p>
              <h2 id="api-guide-title">Send audio. Get word timings.</h2>
              <p>POST an audio file and receive a transcript with start and end times for every word.</p>
            </div>
            <span className="api-method">POST <i>/transcriptions</i></span>
          </div>

          <div className="api-guide-grid">
            <div className="api-example-card">
              <div className="api-example-heading">
                <div>
                  <span className="api-section-label">1 / REQUEST</span>
                  <h3>Upload your audio</h3>
                </div>
                <div className="api-request-toggle" aria-label="Request format">
                  <button
                    type="button"
                    aria-pressed={requestMode === "curl"}
                    className={requestMode === "curl" ? "is-selected" : ""}
                    onClick={() => setRequestMode("curl")}
                  >
                    cURL
                  </button>
                  <button
                    type="button"
                    aria-pressed={requestMode === "http"}
                    className={requestMode === "http" ? "is-selected" : ""}
                    onClick={() => setRequestMode("http")}
                  >
                    HTTP
                  </button>
                </div>
              </div>
              <pre className="api-code" aria-live="polite"><code>{requestExample}</code></pre>
              <p className="api-example-note">
                Send the audio as multipart form data in the <code>file</code> field.
                {requestMode === "http" && " The browser sets the multipart content type and boundary for you."}
                {" "}Replace the base URL with your API host when deployed.
              </p>
            </div>

            <div className="api-example-card">
              <div className="api-example-heading">
                <div>
                  <span className="api-section-label">2 / RESPONSE</span>
                  <h3>Word-level timestamps</h3>
                </div>
                <span className="api-json-label">JSON</span>
              </div>
              <pre className="api-code api-response-code"><code>{`{
  "transcript": "Hello there.",
  "duration_seconds": 2.4,
  "words": [
    { "word": "Hello", "start_seconds": 0.18, "end_seconds": 0.92 },
    { "word": "there.", "start_seconds": 1.02, "end_seconds": 1.64 }
  ]
}`}</code></pre>
              <p className="api-example-note">
                Times are in seconds relative to the start of the audio clip. Each word includes its own start and end.
              </p>
            </div>
          </div>
        </section>

        <footer className="transcribe-footer">
          <span>Made for listening closely.</span>
          <Link href="/">Back to Bleeper <ChevronRight size={14} /></Link>
        </footer>
      </div>
    </main>
  );
}
