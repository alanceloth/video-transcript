"""Descobre a grade de tiles empiricamente e monta um contato-sheet dos badges.

1. agrupa os y observados em active_speaker.json (cada grupo = uma posicao de tile)
2. mostra a distribuicao temporal de cada grupo (revela mudanca de layout do roster)
3. amostra eventos espalhados no tempo, recorta o badge e monta uma folha por grupo
   -> as folhas em out/frames/verify_*.png sao lidas para extrair o NOME de cada grupo

Assim o mapeamento posicao -> nome vem dos pixels do proprio badge, nao de chute.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter

import common

OUT, FRAMES = common.OUT, common.FRAMES
hms = common.hms

Y_TOL = 10          # px: y dentro dessa distancia = mesmo tile
SAMPLES = 5         # amostras por grupo, espalhadas no tempo
BADGE_X, BADGE_W, BADGE_H = 1674, 250, 34


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", help="video (default: o unico do projeto)")
    args = ap.parse_args()

    common.ensure_dirs()
    video = common.find_video(args.video)
    ffmpeg = str(common.find_ffmpeg())
    data = json.loads((OUT / "active_speaker.json").read_text(encoding="utf-8"))
    samples = data["samples"]
    print(f"{len(samples)} amostras com badge aceso de {int(data['duration'] / 0.5)} frames")

    # agrupa por (side, y) com tolerancia
    grupos: list[dict] = []
    for s in sorted(samples, key=lambda x: (x["side"], x["yc"])):
        for g in grupos:
            if g["side"] == s["side"] and abs(g["yc"] - s["yc"]) <= Y_TOL:
                g["itens"].append(s)
                g["yc"] = sum(i["yc"] for i in g["itens"]) // len(g["itens"])
                break
        else:
            grupos.append({"side": s["side"], "yc": s["yc"], "itens": [s]})

    grupos = [g for g in grupos if len(g["itens"]) >= 4]
    grupos.sort(key=lambda g: -len(g["itens"]))

    print(f"\n{len(grupos)} posicoes de tile distintas:")
    print(f"{'#':>2} {'lado':>4} {'y':>5} {'amostras':>9} {'tempo':>8}   janela de tempo")
    for i, g in enumerate(grupos):
        ts = sorted(x["t"] for x in g["itens"])
        secs = len(ts) / 2
        # distribuicao por decil da reuniao, para ver se o tile muda de dono
        dec = Counter(int(t / data["duration"] * 10) for t in ts)
        spark = "".join(".123456789#"[min(10, dec.get(d, 0) * 10 // max(1, max(dec.values())))]
                        for d in range(10))
        print(f"{i:>2} {g['side']:>4} {g['yc']:>5} {len(ts):>9} "
              f"{int(secs // 60):3d}m{int(secs % 60):02d}s   "
              f"{hms(ts[0])}..{hms(ts[-1])}  [{spark}]")

    # contato-sheet por grupo
    print("\ngerando folhas de verificacao...")
    manifest = []
    for i, g in enumerate(grupos):
        ts = sorted(x["t"] for x in g["itens"])
        picks = [ts[int(k * (len(ts) - 1) / max(1, SAMPLES - 1))] for k in range(SAMPLES)]
        picks = sorted(set(picks))
        crops = []
        for j, t in enumerate(picks):
            p = FRAMES / f"vb_{i:02d}_{j}.png"
            y = max(0, g["yc"] - BADGE_H // 2)
            subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats",
                 "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                 "-vf", f"crop={BADGE_W}:{BADGE_H}:{BADGE_X}:{y},scale=iw*2:ih*2:flags=lanczos",
                 "-y", str(p)],
                check=True, capture_output=True,
            )
            crops.append(p)
            manifest.append({"grupo": i, "linha": j, "t": t, "hms": hms(t),
                             "side": g["side"], "yc": g["yc"]})
        sheet = FRAMES / f"verify_{i:02d}.png"
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats",
             "-i", str(FRAMES / f"vb_{i:02d}_%d.png"),
             "-filter_complex", f"tile=1x{len(crops)}:margin=3:padding=5:color=red",
             "-frames:v", "1", "-y", str(sheet)],
            check=True, capture_output=True,
        )
        print(f"  grupo {i} (lado {g['side']}, y={g['yc']}): {len(crops)} amostras "
              f"em {', '.join(hms(t) for t in picks)} -> {sheet.name}")

    (OUT / "verify_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # rascunho do mapeamento posicao -> nome: preencher lendo as folhas verify_NN.png
    alvo = OUT / "tile_names.json"
    if alvo.exists():
        atual = {(m["side"], m["yc"]): m["name"]
                 for m in json.loads(alvo.read_text(encoding="utf-8"))}
        faltando = [g for g in grupos
                    if not any(s == g["side"] and abs(y - g["yc"]) <= Y_TOL
                               for s, y in atual)]
        print(f"\n{alvo.name} ja existe com {len(atual)} nomes; "
              f"{len(faltando)} posicoes sem nome.")
        for g in faltando:
            print(f"  FALTA: lado {g['side']} y={g['yc']}")
    else:
        alvo.write_text(
            json.dumps([{"side": g["side"], "yc": g["yc"], "name": None} for g in grupos],
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nrascunho criado: {alvo.relative_to(common.PROJ)}")
        print(f"PROXIMO PASSO: abra as folhas {FRAMES.relative_to(common.PROJ)}/verify_NN.png, "
              "leia o nome no badge roxo e preencha o campo \"name\" da posicao "
              "correspondente (grupo NN = ordem em que aparecem acima). Depois: make merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
