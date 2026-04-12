"""
scripts/audio_pipeline/setup_siren_sample.py
One-time setup: generates a seamless ambulance siren loop WAV using SoX.

Run once:
    conda activate carla-xav
    python scripts/audio_pipeline/setup_siren_sample.py

Output:
    xav/assets/siren/siren_loop.wav   ← seamless 1.4 s wail loop

SoX uses a square-wave sweep (700 → 1050 Hz), which has the same buzzy
harmonic quality as a real siren — unlike a pure sine tone.  The loop is
a full wail cycle: sweep up (0.7 s) then sweep down (0.7 s), joined with
a crossfade so it loops cleanly.

SoX install (if not already present):
    sudo apt install sox
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT       = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT / "assets" / "siren"
OUT_WAV    = ASSETS_DIR / "siren_loop.wav"

SAMPLE_RATE  = 44_100
HALF_PERIOD  = 0.7    # seconds per up / down sweep
F_LO         = 700    # Hz — low tone
F_HI         = 1050   # Hz — high tone
CROSSFADE_MS = 20     # ms crossfade when joining the two halves


def _sox_available() -> bool:
    try:
        r = subprocess.run(["sox", "--version"], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _generate(out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        up   = tmp / "up.wav"
        down = tmp / "down.wav"

        # Sweep up: F_LO → F_HI  (square wave — buzzy, realistic siren timbre)
        subprocess.run([
            "sox", "-n",
            "-r", str(SAMPLE_RATE), "-c", "1",
            str(up),
            "synth", f"{HALF_PERIOD:.3f}",
            "square", f"{F_LO}:{F_HI}",
            "norm", "-3",
        ], check=True)

        # Sweep down: F_HI → F_LO
        subprocess.run([
            "sox", "-n",
            "-r", str(SAMPLE_RATE), "-c", "1",
            str(down),
            "synth", f"{HALF_PERIOD:.3f}",
            "square", f"{F_HI}:{F_LO}",
            "norm", "-3",
        ], check=True)

        # Join with short crossfade so the loop boundary is seamless
        subprocess.run([
            "sox", str(up), str(down),
            str(out),
            "splice", f"-q", f"{HALF_PERIOD:.3f},{CROSSFADE_MS/1000:.4f}",
        ], check=True)

    size_kb = out.stat().st_size // 1024
    print(f"  Written: {out}  ({size_kb} KB)")


def main():
    if not _sox_available():
        print("SoX not found.  Install it with:")
        print("    sudo apt install sox")
        sys.exit(1)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    if OUT_WAV.exists():
        print(f"[skip] {OUT_WAV.name} already exists — delete it to regenerate")
        return

    print(f"Generating siren loop ({F_LO}–{F_HI} Hz square-wave wail, "
          f"{HALF_PERIOD * 2:.1f} s) …")
    _generate(OUT_WAV)
    print("Done.  The audio pipeline will use the real siren loop automatically.")


if __name__ == "__main__":
    main()
