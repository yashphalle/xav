"""
scripts/audio_pipeline/engine_audio.py
Speed-modulated engine audio — sample-based (preferred) or synthesized (fallback).

SAMPLE-BASED MODE  (sounds like a real car)
────────────────────────────────────────────
Run once to generate the loop WAVs:
    python scripts/audio_pipeline/setup_engine_samples.py

That builds enginesound (Rust) and writes 7 seamless WAV loops to
    xav/assets/engine/engine_{rpm:04d}rpm.wav

At runtime this module loads those loops and blends between the two
nearest RPM layers using variable-rate scrubbing — exactly how AAA game
engines (Gran Turismo, Forza) handle engine audio:

    1. For each output sample, look up current RPM from telemetry.
    2. Find the two bounding RPM layers  (lo_rpm ≤ current_rpm < hi_rpm).
    3. Scrub lo_sample at rate = current_rpm / lo_rpm  → pitch-shifts it up
       to the current RPM.
    4. Scrub hi_sample at rate = current_rpm / hi_rpm  → pitch-shifts it down.
    5. Cross-fade the two reads: weight = (current_rpm − lo_rpm) / (hi_rpm − lo_rpm).
    6. Apply throttle/brake amplitude envelope.

This gives perfectly smooth pitch transitions at every speed with zero
artifacts, because the pitch shift never exceeds 1 octave between layers.

SYNTHESIZED FALLBACK  (no WAV files needed)
────────────────────────────────────────────
If no WAV files exist in assets/engine/, falls back to an improved
harmonic synthesis model:
  • 4-cylinder firing-frequency sawtooth (rich harmonics)
  • Exhaust resonance low-pass filter
  • Intake bandpass noise layer
  • Throttle/brake amplitude envelope

Public API
──────────
    build_engine_track(telemetry, video_dur_s, sim_dur_s, assets_dir=None)
    → float32 mono array, length = int(video_dur_s × SAMPLE_RATE)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

log = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
ENGINE_VOL  = 0.65

# Speed → RPM model (simplified 6-speed automatic)
IDLE_RPM      = 800.0
MAX_RPM       = 4000.0
MAX_SPEED_KMH = 130.0   # speed at which RPM saturates


# ── Telemetry helpers ──────────────────────────────────────────────────────────

def _interp_telemetry(
    telemetry: list[dict],
    n_out:     int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Interpolate telemetry arrays over *n_out* samples spanning the full sim
    time range.  Returns (t_sim, speed, throttle, brake) as float32 arrays.
    """
    times    = np.array([e["elapsed_s"]  for e in telemetry], dtype=np.float64)
    speeds   = np.array([e["speed_kmh"]  for e in telemetry], dtype=np.float64)
    throttle = np.array([e["throttle"]   for e in telemetry], dtype=np.float64)
    brake    = np.array([e["brake"]      for e in telemetry], dtype=np.float64)

    t_sim = np.linspace(times[0], times[-1], n_out)
    return (
        t_sim.astype(np.float32),
        np.interp(t_sim, times, speeds).astype(np.float32),
        np.interp(t_sim, times, throttle).astype(np.float32),
        np.interp(t_sim, times, brake).astype(np.float32),
    )


def _speed_to_rpm(speed_kmh: np.ndarray) -> np.ndarray:
    """Simplified speed → RPM curve (idle at 0 km/h, saturates at MAX_SPEED_KMH)."""
    return (IDLE_RPM + (np.clip(speed_kmh, 0.0, MAX_SPEED_KMH) / MAX_SPEED_KMH)
            * (MAX_RPM - IDLE_RPM)).astype(np.float32)


# ── Sample loading ─────────────────────────────────────────────────────────────

def _load_wav_mono(path: Path) -> np.ndarray:
    """Load a WAV file as float32 mono at SAMPLE_RATE (resamples if needed)."""
    sr, data = wavfile.read(str(path))

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
        log.debug("Resampled %s from %d→%d Hz", path.name, sr, SAMPLE_RATE)

    # Normalise each loop to unit amplitude
    peak = np.max(np.abs(data))
    if peak > 1e-6:
        data /= peak

    return data


def _load_samples(assets_dir: Path) -> dict[int, np.ndarray]:
    """
    Load all engine_????rpm.wav files from assets_dir.
    Returns dict mapping RPM (int) → float32 mono array.
    """
    samples: dict[int, np.ndarray] = {}
    for wav in sorted(assets_dir.glob("engine_*rpm.wav")):
        try:
            # filename: engine_0800rpm.wav  → rpm = 800
            rpm_str = wav.stem.replace("engine_", "").replace("rpm", "")
            rpm     = int(rpm_str)
            samples[rpm] = _load_wav_mono(wav)
            log.info("  Loaded %-24s → %4d RPM  (%.3f s)",
                     wav.name, rpm, len(samples[rpm]) / SAMPLE_RATE)
        except Exception as exc:
            log.warning("  Could not load %s: %s", wav.name, exc)
    return samples


