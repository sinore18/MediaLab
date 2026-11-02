import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Video Profanity Cleanup | Bleeper",
  description: "Clean up profanity in video audio with precise bleeps while keeping the original video intact.",
  openGraph: {
    title: "Video Profanity Cleanup | Bleeper",
    description: "Clean up profanity in video audio with precise bleeps while keeping the original video intact.",
    type: "website",
    images: [
      {
        url: "/upload/opengraph-image",
        width: 1200,
        height: 630,
        alt: "Bleeper video audio cleanup with a bleeped waveform.",
      },
    ],
  },
};

export default function UploadLayout({ children }: { children: ReactNode }) {
  return children;
}
