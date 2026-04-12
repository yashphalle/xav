"""
scripts/audio_pipeline/synthesizer.py
Engine-noise synthesis + TTS voiceover + video muxing for AdaptTrust scenarios.

THE CORE TIMING PROBLEM (and fix)
──────────────────────────────────
The simulation runs at 20 Hz, but recorder.py writes each sim frame to video
at 30 fps.  Both produce the same number of frames (e.g. 401), but the video
plays them faster:

    sim  : 401 frames × (1/20 s) = 20.05 s of real action
    video: 401 frames ÷  30 fps  = 13.37 s of playback

    time_scale = video_duration / sim_duration = 13.37 / 20.05 ≈ 0.667 (= 20/30)

Every sim timestamp must be multiplied by time_scale before being used as a
position in the audio/video timeline.  Failing to do this shifts TTS clips
≈ 2–3 s late and pushes the second event entirely beyond the video end.

Audio stream 1 — Engine:
    Built to exactly video_duration_s samples.  The sim telemetry (elapsed_s)
    is resampled over [0, video_duration_s] so the engine pitch and amplitude
    track correctly even though the time axes are different.

Audio stream 2 — Voiceover (TTS):
    Each clip is placed at  (trigger_elapsed_s − DISPLAY_BEFORE_S) × time_scale
    in video-time coordinates, which is exactly when overlay.py first shows the
    explanation text on screen.

Public API:
    add_audio_to_videos(scenario_dir)   ← called by adaptrust_runner.py
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.io import wavfile

from .engine_audio import build_engine_track as _build_engine_track

log = logging.getLogger(__name__)

# ── Audio constants ────────────────────────────────────────────────────────────
SAMPLE_RATE = 44_100   # Hz  (must match engine_audio.SAMPLE_RATE)

# TTS voiceover
VOICEOVER_VOL = 1.0
TTS_LANG      = "en"

# Must match overlay.py — seconds of SIMULATION time shown before/after trigger
DISPLAY_BEFORE_S = 2.0
DISPLAY_AFTER_S  = 3.0

# Conditions to process (must match overlay.CONDITIONS)
CONDITIONS = ["none", "descriptive", "teleological"]


# ── Timing helpers ─────────────────────────────────────────────────────────────

def _get_video_properties(video_path: Path) -> tuple[float, float, int]:
    """
    Return (fps, duration_s, frame_count) from a video file using cv2.
    Raises RuntimeError if the file cannot be opened.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps         = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    duration_s = frame_count / fps
    return fps, duration_s, frame_count