# ── Variable-rate scrubbing ────────────────────────────────────────────────────

def _scrub(sample: np.ndarray, rates: np.ndarray) -> np.ndarray:
    """
    Read from *sample* at positions accumulated by *rates*.

    positions[i] = sum(rates[0..i])   — the playback head position in source samples.
    rate = 1.0 → original pitch; rate = 2.0 → one octave up; rate = 0.5 → one octave down.
    Sample is looped automatically.  Linear interpolation between adjacent samples.

    Fully vectorised (no Python loop) — runs at numpy speed.
    """
    positions = np.cumsum(rates.astype(np.float64))
    n         = len(sample)
    idx       = positions.astype(np.int64) % n
    frac      = (positions - np.floor(positions)).astype(np.float32)
    nxt       = (idx + 1) % n
    return ((1.0 - frac) * sample[idx] + frac * sample[nxt]).astype(np.float32)


# ── Sample-based engine track ──────────────────────────────────────────────────

def _build_sample_track(
    samples: dict[int, np.ndarray],
    rpm_arr: np.ndarray,
    thr_arr: np.ndarray,
    brk_arr: np.ndarray,
) -> np.ndarray:
    """
    Cross-fade between RPM layers using variable-rate scrubbing.

    For each RPM band [lo_rpm, hi_rpm):
      • Scrub lo_sample at rate = current_rpm / lo_rpm  (pitch up to match target)
      • Scrub hi_sample at rate = current_rpm / hi_rpm  (pitch down to match target)
      • Blend with weight t = (current_rpm − lo_rpm) / (hi_rpm − lo_rpm)

    This ensures every pitch transition is always a blend of two samples whose
    individual pitch shift never exceeds ±1 octave, preventing artifacts.
    """
    rpms  = sorted(samples.keys())
    n     = len(rpm_arr)
    out   = np.zeros(n, dtype=np.float32)

    # Pre-compute scrubbed tracks for every layer at VARIABLE rate (follows rpm_arr)
    # Each layer is scrubbed at current_rpm / layer_rpm so it sounds like current_rpm.
    scrubbed: dict[int, np.ndarray] = {}
    for rpm, sample in samples.items():
        rates           = (rpm_arr / float(rpm)).astype(np.float32)
        scrubbed[rpm]   = _scrub(sample, rates)
        log.debug("  Scrubbed %d RPM layer  rate=[%.2f – %.2f]",
                  rpm, float(rates.min()), float(rates.max()))

    # Blend adjacent layers based on current RPM
    for i in range(len(rpms) - 1):
        lo, hi   = rpms[i], rpms[i + 1]
        in_band  = (rpm_arr >= lo) & (rpm_arr < hi)
        if not np.any(in_band):
            continue
        t        = ((rpm_arr - lo) / float(hi - lo)).astype(np.float32)
        out     += in_band * ((1.0 - t) * scrubbed[lo] + t * scrubbed[hi])

    # Below lowest layer
    mask = rpm_arr < rpms[0]
    if np.any(mask):
        out[mask] = scrubbed[rpms[0]][mask]

    # Above highest layer
    mask = rpm_arr >= rpms[-1]
    if np.any(mask):
        out[mask] = scrubbed[rpms[-1]][mask]

    # Amplitude envelope: louder under throttle, quieter under braking
    amp  = np.clip(0.55 + 0.45 * thr_arr - 0.25 * brk_arr, 0.2, 1.0)
    out *= amp

    # Fade in/out
    fade = int(SAMPLE_RATE * 0.05)
    out[:fade]  *= np.linspace(0.0, 1.0, fade)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)

    out /= (np.max(np.abs(out)) + 1e-9)
    return out


# ── Synthesized fallback ───────────────────────────────────────────────────────

