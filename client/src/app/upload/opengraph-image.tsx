import { createProjectOgImage } from "../project-og-image";

export const alt = "Bleeper video audio cleanup with a bleeped waveform.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return createProjectOgImage("bleeper");
}