def _log_timing_table(
    telemetry:      list[dict],
    action_events:  list[dict],
    explanations:   list[dict],
    video_fps:      float,
    video_dur:      float,
    sim_dur:        float,
    time_scale:     float,
    condition:      str,
) -> None:
    """
    Write a full timing audit table to the log so sync issues are immediately
    visible.  Shows every second of video time alongside its sim time, speed,
    and action state; then an event-level breakdown with exact sample positions.
    """
    log.info("")
    log.info("┌─ TIMING TABLE: condition=%s ─────────────────────────────────────┐", condition)
    log.info("│  Sim duration : %6.3f s @ ~%.0f Hz (%d frames)",
             sim_dur, len(telemetry) / sim_dur, len(telemetry))
    log.info("│  Video        : %6.3f s @ %.0f fps  (scale %.6f)",
             video_dur, video_fps, time_scale)
    log.info("│")
    log.info("│  video_t  sim_t   speed     throttle  brake    state")
    log.info("│  ──────── ──────  ────────  ────────  ──────   ──────────────")

    times    = [e["elapsed_s"]  for e in telemetry]
    speeds   = [e["speed_kmh"]  for e in telemetry]
    throttles= [e["throttle"]   for e in telemetry]
    brakes   = [e["brake"]      for e in telemetry]

    step = 0.5   # log every 0.5 s of video time
    t_vid = 0.0
    while t_vid <= video_dur + 0.01:
        t_sim   = t_vid / time_scale
        spd     = float(np.interp(t_sim, times, speeds))
        thr     = float(np.interp(t_sim, times, throttles))
        brk     = float(np.interp(t_sim, times, brakes))
        if brk > 0.30:
            state = "BRAKING"
        elif thr > 0.50:
            state = "ACCELERATING"
        else:
            state = "cruising"
        log.info("│  %6.2f s  %5.2f s  %5.1f km/h  %5.2f     %5.2f    %s",
                 t_vid, t_sim, spd, thr, brk, state)
        t_vid += step

    log.info("│")
    log.info("│  EVENT SYNC AUDIT")
    log.info("│  ─────────────────────────────────────────────────────────────")

    expl_map = {e["event_index"]: e.get("explanation", "") for e in explanations}

    for i, ev in enumerate(action_events):
        snap            = ev["telemetry_snapshot"]
        trig_sim        = snap["elapsed_s"]
        trig_vid        = trig_sim * time_scale
        text_start_vid  = max(0.0, trig_vid - DISPLAY_BEFORE_S * time_scale)
        text_end_vid    = min(video_dur, trig_vid + DISPLAY_AFTER_S * time_scale)
        text_dur_vid    = text_end_vid - text_start_vid

        text = expl_map.get(i, "")

        log.info("│")
        log.info("│  event[%d]  %s", i, ev["trigger_type"])
        log.info("│    sim trigger    : %.3f s  (speed=%.1f km/h  brake=%.2f)",
                 trig_sim, snap["speed_kmh"], snap["brake"])
        log.info("│    video trigger  : %.3f s  (= %.3f × %.6f)", trig_vid, trig_sim, time_scale)
        log.info("│    text window    : %.3f s → %.3f s  (%.2f s, video time)",
                 text_start_vid, text_end_vid, text_dur_vid)

        if not text.strip():
            log.info("│    TTS            : — (empty explanation, condition=%s)", condition)
        else:
            log.info("│    TTS start      : %.3f s  (= text_start, video time)", text_start_vid)
            log.info("│    TTS text       : \"%s\"",
                     text[:70] + ("…" if len(text) > 70 else ""))
            tts_start_sample = int(text_start_vid * SAMPLE_RATE)
            log.info("│    TTS sample pos : %d  (@ %.1f Hz)", tts_start_sample, SAMPLE_RATE)

    log.info("└──────────────────────────────────────────────────────────────────┘")
    log.info("")


# ── TTS generation ─────────────────────────────────────────────────────────────

def _tts_to_array(text: str) -> np.ndarray | None:
    """
    Synthesise *text* via gTTS → float32 mono array at SAMPLE_RATE.
    Returns None on any failure so callers can continue gracefully.
    """
    try:
        from gtts import gTTS
        from pydub import AudioSegment
    except ImportError as exc:
        log.warning("gTTS / pydub unavailable (%s)", exc)
        return None

    tmp_mp3 = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_mp3 = f.name

        t0 = time.perf_counter()
        gTTS(text=text, lang=TTS_LANG, slow=False, tld="co.uk").save(tmp_mp3)
        log.debug("gTTS: %d chars → %.2f s", len(text), time.perf_counter() - t0)

        seg = (AudioSegment.from_mp3(tmp_mp3)
               .set_frame_rate(SAMPLE_RATE)
               .set_channels(1))
        os.unlink(tmp_mp3)
        tmp_mp3 = None

        arr = np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0
        log.debug("TTS clip duration: %.3f s (%d samples)", len(arr) / SAMPLE_RATE, len(arr))
        return arr * VOICEOVER_VOL

    except Exception as exc:
        log.warning("TTS failed (%s) — clip skipped", exc)
        if tmp_mp3 and os.path.exists(tmp_mp3):
            os.unlink(tmp_mp3)
        return None


