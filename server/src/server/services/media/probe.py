import subprocess
from pathlib import Path


class MediaProbeError(RuntimeError):
    pass


class MediaProbeService:
    def duration_seconds(self, media_path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(media_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            duration = float(result.stdout.strip())
        except FileNotFoundError as error:
            raise MediaProbeError("ffprobe is not installed on the server.") from error
        except (subprocess.SubprocessError, ValueError) as error:
            raise MediaProbeError(
                "The uploaded file is not a supported media file."
            ) from error

        if duration <= 0:
            raise MediaProbeError("The uploaded media has an invalid duration.")
        return duration
