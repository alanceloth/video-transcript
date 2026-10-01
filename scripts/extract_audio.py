"""Extrai o audio do video em WAV PCM 16-bit mono 16 kHz (formato que o resto espera).

Uso: python extract_audio.py [caminho/do/video]
"""

from __future__ import annotations

import argparse
import subprocess

import common


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", help="video de entrada (default: o unico do projeto)")
    args = ap.parse_args()

    common.ensure_dirs()
    video = common.find_video(args.video)
    wav = common.OUT / "audio.wav"
    if common.skip_if_done(wav, "extracao de audio"):
        return 0

    dur = subprocess.run(
        [str(common.find_ffmpeg("ffprobe")), "-v", "error",
         "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    print(f"video: {video.name}\nduracao: {common.hms(float(dur))}")

    subprocess.run(
        [str(common.find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-nostats",
         "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)],
        check=True,
    )
    print(f"-> {wav.relative_to(common.PROJ)} ({wav.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