def _build_synth_track(
    speed_arr: np.ndarray,
    thr_arr:   np.ndarray,
    brk_arr:   np.ndarray,
) -> np.ndarray:
    """
    Improved synthesized engine: 4-cylinder combustion model + exhaust filter.

    Much more realistic than a pure sine wave:
      • Sawtooth harmonic series — models the broadband combustion pulse
      • Low-pass exhaust resonance filter
      • Intake broadband noise (bandpass-filtered)
      • Throttle/brake amplitude envelope
      • RPM derived from speed using a simplified gear model
    """
    n      = len(speed_arr)
    rpm    = _speed_to_rpm(speed_arr)

    # 4-cylinder 4-stroke firing frequency: (RPM/60) × (4cyl / 2strokes) = RPM/30
    f_fire = (rpm / 30.0).astype(np.float64)

    # Phase accumulation (glitch-free even as frequency changes)
    phase = np.cumsum(2.0 * np.pi * f_fire / SAMPLE_RATE)

    # Sawtooth via Fourier series (7 harmonics → natural combustion timbre)
    wave = np.zeros(n, dtype=np.float64)
    for h in range(1, 8):
        wave += ((-1.0) ** (h + 1) / h) * np.sin(h * phase)
    wave *= (2.0 / np.pi)   # normalise sawtooth to ±1

    # Exhaust resonance: low-pass (models exhaust pipe damping of high harmonics)
    sos_ex = butter(4, 1200.0 / (SAMPLE_RATE / 2.0), "low", output="sos")
    wave   = sosfilt(sos_ex, wave)

    # Intake noise: bandpass-filtered white noise around current firing frequency
    f_lo  = max(float(f_fire.mean()) * 0.5,  50.0)
    f_hi  = min(float(f_fire.mean()) * 4.0, 8000.0)
    if f_lo < f_hi:
        noise    = np.random.default_rng(42).standard_normal(n)
        sos_in   = butter(2, [f_lo / (SAMPLE_RATE / 2.0),
                               f_hi / (SAMPLE_RATE / 2.0)], "band", output="sos")
        wave    += sosfilt(sos_in, noise) * 0.12

    # Amplitude envelope
    amp   = np.clip(0.55 + 0.45 * thr_arr - 0.25 * brk_arr, 0.2, 1.0)
    wave *= amp

    # Fade in/out
    fade  = int(SAMPLE_RATE * 0.05)
    wave[:fade]  *= np.linspace(0.0, 1.0, fade)
    wave[-fade:] *= np.linspace(1.0, 0.0, fade)

    wave /= (np.max(np.abs(wave)) + 1e-9)
    return wave.astype(np.float32)


# ── Public API ─────────────────────────────────────────────────────────────────

def build_engine_track(
    telemetry:   list[dict],
    video_dur_s: float,
    sim_dur_s:   float,
    assets_dir:  Path | None = None,
) -> np.ndarray:
    """
    Build a speed-modulated engine audio track timed to the VIDEO duration.

    Automatically uses sample-based synthesis if WAV loops are present in
    assets_dir; otherwise falls back to improved harmonic synthesis.

    Args:
        telemetry:   list of frame dicts from telemetry.json
        video_dur_s: actual video playback duration (seconds)
        sim_dur_s:   simulation duration (seconds) — used for time mapping
        assets_dir:  folder containing engine_????rpm.wav files.
                     Defaults to  xav/assets/engine/

    Returns:
        float32 mono array of length int(video_dur_s × SAMPLE_RATE),
        values in [−ENGINE_VOL, ENGINE_VOL].
    """
    if assets_dir is None:
        assets_dir = Path(__file__).resolve().parents[2] / "assets" / "engine"

    n_out = int(video_dur_s * SAMPLE_RATE)
    _, spd, thr, brk = _interp_telemetry(telemetry, n_out)
    rpm_arr           = _speed_to_rpm(spd)

    log.info("Engine track: %.3f s video  (%.3f s sim)  n=%d samples",
             video_dur_s, sim_dur_s, n_out)
    log.info("Speed range: %.1f – %.1f km/h  →  RPM range: %.0f – %.0f",
             float(spd.min()), float(spd.max()),
             float(rpm_arr.min()), float(rpm_arr.max()))

    # ── Try sample-based ───────────────────────────────────────────────────
    samples = {}
    if assets_dir.exists():
        samples = _load_samples(assets_dir)

    if samples:
        log.info("Mode: SAMPLE-BASED  (%d RPM layers: %s)",
                 len(samples), ", ".join(str(r) for r in sorted(samples)))
        wave = _build_sample_track(samples, rpm_arr, thr, brk)
        log.info("Sample-based engine track done")
    else:
        log.info("Mode: SYNTHESIZED FALLBACK  (no WAV files in %s)", assets_dir)
        log.info("  → Run:  python scripts/audio_pipeline/setup_engine_samples.py")
        log.info("    to generate real engine sounds (one-time, ~5 min)")
        wave = _build_synth_track(spd, thr, brk)
        log.info("Synthesized engine track done")

    return (wave[:n_out] * ENGINE_VOL).astype(np.float32)
