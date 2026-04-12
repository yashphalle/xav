"""
scripts/audio_pipeline/setup_engine_samples.py
One-time setup: builds enginesound (Rust) and generates seamless engine loop
WAVs at 7 RPM levels that the audio pipeline blends between at runtime.

Run once:
    conda activate carla-xav
    python scripts/audio_pipeline/setup_engine_samples.py

Outputs (in xav/assets/engine/):
    engine_0800rpm.wav   ← idle
    engine_1200rpm.wav
    engine_1600rpm.wav
    engine_2000rpm.wav
    engine_2500rpm.wav
    engine_3000rpm.wav
    engine_4000rpm.wav   ← wide-open throttle

enginesound: https://github.com/DasEtwas/enginesound  (MIT licence)
"""

import math
import os
import subprocess
import sys
from pathlib import Path

ROOT       = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT / "assets" / "engine"
BUILD_DIR  = ROOT / "build" / "enginesound"
REPO_URL   = "https://github.com/DasEtwas/enginesound"
BINARY     = BUILD_DIR / "target" / "release" / "enginesound"

# RPM levels to generate — covers idle (800) through WOT (4000)
RPMS = [800, 1200, 1600, 2000, 2500, 3000, 4000]

# Which example config to use (bundled in the repo)
# example1 = generic 4-cylinder petrol engine
ENGINE_CONFIG = "example1.esc"

SAMPLE_RATE = 44_100   # must match synthesizer.py


# ── Rust / cargo ───────────────────────────────────────────────────────────────

def _cargo_available() -> bool:
    try:
        r = subprocess.run(["cargo", "--version"], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _install_rust():
    print("Rust not found — installing via rustup (this is a one-time ~2 min step) …")
    subprocess.run(
        'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y',
        shell=True, check=True,
    )
    cargo_bin = Path.home() / ".cargo" / "bin"
    os.environ["PATH"] = str(cargo_bin) + ":" + os.environ.get("PATH", "")
    print("Rust installed. PATH updated for this session.")


# ── enginesound build ──────────────────────────────────────────────────────────

def _clone_repo():
    if BUILD_DIR.exists():
        print(f"Repo already cloned at {BUILD_DIR}")
        return
    print(f"Cloning enginesound → {BUILD_DIR} …")
    subprocess.run(["git", "clone", REPO_URL, str(BUILD_DIR)], check=True)


def _build_binary():
    if BINARY.exists():
        print(f"Binary already built: {BINARY}")
        return
    print("Building enginesound (first build takes 1–3 min) …")
    subprocess.run(
        ["cargo", "build", "--release", "--no-default-features"],
        cwd=BUILD_DIR, check=True,
    )
    print(f"Built: {BINARY}")


# ── WAV generation ─────────────────────────────────────────────────────────────

def _rpm_loop_params(rpm: int) -> tuple[float, float, float]:
    """
    Return (length_s, crossfade_s, warmup_s) for a seamless loop at *rpm*.
    Formula from the enginesound README.
    """
    wavelength  = 120.0 / rpm
    average_len = 3.2
    cycles      = math.ceil(average_len / wavelength)
    crossfade   = 2.0 * wavelength
    length      = wavelength * cycles + crossfade / 2.0
    warmup      = 2.0
    return length, crossfade, warmup


def _generate_loop(rpm: int, config: Path, output: Path) -> None:
    length, crossfade, warmup = _rpm_loop_params(rpm)
    cmd = [
        str(BINARY),
        "--headless",
        "--config",       str(config),
        "--output",       str(output),
        "--rpm",          str(rpm),
        "--samplerate",   str(SAMPLE_RATE),
        "--volume",       "0.5",
        "--length",       f"{length:.4f}",
        "--crossfade",    f"{crossfade:.4f}",
        "--warmup_time",  f"{warmup:.1f}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"enginesound failed for {rpm} RPM:\n{result.stderr}"
        )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Rust
    if not _cargo_available():
        _install_rust()
    if not _cargo_available():
        print("ERROR: cargo still not found. Re-open your terminal and try again.")
        sys.exit(1)

    # 2. Clone + build
    _clone_repo()
    _build_binary()

    # 3. Config file
    config = BUILD_DIR / ENGINE_CONFIG
    if not config.exists():
        raise FileNotFoundError(
            f"Engine config not found: {config}\n"
            "Check that the repo cloned correctly."
        )

    # 4. Generate loops
    print(f"\nGenerating {len(RPMS)} engine loops → {ASSETS_DIR}\n")
    for rpm in RPMS:
        out = ASSETS_DIR / f"engine_{rpm:04d}rpm.wav"
        if out.exists():
            print(f"  [skip] {out.name} already exists")
            continue
        print(f"  [{rpm:4d} RPM]  length={_rpm_loop_params(rpm)[0]:.2f}s …", end=" ", flush=True)
        _generate_loop(rpm, config, out)
        size_kb = out.stat().st_size // 1024
        print(f"done  ({size_kb} KB)")

    print(f"\nAll engine samples ready in {ASSETS_DIR}")
    print("The audio pipeline will now use real engine sounds automatically.")


if __name__ == "__main__":
    main()
