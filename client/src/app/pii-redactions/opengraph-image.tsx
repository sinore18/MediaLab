import { createProjectOgImage } from "../project-og-image";

export const alt = "Audio waveform and transcript with personally identifiable details redacted.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return createProjectOgImage("redaction");
}
