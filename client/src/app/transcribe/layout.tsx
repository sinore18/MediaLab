import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Audio Transcription | Bleeper",
  description: "Transcribe audio into timestamped words with a simple upload or recording workflow.",
  openGraph: {
    title: "Audio Transcription | Bleeper",
    description: "Transcribe audio into timestamped words with a simple upload or recording workflow.",
    type: "website",
    images: [
      {
        url: "/transcribe/opengraph-image",
        width: 1200,
        height: 630,
        alt: "Audio waveform paired with a word-level, timestamped transcript.",
      },
    ],
  },
};

export default function TranscribeLayout({ children }: { children: ReactNode }) {
  return children;
}
