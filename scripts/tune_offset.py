"""Calibra a compensacao de latencia do badge do Teams.

O Teams acende o badge do falante ativo com um atraso de fracoes de segundo. Isso
faz as primeiras palavras de um turno cairem no falante anterior. Aqui varremos
offsets e escolhemos o que melhor alinha as trocas de falante com as fronteiras de
frase da transcricao.

Metricas (menor = melhor):
  fragmentos  turnos com <= 3 palavras (crosstalk mal cortado)
  d_media     distancia media, em s, da troca de falante ate o inicio de segmento ASR
  na_borda    % de trocas que caem exatamente no inicio de um segmento ASR (maior = melhor)
"""

from __future__ import annotations

import bisect
import json

import common
import merge

OUT = common.OUT


def main() -> int:
    common.require(OUT / "asr.json", "make asr")
    common.require(OUT / "tile_names.json", "make verify")
    asr = json.loads((OUT / "asr.json").read_text(encoding="utf-8"))
    segs = asr["segments"]
    bordas = sorted(s["start"] for s in segs)

    print(f"{'offset':>7} {'turnos':>7} {'fragmentos':>11} {'d_media':>8} {'na_borda':>9}")
    linhas = []
    for i in range(0, 13):
        off = -0.2 * i
        iv = merge.intervals_from_badge(offset=off)
        blocks, _ = merge.build_blocks(segs, iv)
        frag = sum(1 for b in blocks if len(b["text"].split()) <= 3)
        dists = []
        for b in blocks[1:]:
            j = bisect.bisect_left(bordas, b["start"])
            cands = [abs(b["start"] - bordas[k])
                     for k in (j - 1, j, j + 1) if 0 <= k < len(bordas)]
            dists.append(min(cands) if cands else 0.0)
        d = sum(dists) / len(dists) if dists else 0.0
        na_borda = 100 * sum(1 for x in dists if x <= 0.05) / max(1, len(dists))
        linhas.append((off, len(blocks), frag, d, na_borda))
        print(f"{off:7.1f} {len(blocks):7d} {frag:11d} {d:8.3f} {na_borda:8.1f}%")

    melhor = min(linhas, key=lambda r: (r[2], r[3]))
    print(f"\nmelhor offset: {melhor[0]:.1f}s "
          f"({melhor[2]} fragmentos, d_media {melhor[3]:.3f}s, {melhor[4]:.1f}% na borda)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
