import { ImageResponse } from "next/og";

type Project = "bleeper" | "redaction" | "transcription";

const projects = {
  bleeper: {
    label: "VIDEO AUDIO CLEANUP",
    title: "Keep the story.\nLose the words.",
    description: "A clean bleep. The moment stays.",
    accent: "#f7c95c",
  },
  redaction: {
    label: "PRIVACY-FIRST AUDIO",
    title: "Keep the call.\nLose the identifiers.",
    description: "PII redaction with a clear audit trail.",
    accent: "#83e0bd",
  },
  transcription: {
    label: "WORD-LEVEL TRANSCRIPTION",
    title: "Every word,\nin sync.",
    description: "Turn a recording into timestamped text.",
    accent: "#8fc6ff",
  },
} satisfies Record<Project, { label: string; title: string; description: string; accent: string }>;

const waveform = [
  20, 34, 26, 48, 37, 58, 30, 43, 62, 33, 47, 24, 55, 39, 67, 29, 44, 58, 32, 49, 23, 40,
];

function Artwork({ project, accent }: { project: Project; accent: string }) {
  if (project === "redaction") {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: 438,
          padding: 28,
          borderRadius: 22,
          backgroundColor: "#202d2a",
          border: "1px solid #40534d",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", color: "#b7c8c0", fontSize: 16 }}>
          <span>REDACTED TRANSCRIPT</span>
          <span style={{ color: accent }}>● SECURE</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 18, marginTop: 32, fontSize: 19 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ color: "#9bacaa", width: 46 }}>00:04</span>
            <span>My email is</span>
            <span style={{ backgroundColor: "#101514", color: "#101514", padding: "5px 15px", borderRadius: 5 }}>hidden</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ color: "#9bacaa", width: 46 }}>00:08</span>
            <span>and my phone is</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ color: "#9bacaa", width: 46 }}>00:11</span>
            <span style={{ backgroundColor: "#101514", color: "#101514", padding: "5px 15px", borderRadius: 5 }}>hidden</span>
            <span>— removed</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", marginTop: 32, gap: 5 }}>
          {waveform.map((height, index) => (
            <span
              key={index}
              style={{
                width: 6,
                height,
                borderRadius: 4,
                backgroundColor: index > 8 && index < 15 ? "#60706a" : accent,
              }}
            />
          ))}
        </div>
        <div style={{ display: "flex", marginTop: 20, color: accent, fontSize: 14, letterSpacing: 2 }}>
          PII REMOVED · AUDIT READY
        </div>
      </div>
    );
  }

  if (project === "transcription") {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: 438,
          padding: 28,
          borderRadius: 22,
          backgroundColor: "#202838",
          border: "1px solid #3c4a60",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", color: "#b9c9de", fontSize: 16 }}>
          <span>INTERVIEW.wav</span>
          <span>00:18</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 110, gap: 5, marginTop: 14 }}>
          {waveform.map((height, index) => (
            <span
              key={index}
              style={{
                width: 6,
                height,
                borderRadius: 4,
                backgroundColor: index < 12 ? accent : "#53627a",
              }}
            />
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 16, fontSize: 19 }}>
          <div style={{ display: "flex", gap: 14 }}>
            <span style={{ color: accent, width: 82 }}>00:02.3</span>
            <span>Every word</span>
          </div>
          <div style={{ display: "flex", gap: 14 }}>
            <span style={{ color: accent, width: 82 }}>00:03.1</span>
            <span>right on time.</span>
          </div>
        </div>
        <div style={{ display: "flex", marginTop: 24, color: "#9eacc1", fontSize: 14, letterSpacing: 2 }}>
          WORD-LEVEL TIMESTAMPS
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        width: 438,
        padding: 28,
        borderRadius: 22,
        backgroundColor: "#28291f",
        border: "1px solid #514a35",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", color: "#d0cbb8", fontSize: 16 }}>
        <span>weekend-recap.mp4</span>
        <span>00:18</span>
      </div>
      <div
        style={{
          display: "flex",
          height: 126,
          marginTop: 22,
          borderRadius: 12,
          background: "linear-gradient(145deg, #465b54 0%, #293731 55%, #202b28 100%)",
          alignItems: "center",
          justifyContent: "center",
          color: "#e5eee7",
          fontSize: 20,
        }}
      >
        AUDIO CLEANUP STUDIO
      </div>
      <div style={{ display: "flex", alignItems: "center", marginTop: 26, gap: 5 }}>
        {waveform.map((height, index) => (
          <span
            key={index}
            style={{
              width: 6,
              height,
              borderRadius: 4,
              backgroundColor: index > 9 && index < 14 ? "#8d7842" : accent,
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 18, color: "#c5bd9f", fontSize: 14 }}>
        <span>ORIGINAL AUDIO</span>
        <span style={{ color: accent }}>BLEEPED</span>
      </div>
    </div>
  );
}

export function createProjectOgImage(project: Project) {
  const { label, title, description, accent } = projects[project];

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "56px 62px",
          color: "#f5f4ed",
          background: "linear-gradient(125deg, #14221f 0%, #171b25 100%)",
          fontFamily: "Arial",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", width: 570 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 21, fontWeight: 700 }}>
            <span
              style={{
                display: "flex",
                width: 36,
                height: 36,
                alignItems: "center",
                justifyContent: "center",
                borderRadius: 10,
                color: "#14221f",
                backgroundColor: accent,
              }}
            >
              b
            </span>
            bleeper
          </div>
          <div style={{ display: "flex", marginTop: 64, color: accent, fontSize: 15, letterSpacing: 3 }}>
            {label}
          </div>
          <div style={{ display: "flex", marginTop: 20, whiteSpace: "pre-line", fontSize: 51, lineHeight: 1.12, fontWeight: 700 }}>
            {title}
          </div>
          <div style={{ display: "flex", marginTop: 22, color: "#b8c2bd", fontSize: 20 }}>
            {description}
          </div>
          <div style={{ display: "flex", marginTop: 48, color: "#87958f", fontSize: 15 }}>
            dhwani.site
          </div>
        </div>
        <Artwork project={project} accent={accent} />
      </div>
    ),
    { width: 1200, height: 630 },
  );
}
