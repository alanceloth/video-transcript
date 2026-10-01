"""Transcreve o audio da reuniao com faster-whisper large-v3 na GPU.

Processa em JANELAS, nao o audio inteiro de uma vez: o feature_extractor do
faster-whisper monta a STFT de todo o waveform em memoria e o np.fft faz upcast para
float64, o que da ~3,7 GB de pico numa reuniao de 1h20 e estoura a RAM da maquina
quando ha outros programas abertos. Em janela de 15 min o pico fica em ~1 GB e a
duracao da reuniao deixa de importar.

O corte entre janelas cai no ponto de menor energia perto do limite (ver _cut_points),
para nao partir palavra no meio. Como condition_on_previous_text=False, nao ha contexto
a perder entre janelas.

Saidas em out/:
  asr.jsonl  - um segmento por linha, escrito incrementalmente (permite acompanhar)
  asr.json   - resultado final consolidado (segmentos + palavras com timestamps)
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

import common

WAV = common.OUT / "audio.wav"
OUT_JSONL = common.OUT / "asr.jsonl"
OUT_JSON = common.OUT / "asr.json"
hms = common.hms

# As DLLs de cuBLAS/cuDNN vem dos wheels nvidia-*-cu12 e nao estao no PATH;
# CTranslate2 so as encontra se registrarmos os diretorios antes do import.
common.add_cuda_dll_dirs()

from faster_whisper import WhisperModel  # noqa: E402  (depende do add_cuda_dll_dirs acima)

# Contexto curto de dominio: melhora nomes proprios e pontuacao sem induzir alucinacao.
# (Generico p/ reunioes do dominio de falencias/credito — serve varias reunioes.)
INITIAL_PROMPT = (
    "Reunião sobre modelagem de negócio do domínio de falências e recuperação "
    "judicial: modelo de entidades, pessoa física e jurídica, órgão público, credor, advogado, "
    "administrador judicial, papel no processo, vara e juízo, caso, quadro geral de credores, "
    "crédito, classe, valoração, participação, aquisição, cessão, ativo patrimonial, bem "
    "material, ativo financeiro, direito creditório, penhora, arresto, deságio."
)


SR = 16000


def _cut_points(audio: np.ndarray, window_s: float, search_s: float = 20.0) -> list[int]:
    """Limites das janelas, cada um no vale de energia mais silencioso da regiao de busca.

    Cortar em multiplo exato de window_s partiria palavra no meio; procurar o minimo de
    energia numa faixa de +/- search_s/2 em volta faz o corte cair numa pausa.
    """
    hop = int(0.05 * SR)                      # envelope de energia a cada 50 ms
    n_hops = len(audio) // hop
    env = (audio[: n_hops * hop].reshape(n_hops, hop) ** 2).mean(axis=1)

    pts = [0]
    passo, busca = int(window_s * SR), int(search_s / 2 * SR)
    while True:
        alvo = pts[-1] + passo
        if alvo >= len(audio) - busca:        # o que resta vira a ultima janela
            break
        lo = max(pts[-1] + hop, alvo - busca) // hop
        hi = min(len(audio), alvo + busca) // hop
        if hi <= lo:
            break
        pts.append((lo + int(np.argmin(env[lo:hi]))) * hop)
    pts.append(len(audio))
    return pts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=900.0,
                    help="tamanho da janela de transcricao em segundos (default 900 = 15 min; "
                         "menor = menos RAM)")
    args = ap.parse_args()

    common.ensure_dirs()
    if common.skip_if_done(OUT_JSON, "transcricao"):
        return 0
    if not WAV.exists():
        print(f"ERRO: {WAV} nao existe (rode extract_audio.py primeiro)", file=sys.stderr)
        return 1

    t0 = time.time()
    audio = common.read_wav_mono_f32(WAV, SR)
    total = len(audio) / SR
    cortes = _cut_points(audio, args.window)
    print(f"duracao: {hms(total)} | {len(cortes) - 1} janela(s) de ~{args.window / 60:.0f} min "
          f"(corte no silencio)", flush=True)

    print("carregando large-v3 (float16, cuda)...", flush=True)
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    print(f"modelo pronto em {time.time() - t0:.1f}s", flush=True)

    collected: list[dict] = []
    idioma, prob = "", 0.0
    with OUT_JSONL.open("w", encoding="utf-8") as fh:
        for w_i, (a, b) in enumerate(zip(cortes, cortes[1:]), 1):
            off = a / SR
            print(f"\n--- janela {w_i}/{len(cortes) - 1}: {hms(off)} -> {hms(b / SR)} ---",
                  flush=True)
            segments, info = model.transcribe(
                audio[a:b],
                language="pt",
                task="transcribe",
                beam_size=5,
                word_timestamps=True,
                # Reuniao longa: nao condicionar no texto anterior evita loops de repeticao.
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=INITIAL_PROMPT,
            )
            if not idioma:
                idioma, prob = info.language, info.language_probability
                print(f"idioma: {idioma} (p={prob:.2f})", flush=True)

            for seg in segments:
                item = {
                    "id": len(collected),
                    "start": round(seg.start + off, 3),
                    "end": round(seg.end + off, 3),
                    "text": seg.text.strip(),
                    "words": [
                        {
                            "start": round(w.start + off, 3),
                            "end": round(w.end + off, 3),
                            "word": w.word,
                            "prob": round(w.probability, 3),
                        }
                        for w in (seg.words or [])
                    ],
                }
                collected.append(item)
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                fh.flush()
                pct = 100 * item["end"] / total if total else 0
                elapsed = time.time() - t0
                print(f"[{pct:5.1f}%] [{hms(item['start'])} -> {hms(item['end'])}] "
                      f"(+{elapsed / 60:.1f}min) {item['text'][:90]}", flush=True)

    OUT_JSON.write_text(
        json.dumps(
            {
                "duration": total,
                "language": idioma,
                "model": "large-v3",
                "segments": collected,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    elapsed = time.time() - t0
    speed = total / elapsed if elapsed else 0
    print(f"\nOK: {len(collected)} segmentos em {elapsed / 60:.1f} min "
          f"({speed:.1f}x tempo real) -> {OUT_JSON.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
