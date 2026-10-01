"""Dump da transcricao bruta em texto (sem falantes) + nomes proprios citados.

out/asr.txt  - [hh:mm:ss] texto, uma linha por segmento
Imprime tambem a contagem de tokens capitalizados no meio de frase (candidatos a
nome de pessoa), util para identificar participantes citados na conversa.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import common

OUT = common.OUT
hms = common.hms

STOP = {
    "A", "O", "E", "Mas", "Então", "Que", "Não", "Sim", "Aí", "Aqui", "Ali", "Ele", "Ela",
    "Eu", "Você", "Vocês", "Nós", "Isso", "Isto", "Esse", "Essa", "Este", "Esta", "Como",
    "Quando", "Porque", "Por", "Para", "Com", "Sem", "De", "Da", "Do", "Das", "Dos", "No",
    "Na", "Nos", "Nas", "Um", "Uma", "Os", "As", "Se", "Já", "Ah", "Ó", "Tá", "Ok", "Bom",
    "Agora", "Depois", "Antes", "Só", "Também", "Tem", "Tinha", "Vai", "Foi", "Está", "Estão",
    "Lei", "Decreto", "Artigo", "Classe", "Crédito", "Créditos", "Processo", "Juiz", "Juíza",
    "Certo", "Beleza", "Perfeito", "Exato", "Obrigada", "Obrigado", "Oi", "Olá", "Gente",
}


def main() -> int:
    common.require(OUT / "asr.json", "make asr")
    asr = json.loads((OUT / "asr.json").read_text(encoding="utf-8"))
    segs = asr["segments"]
    (OUT / "asr.txt").write_text(
        "\n".join(f"[{hms(s['start'])}] {s['text']}" for s in segs), encoding="utf-8"
    )

    palavras = sum(len(s["text"].split()) for s in segs)
    print(f"{len(segs)} segmentos | {palavras} palavras | {hms(asr['duration'])}")

    # tokens capitalizados que NAO iniciam frase -> candidatos a nome proprio
    cand: Counter[str] = Counter()
    for s in segs:
        toks = re.findall(r"[A-ZÀ-Ý][a-zà-ÿ]{2,}", s["text"])
        for tok in toks:
            # ignora se for a primeira palavra do segmento
            if s["text"].lstrip().startswith(tok):
                continue
            if tok not in STOP:
                cand[tok] += 1
    print("\ncandidatos a nome proprio (>=3 mencoes):")
    for tok, n in cand.most_common(45):
        if n >= 3:
            print(f"  {n:4d}  {tok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