def build_voiceover_track(
    action_events:  list[dict],
    explanations:   list[dict],
    video_dur_s:    float,
    time_scale:     float,
) -> np.ndarray:
    """
    Build a mono voiceover track — one TTS clip per event, but never overlapping.

    Each clip is RIGHT-ALIGNED so it finishes exactly at the trigger time.
    That way the explanation is fully spoken before the vehicle action fires.

    If the previous clip is still speaking when this clip would need to start,
    the clip is shifted to start right after the previous one ends (left-aligned
    from next_free_s).

    Returns float32 mono array of length int(video_dur_s × SAMPLE_RATE).
    """
    n_samples    = int(video_dur_s * SAMPLE_RATE)
    track        = np.zeros(n_samples, dtype=np.float32)
    next_free_s  = 0.0   # earliest video-time at which a new clip can start
    clips_placed = 0

    sorted_expls = sorted(explanations, key=lambda e: e.get("event_index", 999))

    for expl in sorted_expls:
        text   = expl.get("explanation", "").strip()
        ev_idx = expl.get("event_index", -1)

        if not text:
            log.info("  event[%s] %-20s  empty — skip",
                     ev_idx, expl.get("trigger_type", "?"))
            continue
        if ev_idx < 0 or ev_idx >= len(action_events):
            log.warning("  event[%s] out of range — skip", ev_idx)
            continue

        ev         = action_events[ev_idx]
        trig_sim_s = ev["telemetry_snapshot"]["elapsed_s"]
        trig_vid_s = trig_sim_s * time_scale

        # Generate TTS first so we know clip duration
        tts_arr = _tts_to_array(text)
        if tts_arr is None:
            log.warning("  TTS failed for event[%d] — skipping", ev_idx)
            continue

        clip_dur_s = len(tts_arr) / SAMPLE_RATE

        # Use explicit start override if set (e.g. L3 event 0 waits for the turn)
        if "audio_start_s" in expl:
            tts_start_vid = float(expl["audio_start_s"])
        else:
            # Default: right-align so clip ends at trigger fire time
            tts_end_vid   = trig_vid_s
            tts_start_vid = max(0.0, tts_end_vid - clip_dur_s)

        if tts_start_vid < next_free_s:
            # Previous clip still speaking — shift this one to start right after
            if next_free_s >= video_dur_s:
                log.info("  event[%d] %-20s  SKIPPED (no room left in video)",
                         ev_idx, expl.get("trigger_type", "?"))
                continue
            log.info("  event[%d] %-20s  SHIFTED %.2f s → %.2f s (prev clip still speaking)",
                     ev_idx, expl.get("trigger_type", "?"), tts_start_vid, next_free_s)
            tts_start_vid = next_free_s

        log.info("  event[%d] %-20s  VOICING @ video %.2f s (ends %.2f s, trigger %.2f s) — \"%s\"",
                 ev_idx, expl.get("trigger_type", "?"),
                 tts_start_vid, tts_start_vid + clip_dur_s, trig_vid_s,
                 text[:55] + ("…" if len(text) > 55 else ""))

        start_sample = int(tts_start_vid * SAMPLE_RATE)
        end_sample   = min(start_sample + len(tts_arr), n_samples)
        clip_len     = end_sample - start_sample
        track[start_sample:end_sample] += tts_arr[:clip_len]

        next_free_s = tts_start_vid + clip_dur_s
        clips_placed += 1
        log.info("    placed %.2f s clip, next slot free at %.2f s",
                 clip_dur_s, next_free_s)

    log.info("Voiceover: %d clip(s) placed  (video_dur=%.3f s)", clips_placed, video_dur_s)
    return np.clip(track, -1.0, 1.0)


# ── Mixing and muxing ──────────────────────────────────────────────────────────

def _fit(arr: np.ndarray, n: int) -> np.ndarray:
    """Trim or zero-pad *arr* to exactly *n* samples."""
    if len(arr) >= n:
        return arr[:n]
    return np.pad(arr, (0, n - len(arr)))


