"""
TTS voiceover generation and video+audio muxing for the nuScenes pipeline.
Reuses the same gTTS → pydub → moviepy stack as the AdaptTrust CARLA synthesizer.

Each explanation window gets one TTS clip placed at the start of its video time range.
If a clip is longer than the window, it plays into the next window (never cut short).
Clips never overlap — if a previous clip is still running, the next one is shifted.
"""

import os
import tempfile
import time
import logging

import numpy as np
from scipy.io import wavfile

from config import FPS_OUTPUT

log = logging.getLogger(__name__)

SAMPLE_RATE  = 44_100   # Hz — must match what pydub resamples to
VOICE_VOLUME = 1.0


def _tts_to_array(text: str) -> np.ndarray | None:
    """
    Synthesise text via gTTS → float32 mono array at SAMPLE_RATE.
    Returns None on failure so the caller can continue without audio.
    """
    try:
        from gtts import gTTS
        from pydub import AudioSegment
    except ImportError as exc:
        log.warning("gTTS / pydub not installed (%s) — no voice", exc)
        return None

    tmp_mp3 = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_mp3 = f.name

        gTTS(text=text, lang="en", slow=False, tld="co.uk").save(tmp_mp3)

        seg = (AudioSegment.from_mp3(tmp_mp3)
               .set_frame_rate(SAMPLE_RATE)
               .set_channels(1))
        os.unlink(tmp_mp3)
        tmp_mp3 = None

        arr = np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0
        return arr * VOICE_VOLUME

    except Exception as exc:
        log.warning("TTS failed (%s) — clip skipped", exc)
        if tmp_mp3 and os.path.exists(tmp_mp3):
            os.unlink(tmp_mp3)
        return None


def build_voice_track(
    explanations: list[dict],
    frame_to_window_map: dict[int, int],
    total_frames: int,
    explanation_type: str,
    fps: int = FPS_OUTPUT,
) -> np.ndarray:
    """
    Build a mono float32 audio track aligned to the output video.

    Each explanation window's clip is placed at its window start time.
    If a previous clip is still speaking, the next clip waits — never overlaps.

    Returns a float32 array of length int(video_duration_s * SAMPLE_RATE).
    """
    video_dur_s = total_frames / fps
    n_samples   = int(video_dur_s * SAMPLE_RATE)
    track       = np.zeros(n_samples, dtype=np.float32)
    next_free_s = 0.0

    # Build window_index → start time in seconds mapping
    window_start_s: dict[int, float] = {}
    for frame_idx, win_idx in frame_to_window_map.items():
        if win_idx not in window_start_s:
            window_start_s[win_idx] = frame_idx / fps

    for exp in sorted(explanations, key=lambda e: e["window_index"]):
        win_idx = exp["window_index"]
        text    = exp.get(explanation_type, "").strip()

        if not text:
            continue

        clip = _tts_to_array(text)
        if clip is None:
            continue

        clip_dur_s = len(clip) / SAMPLE_RATE
        ideal_start = window_start_s.get(win_idx, 0.0)

        # Never overlap the previous clip
        start_s = max(ideal_start, next_free_s)

        if start_s >= video_dur_s:
            log.info("Window %d: no room left in video — skipping", win_idx)
            continue

        start_sample = int(start_s * SAMPLE_RATE)
        end_sample   = min(start_sample + len(clip), n_samples)
        clip_len     = end_sample - start_sample
        track[start_sample:end_sample] += clip[:clip_len]

        next_free_s = start_s + clip_dur_s
        log.info(
            "Window %d [%s]: placed %.2f s clip @ %.2f s → %.2f s  \"%s\"",
            win_idx, explanation_type, clip_dur_s, start_s, next_free_s,
            text[:60] + ("…" if len(text) > 60 else ""),
        )

    return np.clip(track, -1.0, 1.0)


def mux_audio_to_video(
    video_path: str,
    voice_track: np.ndarray,
    output_path: str,
) -> None:
    """
    Write voice_track as WAV then mux it into video_path via moviepy.
    Writes to a temp file first then renames to avoid corrupting the source.
    """
    try:
        from moviepy import VideoFileClip, AudioFileClip
    except ImportError as exc:
        log.error("moviepy not installed (%s) — cannot add audio", exc)
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name
    wavfile.write(tmp_wav, SAMPLE_RATE, (voice_track * 32767).astype(np.int16))

    tmp_mp4 = video_path + ".tmp.mp4"
    try:
        clip  = VideoFileClip(video_path)
        audio = AudioFileClip(tmp_wav).subclipped(0, clip.duration)
        (clip.with_audio(audio)
             .write_videofile(tmp_mp4, codec="libx264", audio_codec="aac", logger=None))
        clip.close()
        os.replace(tmp_mp4, output_path)
    finally:
        os.unlink(tmp_wav)
        if os.path.exists(tmp_mp4):
            os.unlink(tmp_mp4)


def add_voice_to_video(
    video_path: str,
    explanations: list[dict],
    frame_to_window_map: dict[int, int],
    total_frames: int,
    explanation_type: str,
    fps: int = FPS_OUTPUT,
) -> None:
    """
    Top-level call: build voice track for `explanation_type` and mux into video_path.
    """
    print(f"  Generating TTS voice track for {explanation_type}...")
    t0    = time.perf_counter()
    track = build_voice_track(
        explanations, frame_to_window_map, total_frames, explanation_type, fps
    )
    print(f"  TTS done in {time.perf_counter() - t0:.1f}s — muxing audio...")
    mux_audio_to_video(video_path, track, video_path)
    print(f"  Audio muxed into {video_path}")
