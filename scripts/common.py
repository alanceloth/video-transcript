"""Infra compartilhada do pipeline: descoberta de ffmpeg/video, saida e helpers.

O video de entrada mora em input/. Nomes com espaco sao a regra (gravacao do Teams),
por isso nenhum caminho trafega pelo mecanismo de targets do make: os scripts recebem
tudo por variavel de ambiente.

Variaveis de ambiente (o Makefile as exporta):
  VT_VIDEO   nome do arquivo em input/ (ou caminho); se vazio, usa o unico video de input/
  VT_OUT     diretorio de saida; se vazio, deriva output/<nome do video>
  VT_FORCE   se setado, refaz etapas cujo artefato ja existe
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys

PROJ = pathlib.Path(__file__).resolve().parent.parent
INPUT = PROJ / "input"
# toda reuniao processada ganha uma subpasta aqui; um lugar so p/ ignorar no git e limpar
OUTPUT = PROJ / "output"
MODELS = PROJ / "models"

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".m4v", ".webm")


def _videos_in(d: pathlib.Path) -> list[pathlib.Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def _default_out_name() -> str:
    """Subpasta padrao em output/ = <nome do video de entrada>, p/ rastrear qual input a gerou.

    Usa VT_VIDEO se setado; senao o unico video de input/; senao cai para 'sem-video'.
    """
    import re

    cand = os.environ.get("VT_VIDEO")
    if not cand:
        vids = _videos_in(INPUT)
        cand = str(vids[0]) if len(vids) == 1 else None
    if not cand:
        return "sem-video"
    safe = re.sub(r'[<>:"/\\|?*\n\r\t]+', "", pathlib.Path(cand).stem).strip()
    return safe or "sem-video"


# VT_OUT explicito vence (relativo a raiz do projeto); senao output/<nome do video>.
_vt_out = os.environ.get("VT_OUT")
OUT = PROJ / _vt_out if _vt_out else OUTPUT / _default_out_name()
FRAMES = OUT / "frames"


def ensure_dirs() -> None:
    for d in (INPUT, OUTPUT, OUT, FRAMES):
        d.mkdir(parents=True, exist_ok=True)


def find_ffmpeg(name: str = "ffmpeg") -> pathlib.Path:
    """ffmpeg do PATH; senao procura na instalacao do winget (independe da versao)."""
    found = shutil.which(name)
    if found:
        return pathlib.Path(found)
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for exe in sorted(base.glob(f"*FFmpeg*/**/bin/{name}.exe"), reverse=True):
        return exe
    raise SystemExit(
        f"ERRO: {name} nao encontrado. Instale com: winget install --id Gyan.FFmpeg -e"
    )


def find_video(explicit: str | os.PathLike[str] | None = None) -> pathlib.Path:
    """Video a processar: argumento > VT_VIDEO > unico video em input/.

    Um nome solto ("reuniao.mp4") e resolvido contra input/ primeiro, depois contra a
    raiz do projeto — assim VIDEO= aceita so o nome do arquivo.
    """
    cand = explicit or os.environ.get("VT_VIDEO") or None
    if cand:
        p = pathlib.Path(cand)
        tentativas = [p] if p.is_absolute() else [INPUT / p, PROJ / p, p]
        for c in tentativas:
            if c.exists():
                return c.resolve()
        raise SystemExit(
            f"ERRO: video nao encontrado: {cand}\n"
            f"  procurei em {INPUT.name}/ e na raiz do projeto"
        )

    achados = _videos_in(INPUT)
    if not achados:
        soltos = _videos_in(PROJ)
        if soltos:
            nomes = "\n  ".join(p.name for p in soltos)
            raise SystemExit(
                f"ERRO: nenhum video em {INPUT.name}/, mas achei na raiz do projeto.\n"
                f"  mova para {INPUT.name}/:\n  {nomes}"
            )
        raise SystemExit(
            f"ERRO: nenhum video em {INPUT.name}/. Coloque o arquivo la "
            f'ou use VIDEO="nome.mp4"'
        )
    if len(achados) > 1:
        nomes = "\n  ".join(p.name for p in achados)
        raise SystemExit(
            f"ERRO: {len(achados)} videos em {INPUT.name}/; escolha um com "
            f'VIDEO="nome.mp4"\n  {nomes}'
        )
    return achados[0].resolve()


def skip_if_done(path: pathlib.Path, etapa: str) -> bool:
    """True se o artefato ja existe e VT_FORCE nao esta setado.

    Substitui a checagem de timestamp que o make fazia: com nome de arquivo cheio de
    espaco, alvo de make derivado de caminho nao funciona (ver CLAUDE.md).
    """
    if path.exists() and not os.environ.get("VT_FORCE"):
        print(f"{path.name} ja existe -> pulando {etapa} (FORCE=1 para refazer)")
        return True
    return False


def require(path: pathlib.Path, comando: str) -> None:
    """Aborta com instrucao acionavel quando falta um artefato de etapa anterior."""
    if not path.exists():
        raise SystemExit(f"ERRO: falta {path.name} em {path.parent.name}/ — rode: {comando}")


def read_wav_mono_f32(path: pathlib.Path, expected_rate: int | None = None) -> "object":
    """Le WAV PCM 16-bit mono como float32 em [-1, 1] (sem soundfile/librosa)."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise RuntimeError(f"esperado PCM 16-bit, veio {wf.getsampwidth() * 8}-bit")
        if expected_rate is not None and wf.getframerate() != expected_rate:
            raise RuntimeError(
                f"esperado {expected_rate} Hz, veio {wf.getframerate()} Hz "
                "(reextraia o wav com -ar 16000)"
            )
        raw = wf.readframes(wf.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if wf.getnchannels() > 1:
            audio = audio.reshape(-1, wf.getnchannels())[:, 0]
    return audio


def add_cuda_dll_dirs() -> None:
    """Registra as DLLs de cuBLAS/cuDNN dos wheels nvidia-*-cu12 (CTranslate2 as exige)."""
    if not hasattr(os, "add_dll_directory"):
        return
    nvidia = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for d in sorted(nvidia.glob("*/bin")) + sorted(nvidia.glob("*/lib")):
        if d.is_dir():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"


def hms(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
