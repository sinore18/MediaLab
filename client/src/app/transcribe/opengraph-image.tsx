import { createProjectOgImage } from "../project-og-image";

export const alt = "Audio waveform paired with a word-level, timestamped transcript.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return createProjectOgImage("transcription");
}