def mix_and_render(
    video_path:  str | Path,
    engine_arr:  np.ndarray,
    voice_arr:   np.ndarray,
    output_path: str | Path,
) -> None:
    """
    Mix engine + voice, attach to video, write output.
    Safe in-place update: writes to *.tmp.mp4 then renames.
    """
    try:
        from moviepy import VideoFileClip, AudioFileClip
    except ImportError as exc:
        log.error("moviepy unavailable (%s) — cannot mux audio", exc)
        return

    video_path  = Path(video_path)
    output_path = Path(output_path)
    in_place    = video_path.resolve() == output_path.resolve()

    t0   = time.perf_counter()
    clip = VideoFileClip(str(video_path))
    n    = int(clip.duration * SAMPLE_RATE)

    log.debug("Mux: video=%.3f s  audio arrays: engine=%d  voice=%d  target=%d samples",
              clip.duration, len(engine_arr), len(voice_arr), n)

    mixed = np.clip(_fit(engine_arr, n) + _fit(voice_arr, n), -1.0, 1.0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name
    wavfile.write(tmp_wav, SAMPLE_RATE, (mixed * 32767).astype(np.int16))

    actual_out = output_path.with_suffix(".tmp.mp4") if in_place else output_path
    audio      = AudioFileClip(tmp_wav).subclipped(0, clip.duration)
    (clip.with_audio(audio)
         .write_videofile(str(actual_out), codec="libx264", audio_codec="aac", logger=None))
    clip.close()
    os.unlink(tmp_wav)

    if in_place:
        actual_out.replace(output_path)

    log.info("%s written (%.1f s)", output_path.name, time.perf_counter() - t0)


# ── Public API ─────────────────────────────────────────────────────────────────

def add_audio_to_videos(scenario_dir: str | Path) -> None:
    """
    Add speed-modulated engine noise and frame-accurate TTS voiceover to every
    overlay video in scenario_dir.

    Called automatically by adaptrust_runner.py after render_overlays().
    Logs full timing tables to  scenario_dir/audio_pipeline.log.
    """
    scenario_dir = Path(scenario_dir)

    # ── Logging setup ──────────────────────────────────────────────────────
    log_path = scenario_dir / "audio_pipeline.log"
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(fh)
    log.setLevel(logging.DEBUG)

    if not logging.root.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("[audio] %(levelname)s %(message)s"))
        logging.root.addHandler(ch)
        logging.root.setLevel(logging.INFO)

    try:
        t_total = time.perf_counter()
        log.info("=== Audio pipeline: %s ===", scenario_dir.name)

        # ── Load data ──────────────────────────────────────────────────────
        tel_path  = scenario_dir / "telemetry.json"
        ev_path   = scenario_dir / "action_events.json"
        exp_dir   = scenario_dir / "explanations"
        src_video = scenario_dir / "video.mp4"   # original capture (constant reference)

        for p in (tel_path, ev_path):
            if not p.exists():
                log.error("Missing required file: %s", p); return

        telemetry     = json.loads(tel_path.read_text())
        action_events = json.loads(ev_path.read_text())

        # ── Timing parameters ──────────────────────────────────────────────
        sim_dur_s = telemetry[-1]["elapsed_s"]
        sim_hz    = (len(telemetry) - 1) / sim_dur_s

        # Use source video (or first available overlay video) for fps/duration
        ref_video = src_video
        if not ref_video.exists():
            for cond in CONDITIONS:
                candidate = scenario_dir / f"video_{cond}.mp4"
                if candidate.exists():
                    ref_video = candidate
                    break

        if not ref_video.exists():
            log.error("No video file found in %s", scenario_dir); return

        video_fps, video_dur_s, video_frames = _get_video_properties(ref_video)
        time_scale = video_dur_s / sim_dur_s   # sim-time → video-time multiplier

        log.info("")
        log.info("TIMING PARAMETERS")
        log.info("  Simulation : %d frames @ %.2f Hz → %.4f s", len(telemetry), sim_hz, sim_dur_s)
        log.info("  Video      : %d frames @ %.2f fps → %.4f s", video_frames, video_fps, video_dur_s)
        log.info("  time_scale : %.6f  (every 1 s sim = %.4f s video)", time_scale, time_scale)
        log.info("  Cause      : recorder writes 1 frame/sim-tick (%d Hz) into a %d-fps container",
                 int(round(sim_hz)), int(round(video_fps)))
        log.info("")

        # ── Action events summary ──────────────────────────────────────────
        log.info("ACTION EVENTS  (%d total)", len(action_events))
        for i, ev in enumerate(action_events):
            snap       = ev["telemetry_snapshot"]
            trig_sim   = snap["elapsed_s"]
            trig_vid   = trig_sim * time_scale
            text_start = max(0.0, trig_vid - DISPLAY_BEFORE_S * time_scale)
            text_end   = min(video_dur_s, trig_vid + DISPLAY_AFTER_S * time_scale)
            log.info(
                "  [%d] %-20s  sim=%.3fs  video=%.3fs  "
                "text_window=[%.3fs, %.3fs]  speed=%.1fkm/h  brake=%.2f",
                i, ev["trigger_type"], trig_sim, trig_vid,
                text_start, text_end,
                snap["speed_kmh"], snap["brake"],
            )
        log.info("")

        # ── Engine audio (sample-based if WAVs exist, synthesized fallback) ──
        log.info("Building engine audio (%.3f s @ %d Hz) …", video_dur_s, SAMPLE_RATE)
        t0         = time.perf_counter()
        engine_arr = _build_engine_track(telemetry, video_dur_s, sim_dur_s)
        log.info("Engine done in %.2f s", time.perf_counter() - t0)
        log.info("")

        # ── Siren audio for S4 (distance-modulated, shared across conditions) ──
        siren_arr = np.zeros(int(video_dur_s * SAMPLE_RATE), dtype=np.float32)
        if "S4" in scenario_dir.name:
            npc_path = scenario_dir / "npc_telemetry.json"
            if npc_path.exists():
                log.info("Building siren track (S4 ambulance distance modulation) …")
                t0 = time.perf_counter()
                from .siren_audio import build_siren_track as _build_siren_track
                npc_telemetry = json.loads(npc_path.read_text())
                siren_arr = _build_siren_track(
                    telemetry, npc_telemetry, video_dur_s, sim_dur_s
                )
                log.info("Siren done in %.2f s", time.perf_counter() - t0)
            else:
                log.warning("S4 detected but npc_telemetry.json missing — no siren")
            log.info("")

        # ── Per-condition ──────────────────────────────────────────────────
        for condition in CONDITIONS:
            vid_path = scenario_dir / f"video_{condition}.mp4"
            exp_path = exp_dir / f"{condition}.json"

            if not vid_path.exists():
                log.warning("video_%s.mp4 not found — skipping", condition); continue
            if not exp_path.exists():
                log.warning("explanations/%s.json not found — skipping", condition); continue

            explanations   = json.loads(exp_path.read_text())
            non_empty      = sum(1 for e in explanations if e.get("explanation", "").strip())
            log.info("━━ Condition: %-14s  (%d/%d explanations non-empty) ━━",
                     condition, non_empty, len(explanations))

            # Full timing audit table for this condition
            _log_timing_table(
                telemetry, action_events, explanations,
                video_fps, video_dur_s, sim_dur_s, time_scale, condition,
            )

            t1        = time.perf_counter()
            voice_arr = build_voiceover_track(
                action_events, explanations, video_dur_s, time_scale
            )
            log.info("Voiceover built in %.2f s", time.perf_counter() - t1)

            t2 = time.perf_counter()
            # Pre-mix engine + siren so mix_and_render sees one background track
            bg_arr = np.clip(engine_arr + siren_arr, -1.0, 1.0)
            mix_and_render(vid_path, bg_arr, voice_arr, vid_path)
            log.info("Mix+render done in %.2f s", time.perf_counter() - t2)
            log.info("")

        log.info("=== Done: %s  (total %.1f s) ===", scenario_dir.name,
                 time.perf_counter() - t_total)
        log.info("Full log: %s", log_path)

    finally:
        log.removeHandler(fh)
        fh.close()
