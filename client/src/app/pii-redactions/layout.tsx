import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "PII Redaction Studio | Bleeper",
  description: "Remove personally identifiable information from audio with privacy-focused redaction and audit outputs.",
  openGraph: {
    title: "PII Redaction Studio | Bleeper",
    description: "Remove personally identifiable information from audio with privacy-focused redaction and audit outputs.",
    type: "website",
    images: [
      {
        url: "/pii-redactions/opengraph-image",
        width: 1200,
        height: 630,
        alt: "Audio waveform and transcript with personally identifiable details redacted.",
      },
    ],
  },
};

export default function PiiRedactionsLayout({ children }: { children: ReactNode }) {
  return children;
}
