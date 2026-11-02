import csv
import json
import math
import subprocess
from fractions import Fraction
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
                    "format=duration:stream=duration,duration_ts,time_base",
                    "-of",
                    "json",
                    str(media_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            probe_data = json.loads(result.stdout)
        except FileNotFoundError as error:
            raise MediaProbeError("ffprobe is not installed on the server.") from error
        except (subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise MediaProbeError(
                "The uploaded file is not a supported media file."
            ) from error

        duration = self._metadata_duration(probe_data)
        if duration is None:
            duration = self._packet_duration(media_path)
        if duration <= 0:
            raise MediaProbeError("The uploaded media has an invalid duration.")
        return duration

    @staticmethod
    def _metadata_duration(probe_data: dict[str, object]) -> float | None:
        format_data = probe_data.get("format")
        if isinstance(format_data, dict):
            duration = MediaProbeService._finite_float(format_data.get("duration"))
            if duration is not None and duration > 0:
                return duration

        streams = probe_data.get("streams")
        if isinstance(streams, list):
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                duration = MediaProbeService._finite_float(stream.get("duration"))
                if duration is not None and duration > 0:
                    return duration

                duration_ts = MediaProbeService._finite_float(
                    stream.get("duration_ts")
                )
                time_base = stream.get("time_base")
                if duration_ts is not None and isinstance(time_base, str):
                    try:
                        duration = duration_ts * float(Fraction(time_base))
                    except (ValueError, ZeroDivisionError):
                        continue
                    if math.isfinite(duration) and duration > 0:
                        return duration
        return None

    @staticmethod
    def _finite_float(value: object) -> float | None:
        if not isinstance(value, (str, int, float)):
            return None
        try:
            result = float(value)
        except ValueError:
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _packet_duration(media_path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_packets",
                    "-show_entries",
                    "packet=pts_time,duration_time",
                    "-of",
                    "csv=p=0",
                    str(media_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as error:
            raise MediaProbeError("ffprobe is not installed on the server.") from error
        except (subprocess.SubprocessError, ValueError) as error:
            raise MediaProbeError(
                "The uploaded file is not a supported media file."
            ) from error

        first_timestamp: float | None = None
        last_timestamp: float | None = None
        for row in csv.reader(result.stdout.splitlines()):
            if not row:
                continue
            timestamp = MediaProbeService._finite_float(row[0])
            if timestamp is None:
                continue
            packet_duration = (
                MediaProbeService._finite_float(row[1]) if len(row) > 1 else None
            )
            packet_end = timestamp + (packet_duration or 0)
            first_timestamp = (
                timestamp
                if first_timestamp is None
                else min(first_timestamp, timestamp)
            )
            last_timestamp = (
                packet_end if last_timestamp is None else max(last_timestamp, packet_end)
            )

        if first_timestamp is None or last_timestamp is None:
            raise MediaProbeError("The uploaded file is not a supported media file.")
        return last_timestamp - first_timestamp
