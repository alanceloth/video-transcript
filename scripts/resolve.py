"""Resolve caminhos e pre-condicoes para o Makefile, em POSIX e sem quebrar com espaco.

O make nao consegue derivar alvos de caminho com espaco (e nome de gravacao do Teams
sempre tem), entao quem resolve caminho e o Python; o Makefile so consome a saida
entre aspas.

  resolve.py video   imprime o caminho do video de entrada
  resolve.py out     imprime o diretorio de saida
  resolve.py vtt     imprime o .vtt do Teams; exit 1 (silencioso) se nao houver
  resolve.py slack   imprime a transcricao do circulo do Slack; exit 1 se nao houver
  resolve.py names   exit 0 se tile_names.json ja tem algum nome preenchido
"""

from __future__ import annotations

import json
import sys

import common


def main() -> int:
    o = sys.argv[1] if len(sys.argv) > 1 else ""

    if o == "video":
        print(common.find_video().as_posix())
    elif o == "out":
        print(common.OUT.as_posix())
    elif o == "vtt":
        import merge  # reaproveita a heuristica de localizacao do .vtt
        try:
            print(merge._locate_vtt(None).as_posix())
        except SystemExit:
            return 1
    elif o == "slack":
        import merge  # reaproveita a heuristica de localizacao do .slack.json
        try:
            print(merge._locate_slack(None).as_posix())
        except SystemExit:
            return 1
    elif o == "names":
        alvo = common.OUT / "tile_names.json"
        if not alvo.exists():
            return 1
        mapa = json.loads(alvo.read_text(encoding="utf-8"))
        return 0 if any(m.get("name") for m in mapa) else 1
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
