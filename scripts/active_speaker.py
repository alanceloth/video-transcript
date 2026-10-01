"""Extrai a linha do tempo de "quem esta falando" direto da UI do Teams gravada.

O Teams pinta o badge de nome do falante ativo com o roxo da marca (#6264A7).
Varremos o video a 2 fps, olhamos duas faixas verticais que cobrem os badges
(coluna esquerda dos tiles grandes/pequenos e coluna direita dos tiles pequenos),
e para cada frame decidimos qual tile esta aceso.

Vantagem sobre diarizacao por audio: entrega o NOME REAL, sem clustering.

Saida: out/active_speaker.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import numpy as np

import common

FPS = 2.0
STRIP_W = 120           # largura de cada faixa
LEFT_X, RIGHT_X = 1682, 1800
W, H = STRIP_W * 2, 1080
FRAME_BYTES = W * H * 3

TEAMS_PURPLE = np.array([98, 100, 167], dtype=np.int16)
TOL = 30
# um badge aceso rende alguns milhares de px; ruido de fundo fica < 500
MIN_PX = 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", help="video (default: o unico do projeto)")
    args = ap.parse_args()

    common.ensure_dirs()
    video = common.find_video(args.video)
    saida = common.OUT / "active_speaker.json"
    if common.skip_if_done(saida, "varredura de badges"):
        return 0

    cmd = [
        str(common.find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-nostats",
        "-i", str(video),
        "-filter_complex",
        f"[0:v]fps={FPS}[v];"
        f"[v]split=2[a][b];"
        f"[a]crop={STRIP_W}:{H}:{LEFT_X}:0[l];"
        f"[b]crop={STRIP_W}:{H}:{RIGHT_X}:0[r];"
        f"[l][r]hstack=inputs=2[out]",
        "-map", "[out]", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    print("varrendo video a %.1f fps..." % FPS, flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=FRAME_BYTES * 4)

    timeline: list[dict] = []
    t0 = time.time()
    idx = 0
    while True:
        buf = proc.stdout.read(FRAME_BYTES)
        if len(buf) < FRAME_BYTES:
            break
        frame = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 3).astype(np.int16)
        mask = (np.abs(frame - TEAMS_PURPLE) <= TOL).all(axis=2)

        # NAO assumimos grade fixa de tiles: o layout do roster muda durante a reuniao.
        # Localizamos a faixa horizontal de pixels roxos mais forte e guardamos sua
        # geometria; a grade e descoberta depois, por clustering dos y observados.
        per_row = mask.sum(axis=1)
        best = None  # (px, y0, y1)
        start = None
        for y in range(H + 1):
            hot = y < H and per_row[y] >= 3
            if hot and start is None:
                start = y
            elif not hot and start is not None:
                px = int(per_row[start:y].sum())
                if 14 <= (y - start) <= 44 and (best is None or px > best[0]):
                    best = (px, start, y - 1)
                start = None

        t = idx / FPS
        if best is not None and best[0] >= MIN_PX:
            px, y0, y1 = best
            sub = mask[y0 : y1 + 1]
            left = int(sub[:, :STRIP_W].sum())
            right = int(sub[:, STRIP_W:].sum())
            timeline.append({
                "t": round(t, 2), "y0": y0, "y1": y1,
                "yc": (y0 + y1) // 2, "px": px,
                "side": "L" if left >= right else "R",
            })
        idx += 1
        if idx % 600 == 0:
            print(f"  {t / 60:5.1f} min de video  (+{(time.time() - t0) / 60:.1f} min) "
                  f"| {len(timeline)} amostras com falante", flush=True)

    err = proc.stderr.read().decode(errors="replace")
    proc.wait()
    if proc.returncode not in (0, None) and not timeline:
        print(f"ffmpeg falhou: {err[:500]}", file=sys.stderr)
        return 1

    total = idx / FPS
    saida.write_text(json.dumps({"fps": FPS, "duration": total, "samples": timeline},
                                ensure_ascii=False), encoding="utf-8")

    # agrega por posicao observada (lado + y arredondado); o nome de cada posicao
    # e resolvido depois por verify_tiles.py, lendo o texto do proprio badge
    por_pos: dict[tuple[str, int], int] = {}
    for s in timeline:
        key = (s["side"], round(s["yc"] / 10) * 10)
        por_pos[key] = por_pos.get(key, 0) + 1
    print(f"\n{idx} frames ({total / 60:.1f} min) | {len(timeline)} com badge aceso "
          f"({100 * len(timeline) / max(idx, 1):.1f}% de cobertura)")
    print(f"{'lado':>5} {'y':>5}  {'tempo':>8}  {'%':>5}")
    for (side, y), n in sorted(por_pos.items(), key=lambda kv: -kv[1]):
        secs = n / FPS
        print(f"{side:>5} {y:>5}  {int(secs // 60):3d}m{int(secs % 60):02d}s  "
              f"{100 * n / len(timeline):5.1f}")
    print(f"-> {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
