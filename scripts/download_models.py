"""Baixa os modelos ONNX da diarizacao por audio (sherpa-onnx) para models/.

So o caminho SPEAKER=audio precisa deles; vtt/slack/badge nao usam. O whisper
(large-v3) NAO entra aqui: o faster-whisper baixa sozinho do Hugging Face na primeira
transcricao e guarda no cache do usuario.

Python puro (urllib + tarfile) em vez de curl/tar do Makefile, para rodar igual em
qualquer shell. Idempotente: modelo que ja existe e pulado (VT_FORCE=1 rebaixa).
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tarfile
import tempfile
import urllib.request

import common

REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

# segmentacao pyannote 3.0 (vem num tar.bz2 com o model.onnx dentro)
SEG_DIR = common.MODELS / "sherpa-onnx-pyannote-segmentation-3-0"
SEG_URL = f"{REL}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"

# embeddings de voz; o nome do arquivo mantem o %2B%2B literal que diarize.py espera.
# "speaker-recongition" (sic) e o nome real da release no GitHub do sherpa-onnx.
EMBEDDINGS = [
    "wespeaker_en_voxceleb_CAM%2B%2B_LM.onnx",
    "wespeaker_en_voxceleb_resnet293_LM.onnx",
]


def _baixar(url: str, destino) -> None:
    print(f"baixando {url.rsplit('/', 1)[-1]} ...", flush=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(destino)


def main() -> int:
    force = bool(os.environ.get("VT_FORCE"))
    common.MODELS.mkdir(parents=True, exist_ok=True)

    if (SEG_DIR / "model.onnx").exists() and not force:
        print(f"{SEG_DIR.name} ja existe -> pulando")
    else:
        with tempfile.TemporaryDirectory() as td:
            arq = pathlib.Path(td) / "seg.tar.bz2"
            _baixar(SEG_URL, arq)
            with tarfile.open(arq, "r:bz2") as tar:
                tar.extractall(common.MODELS, filter="data")

    for nome in EMBEDDINGS:
        destino = common.MODELS / nome
        if destino.exists() and not force:
            print(f"{nome} ja existe -> pulando")
            continue
        _baixar(f"{REL}/speaker-recongition-models/{nome}", destino)

    print(f"modelos prontos em {common.MODELS.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
