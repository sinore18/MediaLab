"use client";

import { ArrowRight, AudioLines, Check, Clock3, Download, FileVideo2, Pause, Play, ShieldCheck, UploadCloud, Volume2, VolumeX, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024;
const MAX_DURATION_SECONDS = 10 * 60;
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

type SelectedVideo = { file: File; durationSeconds: number };
type UploadState = "idle" | "uploading" | "done" | "error";
type BleepSpan = { start: number; end: number };

function parseBleepTimestamps(header: string | null): number[] {
  if (header === null) {
    throw new Error("The server response is missing the bleep timestamps.");
  }

  let timestamps: unknown;
  try {
    timestamps = JSON.parse(header);
  } catch {
    throw new Error("The server returned invalid bleep timestamps.");
  }

  if (
    !Array.isArray(timestamps) ||
    !timestamps.every((timestamp) => typeof timestamp === "number" && Number.isFinite(timestamp) && timestamp >= 0)
  ) {
    throw new Error("The server returned invalid bleep timestamps.");
  }

  return timestamps;
}

function parseBleepSpans(header: string | null): BleepSpan[] {
  if (header === null) {
    throw new Error("The server response is missing the bleep spans.");
  }

  let spans: unknown;
  try {
    spans = JSON.parse(header);
  } catch {
    throw new Error("The server returned invalid bleep spans.");
  }

  if (
    !Array.isArray(spans) ||
    !spans.every(
      (span) =>
        Array.isArray(span) &&
        span.length === 2 &&
        typeof span[0] === "number" &&
        Number.isFinite(span[0]) &&
        span[0] >= 0 &&
        typeof span[1] === "number" &&
        Number.isFinite(span[1]) &&
        span[1] > span[0],
    )
  ) {
    throw new Error("The server returned invalid bleep spans.");
  }

  return spans.map(([start, end]) => ({ start, end }));
}

function formatBytes(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const previewRef = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<SelectedVideo | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [message, setMessage] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [bleepTimestamps, setBleepTimestamps] = useState<number[]>([]);
  const [bleepSpans, setBleepSpans] = useState<BleepSpan[]>([]);
  const [playerDuration, setPlayerDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  async function selectVideo(file?: File) {
    setMessage("");
    setUploadState("idle");
    setPreviewUrl(null);
    setBleepTimestamps([]);
    setBleepSpans([]);
    setCurrentTime(0);
    setPlayerDuration(0);
    setIsPlaying(false);
    if (!file) return;
    if (!file.type.startsWith("video/")) {
      setVideo(null);
      setUploadState("error");
      setMessage("Choose a video file to continue.");
      return;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setVideo(null);
      setUploadState("error");
      setMessage("This file is over the 100 MB upload limit.");
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    const probe = document.createElement("video");
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      URL.revokeObjectURL(objectUrl);
      if (!Number.isFinite(probe.duration) || probe.duration <= 0) {
        setVideo(null);
        setUploadState("error");
        setMessage("We couldn't read this video's duration.");
        return;
      }
      if (probe.duration > MAX_DURATION_SECONDS) {
        setVideo(null);
        setUploadState("error");
        setMessage("This video is over the 10 minute duration limit.");
        return;
      }
      setVideo({ file, durationSeconds: probe.duration });
    };
    probe.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      setVideo(null);
      setUploadState("error");
      setMessage("We couldn't read this video. Try another file format.");
    };
    probe.src = objectUrl;
  }

  async function uploadVideo() {
    if (!video) return;
    setUploadState("uploading");
    setMessage("Processing video...");
    try {
      const formData = new FormData();
      formData.append("file", video.file, video.file.name);
      const response = await fetch(`${API_BASE_URL}/uploads`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "The video could not be processed.");
      }

      const timestamps = parseBleepTimestamps(response.headers.get("X-Bleep-Timestamps"));
      const spans = parseBleepSpans(response.headers.get("X-Bleep-Spans"));
      const returnedVideo = await response.blob();
      setPreviewUrl(URL.createObjectURL(returnedVideo));
      setBleepTimestamps(timestamps);
      setBleepSpans(spans);
      setUploadState("done");
      setMessage("Processing complete. Preview or download your cleaned video.");
    } catch (error) {
      setUploadState("error");
      setMessage(error instanceof Error ? error.message : "The upload could not be completed.");
    }
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="Bleeper home">
          <span className="brand-mark"><FileVideo2 size={19} strokeWidth={2.2} /></span>
          <span>bleeper</span>
        </Link>
        <div className="topbar-note"><a href="/transcribe" className="topbar-transcribe-link"><AudioLines size={14} /> Transcribe audio</a><ShieldCheck size={15} /> Private by design</div>
      </header>

      <div className="main-grid">
        <section className="upload-panel" aria-labelledby="upload-title">
          <div className="panel-head">
            <div>
              <h2 className="panel-title" id="upload-title">Start with a video</h2>
              <p className="panel-caption">Choose a file to begin your cleanup.</p>
            </div>
            <div className="secure-label"><FileVideo2 size={14} /> Server processing</div>
          </div>
          <div className="panel-body">
            <div
              className={`dropzone${isDragging ? " is-dragging" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => { event.preventDefault(); setIsDragging(false); void selectVideo(event.dataTransfer.files[0]); }}
              onClick={(event) => { if (event.target !== inputRef.current) inputRef.current?.click(); }}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") inputRef.current?.click(); }}
              role="button"
              tabIndex={0}
              aria-label="Choose a video file"
            >
              <input ref={inputRef} className="file-input" type="file" accept="video/*" onChange={(event) => void selectVideo(event.target.files?.[0])} aria-label="Choose video file" />
              <span className="upload-icon"><UploadCloud size={24} /></span>
              <p className="drop-title">Drop your video here</p>
              <p className="drop-copy">or browse files on your device</p>
              <button className="browse-button" type="button" onClick={(event) => { event.stopPropagation(); inputRef.current?.click(); }}>Browse videos</button>
            </div>

            {video && (
              <div className="file-row">
                <span className="file-symbol"><FileVideo2 size={19} /></span>
                <div className="file-info">
                  <p className="file-name">{video.file.name}</p>
                  <p className="file-meta">{formatBytes(video.file.size)} · {formatDuration(video.durationSeconds)}</p>
                </div>
                <button className="remove-button" type="button" title="Remove video" aria-label="Remove video" onClick={() => { setVideo(null); setPreviewUrl(null); setBleepTimestamps([]); setBleepSpans([]); setCurrentTime(0); setPlayerDuration(0); setIsPlaying(false); setUploadState("idle"); setMessage(""); }}><X size={17} /></button>
              </div>
            )}

            <div className="limits">
              <span className="limit-item"><Check size={14} /> Up to 100 MB</span>
              <span className="limit-item"><Clock3 size={14} /> Up to 30 seconds</span>
              <span className="limit-item">MP4, MOV, WebM</span>
            </div>
            <button className="submit-button" type="button" disabled={!video || uploadState === "uploading" || uploadState === "done"} onClick={() => void uploadVideo()}>
              {uploadState === "uploading" ? "Processing video..." : uploadState === "done" ? "Processing complete" : "Upload video"}
              {uploadState !== "uploading" && uploadState !== "done" && <ArrowRight size={16} />}
            </button>
            {message && <p className={`status-message ${uploadState === "error" ? "error" : uploadState === "done" ? "success" : ""}`} role="status">{uploadState === "done" ? <Check size={15} /> : null}{message}</p>}
            {previewUrl && (
              <>
                <div className="video-player">
                  <div className="player-heading">
                    <span className="player-title"><span className="player-live-dot" /> PROCESSED VIDEO</span>
                    <span className="player-bleep-count">{bleepSpans.length} {bleepSpans.length === 1 ? "BLEEP MARKED" : "BLEEPS MARKED"}</span>
                  </div>
                  <video
                    ref={previewRef}
                    className="local-preview"
                    src={previewUrl}
                    playsInline
                    muted={isMuted}
                    aria-label="Processed video preview"
                    onLoadedMetadata={(event) => setPlayerDuration(event.currentTarget.duration)}
                    onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onEnded={() => setIsPlaying(false)}
                  />
                  <div className="player-controls">
                    <button
                      className="player-button player-play-button"
                      type="button"
                      aria-label={isPlaying ? "Pause video" : "Play video"}
                      onClick={() => {
                        const player = previewRef.current;
                        if (!player) return;
                        if (player.paused) {
                          void player.play().catch(() => setIsPlaying(false));
                        } else {
                          player.pause();
                        }
                      }}
                    >
                      {isPlaying ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}
                    </button>
                    <div className="player-time" aria-live="off">
                      <span>{formatDuration(currentTime)}</span>
                      <span className="player-time-divider">/</span>
                      <span>{formatDuration(playerDuration)}</span>
                    </div>
                    <div className="player-timeline">
                      <div className="timeline-track" aria-hidden="true">
                        <span className="timeline-base" />
                        <span className="timeline-played" style={{ width: `${playerDuration ? (currentTime / playerDuration) * 100 : 0}%` }} />
                        {playerDuration > 0 && bleepSpans.map((span, index) => {
                          const start = Math.max(0, Math.min(span.start, playerDuration));
                          const end = Math.max(0, Math.min(span.end, playerDuration));
                          if (end <= start) return null;
                          return (
                            <span
                              className="timeline-bleep"
                              key={`${span.start}-${index}`}
                              style={{ left: `${(start / playerDuration) * 100}%`, width: `${((end - start) / playerDuration) * 100}%` }}
                            />
                          );
                        })}
                      </div>
                      <input
                        className="player-seek"
                        type="range"
                        min={0}
                        max={playerDuration || 0}
                        step={0.1}
                        value={Math.min(currentTime, playerDuration || 0)}
                        disabled={!playerDuration}
                        aria-label="Video progress"
                        onChange={(event) => {
                          const nextTime = Number(event.currentTarget.value);
                          if (previewRef.current) previewRef.current.currentTime = nextTime;
                          setCurrentTime(nextTime);
                        }}
                      />
                    </div>
                    <button
                      className="player-button player-volume-button"
                      type="button"
                      aria-label={isMuted ? "Unmute video" : "Mute video"}
                      onClick={() => setIsMuted((muted) => !muted)}
                    >
                      {isMuted ? <VolumeX size={17} /> : <Volume2 size={17} />}
                    </button>
                  </div>
                  {bleepSpans.length > 0 && (
                    <div className="player-legend"><span /> Highlighted sections have been bleeped</div>
                  )}
                </div>
                <a className="download-link" href={previewUrl} download="bleeper-processed.mp4"><Download size={15} /> Download processed video</a>
                <section className="bleep-list" aria-labelledby="bleep-list-title">
                  <div className="bleep-list-heading">
                    <h3 id="bleep-list-title">Bleep timestamps</h3>
                    <span>{bleepTimestamps.length} {bleepTimestamps.length === 1 ? "bleep" : "bleeps"}</span>
                  </div>
                  {bleepTimestamps.length > 0 ? (
                    <div className="bleep-timestamps">
                      {bleepTimestamps.map((timestamp, index) => (
                        <button
                          className="timestamp-button"
                          type="button"
                          key={`${timestamp}-${index}`}
                          onClick={() => {
                            if (previewRef.current) previewRef.current.currentTime = timestamp;
                          }}
                          aria-label={`Jump to bleep at ${formatDuration(timestamp)}`}
                        >
                          <Clock3 size={14} />
                          {formatDuration(timestamp)}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="no-bleeps">No bleeps were needed in this video.</p>
                  )}
                </section>
              </>
            )}
          </div>
          <div className="panel-foot"><FileVideo2 size={14} /> Your video is sent to the API for processing, then returned for preview and download.</div>
        </section>
      </div>
    </main>
  );
}
