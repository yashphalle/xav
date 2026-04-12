"""
scripts/audio_pipeline/siren_audio.py
Distance-modulated ambulance siren for S4_EmergencyVehiclePullOver.

HOW DISTANCE MODULATION WORKS
──────────────────────────────
Every audio sample has a corresponding ambulance-to-ego distance, linearly
interpolated from npc_telemetry.json (ambulance x,y vs ego x,y per sim frame).
That distance is mapped to an amplitude envelope:

    distance ≥ MAX_DIST (80 m)  →  amplitude = 0.0  (silent)
    distance ≤ MIN_DIST (6 m)   →  amplitude = 1.0  (full volume)
    in between                  →  linear ramp

The siren waveform (loop WAV or synthesized fallback) is multiplied
sample-by-sample by this envelope.  Result: the siren naturally rises
as the ambulance closes in from ~50 m, peaks when it passes, then
fades as it drives away — without any additional code.

SAMPLE-BASED MODE  (preferred — sounds like a real siren)
──────────────────────────────────────────────────────────
Run once to generate the siren loop WAV:
    python scripts/audio_pipeline/setup_siren_sample.py

That uses SoX to write a seamless 1.4 s square-wave wail loop to
    xav/assets/siren/siren_loop.wav

At runtime this module loads the loop and repeats it to fill the video
duration, then applies the distance-amplitude envelope per sample.

SYNTHESIZED FALLBACK  (no WAV needed — but sounds more "pure tone")
────────────────────────────────────────────────────────────────────
If siren_loop.wav is missing, falls back to scipy.signal.chirp
(sine sweep, correct frequency arc, no harmonics).

Public API:
    build_siren_track(telemetry, npc_telemetry, video_dur_s, sim_dur_s)
    → float32 mono array, length = int(video_dur_s × SAMPLE_RATE)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from scipy.io import wavfile

log = logging.getLogger(__name__)

SAMPLE_RATE  = 44_100   # Hz — must match synthesizer.SAMPLE_RATE
SIREN_VOL    = 0.07     # peak volume relative to 1.0

# Siren frequency sweep (matches setup_siren_sample.py)
F_LO         = 700.0    # Hz — low tone
F_HI         = 1050.0   # Hz — high tone
SWEEP_PERIOD = 1.4      # seconds for one full lo→hi→lo cycle

# Distance attenuation thresholds
MAX_DIST = 80.0   # m — silent beyond this
MIN_DIST = 6.0    # m — full volume within this


# ── Distance helpers ───────────────────────────────────────────────────────────

def _ambulance_distances(
    telemetry:     list[dict],
    npc_telemetry: list[list[dict]],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (sim_times, distances) arrays — one value per sim frame.

    Searches each NPC frame for an actor whose type contains "ambulance";
    falls back to index=0 (always the ambulance in S4) if none found.
    Missing frames get distance = MAX_DIST + 1 → silent.
    """
    n      = len(telemetry)
    times  = np.array([f["elapsed_s"] for f in telemetry], dtype=np.float64)
    ego_x  = np.array([f["x"]         for f in telemetry], dtype=np.float64)
    ego_y  = np.array([f["y"]         for f in telemetry], dtype=np.float64)
    dists  = np.full(n, MAX_DIST + 1.0, dtype=np.float64)

    for i, npc_frame in enumerate(npc_telemetry[:n]):
        if not npc_frame:
            continue

        # Prefer actor whose type contains "ambulance"
        amb = next(
            (a for a in npc_frame if "ambulance" in a.get("actor_type", "").lower()),
            None,
        )
        # Fall back to index=0 (first spawned NPC — always the ambulance in S4)
        if amb is None:
            amb = next((a for a in npc_frame if a.get("index") == 0), None)
        if amb is None:
            continue

        dx = amb["x"] - ego_x[i]
        dy = amb["y"] - ego_y[i]
        dists[i] = np.sqrt(dx * dx + dy * dy)

    return times, dists


def _dist_to_amp(dist: np.ndarray) -> np.ndarray:
    """
    Map distance array (metres) → amplitude array [0.0, 1.0].
    Linear: 1.0 at MIN_DIST, 0.0 at MAX_DIST and beyond.
    """
    clamped = np.clip(dist, MIN_DIST, MAX_DIST)
    return (1.0 - (clamped - MIN_DIST) / (MAX_DIST - MIN_DIST)).astype(np.float32)


# ── Waveform sources ───────────────────────────────────────────────────────────

