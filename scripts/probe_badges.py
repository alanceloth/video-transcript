"""Explora onde ficam os badges de nome e qual y fica roxo (#6264A7 = falante ativo).

Extrai a coluna do roster em RGB puro e imprime as faixas de y com pixels roxos,
para calibrar a grade de tiles usada em active_speaker.py.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np

import common

# coluna do roster no frame 1920x1080
X0, W, H = 1670, 250, 1080
TEAMS_PURPLE = np.array([98, 100, 167])  # #6264A7


def grab(ts: str) -> np.ndarray:
    cmd = [
        str(common.find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-nostats",
        "-ss", ts, "-i", str(common.find_video()), "-frames:v", "1",
        "-vf", f"crop={W}:{H}:{X0}:0",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3)


def purple_mask(img: np.ndarray, tol: int = 30) -> np.ndarray:
    return (np.abs(img.astype(np.int16) - TEAMS_PURPLE) <= tol).all(axis=2)


def bands(mask: np.ndarray, min_px: int = 25) -> list[tuple[int, int, int]]:
    """Faixas contiguas de y com pixels roxos: (y_ini, y_fim, total_px)."""
    per_row = mask.sum(axis=1)
    out, start = [], None
    for y in range(len(per_row) + 1):
        hot = y < len(per_row) and per_row[y] >= 3
        if hot and start is None:
            start = y
        elif not hot and start is not None:
            total = int(per_row[start:y].sum())
            if total >= min_px:
                out.append((start, y - 1, total))
            start = None
    return out


def main() -> int:
    for ts in sys.argv[1:] or ["00:10:00", "00:30:00", "00:50:00"]:
        img = grab(ts)
        m = purple_mask(img)
        print(f"\n=== {ts} === roxo total={m.sum()}")
        for y0, y1, n in bands(m):
            xs = np.where(m[y0 : y1 + 1].any(axis=0))[0]
            print(f"  y {y0:4d}-{y1:4d} (h={y1 - y0 + 1:3d})  px={n:6d}  "
                  f"x {X0 + xs.min():4d}-{X0 + xs.max():4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
