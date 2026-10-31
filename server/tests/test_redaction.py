from pathlib import Path

import pytest

from server.domain.schemas import DetectionSpan
from server.services.processing import local_processing
from server.services.processing.redaction import prepare_redaction_intervals


def _span(start: float, end: float) -> DetectionSpan:
    return DetectionSpan(
        category="CARD",
        first_word_idx=0,
        last_word_idx=1,
        start=start,
        end=end,
        confidence=0.99,
        validator_result=True,
    )


def test_prepare_redaction_intervals_pads_clips_and_merges() -> None:
    intervals = prepare_redaction_intervals(
        [(0.02, 0.2), (0.32, 0.5), (1.0, 1.2)],
        duration_seconds=2.0,
    )

    assert intervals == ((0.0, 0.58), (0.92, 1.28))


@pytest.mark.parametrize(
    ("intervals", "duration", "margin", "merge_gap"),
    [
        ([(1.0, 0.5)], 2.0, 0.08, 0.15),
        ([(0.0, 0.5)], 0.0, 0.08, 0.15),
        ([(0.0, 0.5)], 2.0, -0.01, 0.15),
        ([(0.0, 0.5)], 2.0, 0.08, -0.01),
    ],
)
def test_prepare_redaction_intervals_rejects_invalid_values(
    intervals, duration: float, margin: float, merge_gap: float
) -> None:
    with pytest.raises(ValueError):
        prepare_redaction_intervals(
            intervals,
            duration_seconds=duration,
            margin_seconds=margin,
            merge_gap_seconds=merge_gap,
        )


@pytest.mark.parametrize("mode", ["beep", "silence"])
def test_audio_renderer_applies_margin_fades_and_selected_mode(
    monkeypatch, tmp_path: Path, mode: str
) -> None:
    captured = {}

    def fake_run_ffmpeg(arguments, step):
        captured.update(arguments=arguments, step=step)

    monkeypatch.setattr(local_processing, "_run_ffmpeg", fake_run_ffmpeg)
    renderer = local_processing.FfmpegBleepRenderer()
    result = renderer.render_audio(
        tmp_path / "source.wav",
        [_span(0.5, 1.0), _span(1.2, 1.5)],
        tmp_path / "redacted.wav",
        duration_seconds=3.0,
        mode=mode,
    )

    assert result == tmp_path / "redacted.wav"
    assert captured["step"] == "audio redaction"
    filters = captured["arguments"][captured["arguments"].index("-filter_complex") + 1]
    assert "between(t,0.420000,1.580000)" in filters
    if mode == "beep":
        assert filters.count("sine=frequency=1000") == 1
        assert filters.count("afade=") == 2
        assert "afade=t=in:st=0:d=0.005000" in filters
        assert "afade=t=out:st=1.155000:d=0.005000" in filters
    else:
        assert "sine=frequency=1000" not in filters
        assert filters.endswith("[clean]anull[aout]")


def test_audio_renderer_does_not_render_tone_when_there_are_no_spans(
    monkeypatch, tmp_path: Path
) -> None:
    captured = {}
    monkeypatch.setattr(
        local_processing,
        "_run_ffmpeg",
        lambda arguments, step: captured.update(arguments=arguments, step=step),
    )

    local_processing.FfmpegBleepRenderer().render_audio(
        tmp_path / "source.wav",
        [],
        tmp_path / "redacted.wav",
        duration_seconds=1.0,
    )

    assert "-filter_complex" not in captured["arguments"]
    assert captured["arguments"][-3:] == [
        "-c:a",
        "pcm_s16le",
        str(tmp_path / "redacted.wav"),
    ]


def test_audio_renderer_rejects_fade_outside_supported_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0.005 and 0.01"):
        local_processing.FfmpegBleepRenderer().render_audio(
            tmp_path / "source.wav",
            [_span(0.1, 0.2)],
            tmp_path / "redacted.wav",
            duration_seconds=1.0,
            fade_seconds=0.02,
        )
