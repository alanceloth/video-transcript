"""Diarizacao offline (quem falou quando) com sherpa-onnx, sem token do Hugging Face.

Pipeline: segmentacao pyannote-3.0 (ONNX) -> embeddings de locutor -> clustering.

Uso:
  python diarize.py                # descobre o numero de falantes (threshold)
  python diarize.py --speakers 4   # numero de falantes conhecido (bem mais preciso)
  python diarize.py --embedding resnet293 --threshold 0.6

Saida: out/diar.json  ->  [{"start": s, "end": s, "speaker": n}, ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import sherpa_onnx

import common

PROJ, MODELS = common.PROJ, common.MODELS
WAV = common.OUT / "audio.wav"
hms = common.hms
SEGMENTATION = MODELS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"

EMBEDDINGS = {
    # rapido (~29 MB), CAM++ com large-margin finetune
    "campp": MODELS / "wespeaker_en_voxceleb_CAM%2B%2B_LM.onnx",
    # mais preciso e mais lento (~114 MB)
    "resnet293": MODELS / "wespeaker_en_voxceleb_resnet293_LM.onnx",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speakers", type=int, default=-1,
                    help="numero exato de falantes; -1 = detectar via threshold")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="menor = mais falantes; so usado quando --speakers=-1")
    ap.add_argument("--embedding", choices=sorted(EMBEDDINGS), default="campp")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--out", default="diar.json")
    args = ap.parse_args()

    out = common.OUT / args.out
    if common.skip_if_done(out, "diarizacao"):
        return 0

    embedding = EMBEDDINGS[args.embedding]
    for f in (WAV, SEGMENTATION, embedding):
        if not f.exists():
            print(f"ERRO: nao existe {f}", file=sys.stderr)
            return 1

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(SEGMENTATION)
            ),
            num_threads=args.threads,
            provider="cpu",
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
            num_threads=args.threads,
            provider="cpu",
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=args.speakers, threshold=args.threshold
        ),
        # descarta fala < 0.3s e nao corta em pausas < 0.5s
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        print("ERRO: config invalida (arquivos de modelo?)", file=sys.stderr)
        return 1

    sd = sherpa_onnx.OfflineSpeakerDiarization(config)
    audio = common.read_wav_mono_f32(WAV, sd.sample_rate)
    dur = len(audio) / sd.sample_rate
    modo = f"{args.speakers} falantes fixos" if args.speakers > 0 else f"auto (threshold={args.threshold})"
    print(f"audio: {hms(dur)} | embedding: {args.embedding} | {modo}", flush=True)

    t0 = time.time()
    last = [-1]

    def progress(done: int, total: int) -> int:
        pct = int(done / total * 100)
        if pct >= last[0] + 5:
            last[0] = pct
            print(f"  {pct:3d}%  (+{(time.time() - t0) / 60:.1f}min)", flush=True)
        return 0

    result = sd.process(audio, callback=progress).sort_by_start_time()
    turns = [
        {"start": round(r.start, 3), "end": round(r.end, 3), "speaker": int(r.speaker)}
        for r in result
    ]

    out.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")

    fala: dict[int, float] = {}
    for t in turns:
        fala[t["speaker"]] = fala.get(t["speaker"], 0.0) + (t["end"] - t["start"])
    total_fala = sum(fala.values()) or 1.0

    print(f"\n{len(turns)} turnos | {len(fala)} falantes | "
          f"{(time.time() - t0) / 60:.1f} min de processamento")
    print(f"{'falante':>10}  {'tempo':>9}  {'%':>5}  turnos")
    for spk, secs in sorted(fala.items(), key=lambda kv: -kv[1]):
        n = sum(1 for t in turns if t["speaker"] == spk)
        print(f"{'speaker_%02d' % spk:>10}  {hms(secs):>9}  {100 * secs / total_fala:5.1f}  {n}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
