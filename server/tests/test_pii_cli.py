import json
from pathlib import Path

import pytest

from server.config import Settings
from server.domain.schemas import WordTiming
from server.services.processing import pii_cli

_SYNTHETIC_CARD = "7992739871300"
_SPOKEN_CARD = "seven nine nine two seven three nine eight seven one three zero zero"


def test_cli_runs_redaction_and_writes_all_outputs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    source = tmp_path / "synthetic.wav"
    source.write_bytes(b"synthetic-original-audio")
    output_directory = tmp_path / "redacted"
    renderer_options = {}
    speech_to_text_calls = []

    class FakeAudioExtractor:
        def extract(self, input_path: Path, output_path: Path) -> None:
            assert input_path == source
            output_path.write_bytes(b"synthetic-normalized-audio")

    class FakeSpeechToText:
        def transcribe(self, audio_path: Path) -> str:
            if audio_path.read_bytes() == b"synthetic-normalized-audio":
                transcript = _SPOKEN_CARD
            else:
                transcript = ""
            speech_to_text_calls.append(transcript)
            return transcript

    class FakeWordAligner:
        def align(self, _audio_path: Path, transcript: str) -> list[WordTiming]:
            return [
                WordTiming(
                    word=word,
                    start_seconds=index * 0.1,
                    end_seconds=(index + 1) * 0.1,
                )
                for index, word in enumerate(transcript.split())
            ]

    class FakeRenderer:
        def render_audio(
            self,
            _audio_path,
            spans,
            output_path: Path,
            *,
            duration_seconds: float,
            mode: str,
            margin_seconds: float,
        ) -> Path:
            renderer_options.update(
                categories=[span.category for span in spans],
                duration=duration_seconds,
                mode=mode,
                margin=margin_seconds,
            )
            output_path.write_bytes(b"synthetic-redacted-audio")
            return output_path

    monkeypatch.setattr(
        pii_cli,
        "get_settings",
        lambda: Settings(max_audio_duration_seconds=30),
    )
    monkeypatch.setattr(
        pii_cli.MediaProbeService,
        "duration_seconds",
        lambda _self, _path: 3.0,
    )
    monkeypatch.setattr(pii_cli, "FfmpegAudioExtractor", FakeAudioExtractor)
    monkeypatch.setattr(
        pii_cli,
        "create_speech_to_text_provider",
        lambda _settings, **_kwargs: FakeSpeechToText(),
    )
    monkeypatch.setattr(
        pii_cli,
        "create_word_aligner",
        lambda *_args, **_kwargs: FakeWordAligner(),
    )
    monkeypatch.setattr(pii_cli, "FfmpegBleepRenderer", FakeRenderer)

    exit_code = pii_cli.main(
        [
            str(source),
            "--output-dir",
            str(output_directory),
            "--mode",
            "silence",
            "--margin-ms",
            "100",
        ]
    )

    assert exit_code == 0
    assert renderer_options == {
        "categories": ["CARD"],
        "duration": 3.0,
        "mode": "silence",
        "margin": 0.1,
    }
    assert speech_to_text_calls == [_SPOKEN_CARD, ""]
    assert (output_directory / "redacted_audio.wav").read_bytes() == (
        b"synthetic-redacted-audio"
    )
    transcript = (output_directory / "redacted_transcript.txt").read_text(
        encoding="utf-8"
    )
    audit_text = (output_directory / "audit.json").read_text(encoding="utf-8")
    audit = json.loads(audit_text)
    assert transcript == "[CARD]"
    assert _SYNTHETIC_CARD not in transcript
    assert _SYNTHETIC_CARD not in audit_text
    assert audit["verification"]["pii_recall"] == 1.0
    assert "Redacted audio:" in capsys.readouterr().out


def test_cli_returns_error_for_missing_input(capsys, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        pii_cli.main([str(tmp_path / "missing.wav")])

    assert error.value.code == 2
    assert "Input audio does not exist" in capsys.readouterr().err