def _load_siren_wav(assets_dir: Path) -> np.ndarray | None:
    """
    Load siren_loop.wav from assets_dir as float32 mono at SAMPLE_RATE.
    Returns None if the file is missing or unreadable.
    """
    wav_path = assets_dir / "siren_loop.wav"
    if not wav_path.exists():
        log.info("Siren WAV not found at %s — using synthesized fallback", wav_path)
        log.info("  → Run:  python scripts/audio_pipeline/setup_siren_sample.py")
        return None

    try:
        sr, data = wavfile.read(str(wav_path))

        if data.ndim > 1:
            data = data.mean(axis=1)

        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2_147_483_648.0
        else:
            data = data.astype(np.float32)

        if sr != SAMPLE_RATE:
            from scipy.signal import resample
            n_new = int(len(data) * SAMPLE_RATE / sr)
            data  = resample(data, n_new).astype(np.float32)
            log.debug("Siren WAV resampled %d → %d Hz", sr, SAMPLE_RATE)

        peak = np.max(np.abs(data))
        if peak > 1e-6:
            data /= peak

        log.info("Siren WAV loaded: %.3f s loop (%d samples)",
                 len(data) / SAMPLE_RATE, len(data))
        return data

    except Exception as exc:
        log.warning("Could not load siren WAV (%s) — using synthesized fallback", exc)
        return None


def _loop_wav(loop: np.ndarray, n_out: int) -> np.ndarray:
    """Repeat *loop* as many times as needed to fill *n_out* samples, then trim."""
    repeats = n_out // len(loop) + 2
    return np.tile(loop, repeats)[:n_out]


def _synth_siren(n_out: int) -> np.ndarray:
    """
    Synthesized fallback: scipy chirp sine sweep lo→hi→lo.
    Less realistic than the square-wave WAV but pure Python.
    """
    from scipy.signal import chirp

    half = int(SWEEP_PERIOD / 2 * SAMPLE_RATE)
    t_half = np.linspace(0.0, SWEEP_PERIOD / 2, half, endpoint=False)

    up   = chirp(t_half, f0=F_LO, f1=F_HI, t1=SWEEP_PERIOD / 2, method="linear").astype(np.float32)
    down = chirp(t_half, f0=F_HI, f1=F_LO, t1=SWEEP_PERIOD / 2, method="linear").astype(np.float32)
    one_cycle = np.concatenate([up, down])

    return _loop_wav(one_cycle, n_out)


# ── Public API ─────────────────────────────────────────────────────────────────

def build_siren_track(
    telemetry:     list[dict],
    npc_telemetry: list[list[dict]],
    video_dur_s:   float,
    sim_dur_s:     float,
    assets_dir:    Path | None = None,
) -> np.ndarray:
    """
    Build a distance-modulated ambulance siren track timed to VIDEO duration.

    Args:
        telemetry:     ego frame dicts from telemetry.json
        npc_telemetry: per-frame NPC lists from npc_telemetry.json
        video_dur_s:   actual video playback duration (seconds)
        sim_dur_s:     simulation duration (seconds)
        assets_dir:    folder containing siren_loop.wav.
                       Defaults to  xav/assets/siren/

    Returns:
        float32 mono array of length int(video_dur_s × SAMPLE_RATE).
    """
    if assets_dir is None:
        assets_dir = Path(__file__).resolve().parents[2] / "assets" / "siren"

    n_out      = int(video_dur_s * SAMPLE_RATE)
    time_scale = video_dur_s / sim_dur_s

    # ── Per-frame ambulance distance ─────────────────────────────────────────
    sim_times, sim_dists = _ambulance_distances(telemetry, npc_telemetry)

    visible = sim_dists[sim_dists < MAX_DIST + 1.0]
    if visible.size:
        log.info("Siren: ambulance distance range %.1f m – %.1f m over %d frames",
                 float(visible.min()), float(visible.max()), len(sim_dists))
    else:
        log.warning("Siren: no ambulance actor found in npc_telemetry — track will be silent")

    # ── Interpolate distance to audio sample grid (video-time) ──────────────
    # Map sim timestamps → video timestamps, then interpolate dist per audio sample
    video_times = sim_times * time_scale
    t_audio     = np.linspace(0.0, video_dur_s, n_out)
    dist_audio  = np.interp(t_audio, video_times, sim_dists).astype(np.float32)

    # ── Distance → amplitude envelope (per sample) ──────────────────────────
    amp = _dist_to_amp(dist_audio)   # shape (n_out,), values in [0, 1]

    # ── Siren waveform: WAV loop or synthesized fallback ─────────────────────
    loop = _load_siren_wav(assets_dir)
    if loop is not None:
        wave = _loop_wav(loop, n_out)
        log.info("Mode: SAMPLE-BASED (siren_loop.wav)")
    else:
        wave = _synth_siren(n_out)
        log.info("Mode: SYNTHESIZED FALLBACK (scipy chirp)")

    # ── Apply per-sample amplitude envelope + master volume ──────────────────
    wave = wave * amp * SIREN_VOL

    # Soft-clip — prevents clipping when mixed with engine + voiceover
    wave = np.tanh(wave).astype(np.float32)

    pct_audible = int(100.0 * float(np.mean(amp > 0.05)))
    log.info("Siren track done: peak=%.3f  audible=%d%%  (n=%d, %.2f s)",
             float(np.max(np.abs(wave))), pct_audible, n_out, video_dur_s)

    return wave
