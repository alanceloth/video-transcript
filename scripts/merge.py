"""Cruza a transcricao (asr.json) com quem-fala e gera os entregaveis finais.

Fonte de falante (padrao): out/active_speaker.json + out/tile_names.json — o badge
roxo do Teams, que carrega o NOME REAL de quem esta falando.
Outras fontes: --vtt (rotulos de conta do VTT do Teams), --slack (transcricao do
circulo do Slack, que traz o user id de quem falou palavra por palavra) e --audio
(clusters de diarizacao por audio, sem nome).

Saidas em out/:
  transcricao.md    leitura humana: participacao + turnos com timestamp
  transcricao.txt   texto puro rotulado
  transcricao.srt   legenda para abrir junto com o video
  turnos.json       turnos estruturados
"""

from __future__ import annotations

import argparse
import bisect
import datetime
import html
import json
import pathlib
import re
import sys

import common

OUT = common.OUT
hms, srt_ts = common.hms, common.srt_ts

MERGE_GAP = 3.0        # pausa maxima para juntar dois turnos do mesmo falante
FLICKER_DUR = 0.8      # blocos curtos cercados pelo mesmo falante = ruido
FLICKER_WORDS = 3
FILL_TOL = 2.5         # segundos: distancia maxima para herdar rotulo vizinho
DESCONHECIDO = "Não identificado"
SLACK_BIN = 1.0        # s: largura do bin do histograma de alinhamento com o asr
SLACK_MIN_SUP = 20     # pares de palavra rara minimos para confiar no alinhamento
SLACK_MERGE = 1.5      # s: pausa maxima para unir palavras do mesmo falante
SLACK_EPOCH0: float | None = None   # epoch do t=0 do video, resolvido pelo Slack


def intervals_from_badge(y_tol: int = 10, offset: float = 0.0) -> list[dict]:
    """Amostras de badge (2 fps) -> intervalos [start, end) com nome do falante.

    offset desloca a linha do tempo (negativo = mais cedo) para compensar a latencia
    com que o Teams acende o badge depois que a pessoa comeca a falar.
    """
    data = json.loads((OUT / "active_speaker.json").read_text(encoding="utf-8"))
    mapa = json.loads((OUT / "tile_names.json").read_text(encoding="utf-8"))
    step = 1.0 / data["fps"]

    faltando = [m for m in mapa if not m.get("name")]
    if len(faltando) == len(mapa):
        raise SystemExit(
            f"ERRO: nenhum nome preenchido em {OUT.name}/tile_names.json.\n"
            f"Abra as folhas {OUT.name}/frames/verify_NN.png, leia o nome no badge roxo "
            f"e preencha o campo \"name\" de cada posicao. Depois rode: make merge"
        )
    if faltando:
        print(f"AVISO: {len(faltando)} de {len(mapa)} posicoes sem nome "
              f"(a fala delas ficara como \"{DESCONHECIDO}\"): "
              + ", ".join(f"lado {m['side']} y={m['yc']}" for m in faltando))

    def nome(sample: dict) -> str | None:
        melhor, dist = None, y_tol + 1
        for m in mapa:
            if m["side"] != sample["side"]:
                continue
            d = abs(m["yc"] - sample["yc"])
            if d < dist:
                melhor, dist = m, d
        return melhor["name"] if melhor else None

    out: list[dict] = []
    for s in sorted(data["samples"], key=lambda x: x["t"]):
        n = nome(s)
        if n is None:
            continue
        t = max(0.0, s["t"] + offset)
        if out and out[-1]["speaker"] == n and t - out[-1]["end"] <= step * 1.5:
            out[-1]["end"] = t + step
        else:
            out.append({"start": t, "end": t + step, "speaker": n})
    return out


def intervals_from_audio() -> list[dict]:
    turns = json.loads((OUT / "diar.json").read_text(encoding="utf-8"))
    return [{"start": t["start"], "end": t["end"], "speaker": f"Falante {t['speaker'] + 1}"}
            for t in turns]


def _locate_vtt(explicit: str | None) -> pathlib.Path:
    """Acha o .vtt do Teams: caminho explicito > ao lado do video > unico em OUT."""
    if explicit:
        p = pathlib.Path(explicit)
        if not p.exists() and not p.is_absolute():
            p = common.PROJ / explicit
        if p.exists():
            return p
        raise SystemExit(f"ERRO: VTT nao encontrado: {explicit}")
    try:
        vid = common.find_video()
        if vid.with_suffix(".vtt").exists():
            return vid.with_suffix(".vtt")
        # Teams costuma cortar o sufixo (timestamp/"Meeting Recording") do nome do .vtt
        cands = sorted(vid.parent.glob("*.vtt"))
        for c in cands:
            if vid.stem.startswith(c.stem) or c.stem.startswith(vid.stem[:20]):
                return c
        if len(cands) == 1:
            return cands[0]
    except SystemExit:
        pass
    outv = sorted(OUT.glob("*.vtt"))
    if len(outv) == 1:
        return outv[0]
    raise SystemExit("ERRO: nao localizei o .vtt; informe com --vtt CAMINHO")


def _vtt_ts(s: str) -> float:
    hh, mm, rest = s.replace(",", ".").split(":")
    return int(hh) * 3600 + int(mm) * 60 + float(rest)


def intervals_from_vtt(path: str | None = None) -> list[dict]:
    """Rotulos de falante do VTT do Teams = a CONTA de quem falou (confiavel, nao e
    diarizacao por audio nem chute). Bom para reuniao com muita gente / roster que reflui,
    onde o badge posicional falha. Casa por tempo com o texto do whisper -> cobertura total."""
    vtt = _locate_vtt(path)
    text = vtt.read_text(encoding="utf-8-sig")
    ivs: list[dict] = []
    for b in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d\d:\d\d:\d\d[.,]\d+)\s*-->\s*(\d\d:\d\d:\d\d[.,]\d+)", b)
        v = re.search(r"<v\s+([^>]+?)>", b)
        if not m or not v:
            continue
        name = re.split(r"\s*\|\s*", html.unescape(v.group(1)).strip())[0].strip()
        ivs.append({"start": _vtt_ts(m.group(1)), "end": _vtt_ts(m.group(2)), "speaker": name})
    ivs.sort(key=lambda x: x["start"])
    if not ivs:
        raise SystemExit(f"ERRO: nenhuma fala <v ...> no VTT {vtt.name}")
    print(f"VTT: {vtt.name} ({len(ivs)} falas)")
    return ivs


def _locate_slack(explicit: str | None) -> pathlib.Path:
    """Acha a transcricao do circulo do Slack: explicito > ao lado do video > OUT.

    O arquivo e o doc "Transcricao do circulo" que o Slack gera quando as Anotacoes da
    IA estao ligadas (so aparece depois que o circulo termina). Convencao aqui: salvar
    ao lado do video como <nome do video>.slack.json.
    """
    if explicit:
        p = pathlib.Path(explicit)
        if not p.exists() and not p.is_absolute():
            p = common.PROJ / explicit
        if p.exists():
            return p
        raise SystemExit(f"ERRO: transcricao do Slack nao encontrada: {explicit}")
    cands: list[pathlib.Path] = []
    try:
        vid = common.find_video()
        exato = vid.parent / (vid.stem + ".slack.json")
        if exato.exists():
            return exato
        cands = sorted(vid.parent.glob("*.slack.json"))
    except SystemExit:
        pass
    cands += sorted(common.INPUT.glob("*.slack.json")) + sorted(OUT.glob("*.slack.json"))
    if len(cands) == 1:
        return cands[0]
    raise SystemExit(
        "ERRO: nao localizei a transcricao do circulo do Slack.\n"
        "  baixe o doc \"Transcricao do circulo\" da thread do circulo e salve como\n"
        "  input/<nome do video>.slack.json, ou informe com --slack CAMINHO"
    )


def _slack_items(path: pathlib.Path) -> list[dict]:
    """Palavras da transcricao do Slack: t em epoch, texto e user id de quem falou.

    Formato do AWS Transcribe em streaming: lista de blocos -> transcript.results ->
    alternatives[0].items. Resultado com isPartial=True e hipotese intermediaria e
    repete texto, fica de fora; type "2" e pontuacao (duracao zero).
    O speakerExternalUserId vem como "<team>-<sala>-<user id>[-<sufixo de convidado>]",
    entao o user id e o primeiro token que comeca com U.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    itens: list[dict] = []
    for bloco in data:
        for r in (bloco.get("transcript") or {}).get("results") or []:
            if r.get("isPartial"):
                continue
            alts = r.get("alternatives") or []
            for it in (alts[0].get("items") if alts else []) or []:
                m = re.search(r"U[A-Z0-9]{6,}", it.get("speakerExternalUserId") or "")
                itens.append({
                    "start": it["startTimeMs"] / 1000.0,
                    "end": it["endTimeMs"] / 1000.0,
                    "word": it.get("content", ""),
                    "pontuacao": it.get("type") == "2",
                    "uid": m.group(0) if m else None,
                })
    itens.sort(key=lambda x: x["start"])
    return itens


def _slack_nomes() -> dict[str, str]:
    """Mapa user id -> nome, de slack_users.json na raiz do projeto (opcional)."""
    p = common.PROJ / "slack_users.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _norm(w: str) -> str:
    return re.sub(r"\W+", "", w, flags=re.UNICODE).lower()


def _align_epoch(itens: list[dict], asr: dict) -> float:
    """Epoch (s) do t=0 do video, casando palavras raras com as do asr.json.

    O Slack marca o tempo em epoch; o whisper, em segundos desde o inicio do video. Nao
    da para usar o mtime do arquivo (muda ao copiar o video) nem o inicio do circulo (a
    gravacao comeca antes ou depois), entao o deslocamento sai do proprio texto: para
    cada palavra longa que aparece poucas vezes nos dois lados, o candidato e
    (epoch do Slack - t do whisper). O modo do histograma e o deslocamento real, e a
    mediana do que caiu no modo refina.
    """
    def indexa(pares) -> dict[str, list[float]]:
        d: dict[str, list[float]] = {}
        for t, w in pares:
            if len(w) >= 6:
                d.setdefault(w, []).append(t)
        return {w: ts for w, ts in d.items() if len(ts) <= 3}

    wh = indexa((wd["start"], _norm(wd["word"]))
                for seg in asr["segments"] for wd in (seg.get("words") or []))
    sl = indexa((it["start"], _norm(it["word"]))
                for it in itens if not it["pontuacao"])
    deltas = [s - w for palavra, ts in sl.items() if palavra in wh
              for s in ts for w in wh[palavra]]
    if not deltas:
        raise SystemExit(
            "ERRO: nenhuma palavra em comum entre o asr.json e a transcricao do Slack "
            "\u2014 o JSON e de outra reuniao? Se nao, informe --slack-epoch0"
        )
    hist: dict[int, int] = {}
    for d in deltas:
        b = round(d / SLACK_BIN)
        hist[b] = hist.get(b, 0) + 1
    modo = max(hist.items(), key=lambda kv: (kv[1], -abs(kv[0])))[0]
    apoio = sorted(d for d in deltas if abs(d - modo * SLACK_BIN) <= 1.5 * SLACK_BIN)
    epoch0 = apoio[len(apoio) // 2]
    disp = (apoio[-1] - apoio[0]) if apoio else 0.0
    print(f"alinhamento Slack<->whisper: t=0 do video = epoch {epoch0:.3f} "
          f"({len(apoio)} pares de apoio de {len(deltas)}, dispersao {disp * 1000:.0f} ms)")
    if len(apoio) < SLACK_MIN_SUP:
        print(f"AVISO: apenas {len(apoio)} pares de apoio (< {SLACK_MIN_SUP}); "
              "confira o resultado ou passe --slack-epoch0")
    return epoch0


def intervals_from_slack(path: str | None = None, epoch0: float | None = None,
                         asr: dict | None = None) -> list[dict]:
    """Falante palavra por palavra, da transcricao do circulo do Slack.

    E o equivalente do VTT do Teams: o rotulo e a CONTA de quem falou (nao e diarizacao
    nem chute), aqui com granularidade de palavra. Resolve o caso em que o badge
    posicional nao serve \u2014 no Slack o arranjo dos tiles muda quando alguem entra, sai
    ou liga a camera, e o tile nao mostra o nome de quem esta falando.
    """
    p = _locate_slack(path)
    itens = _slack_items(p)
    if not itens:
        raise SystemExit(f"ERRO: nenhuma palavra na transcricao do Slack {p.name}")
    if epoch0 is None:
        if asr is None:
            raise SystemExit("ERRO: sem asr.json nao da para alinhar; use --slack-epoch0")
        epoch0 = _align_epoch(itens, asr)
    global SLACK_EPOCH0
    SLACK_EPOCH0 = epoch0

    nomes = _slack_nomes()
    faltando = sorted({i["uid"] for i in itens if i["uid"] and i["uid"] not in nomes})
    if faltando:
        print(f"AVISO: {len(faltando)} user id sem nome em slack_users.json "
              f"(sairao como o proprio id): {', '.join(faltando)}")

    ivs: list[dict] = []
    for it in itens:
        if it["pontuacao"] or not it["uid"]:
            continue
        nome = nomes.get(it["uid"], it["uid"])
        s = it["start"] - epoch0
        e = max(it["end"] - epoch0, s + 0.05)
        if ivs and ivs[-1]["speaker"] == nome and s - ivs[-1]["end"] <= SLACK_MERGE:
            ivs[-1]["end"] = max(ivs[-1]["end"], e)
        else:
            ivs.append({"start": s, "end": e, "speaker": nome})
    cobertura = sum(t["end"] - t["start"] for t in ivs)
    print(f"Slack: {p.name} ({len(itens)} palavras, {len(ivs)} turnos, "
          f"{hms(ivs[0]['start'])}..{hms(ivs[-1]['end'])} do video, "
          f"{hms(cobertura)} de fala)")
    return ivs


def _parse_tempo(s: str | None) -> float | None:
    """SS, MM:SS ou HH:MM:SS -> segundos."""
    if not s:
        return None
    try:
        vals = [float(x) for x in str(s).split(":")]
    except ValueError:
        raise SystemExit(f"ERRO: tempo invalido: {s} (use SS, MM:SS ou HH:MM:SS)")
    total = 0.0
    for v in vals:
        total = total * 60 + v
    return total


def speaker_for(start: float, end: float, iv: list[dict], starts: list[float]) -> str | None:
    """Falante com maior sobreposicao; se nao houver, o mais proximo dentro de FILL_TOL."""
    best, best_ov = None, 0.0
    i = max(0, bisect.bisect_left(starts, start) - 4)
    for t in iv[i:]:
        if t["start"] >= end:
            break
        ov = min(end, t["end"]) - max(start, t["start"])
        if ov > best_ov:
            best, best_ov = t["speaker"], ov
    if best is not None:
        return best
    near, near_d = None, FILL_TOL
    for t in iv[max(0, i) : i + 16]:
        d = t["start"] - end if t["start"] > end else start - t["end"]
        if 0 <= d < near_d:
            near, near_d = t["speaker"], d
    return near


def build_blocks(segments: list[dict], iv: list[dict]) -> tuple[list[dict], dict]:
    starts = [t["start"] for t in iv]
    words: list[dict] = []
    for seg in segments:
        if seg.get("words"):
            words.extend({"start": w["start"], "end": w["end"], "word": w["word"]}
                          for w in seg["words"])
        else:
            words.append({"start": seg["start"], "end": seg["end"],
                          "word": " " + seg["text"]})

    stats = {"palavras": len(words), "com_rotulo": 0, "herdado": 0, "sem_rotulo": 0}
    prev = None
    for w in words:
        spk = speaker_for(w["start"], w["end"], iv, starts)
        if spk is not None:
            stats["com_rotulo"] += 1
        elif prev is not None:
            spk, _ = prev, stats.__setitem__("herdado", stats["herdado"] + 1)
        else:
            spk = DESCONHECIDO
            stats["sem_rotulo"] += 1
        w["speaker"] = spk
        prev = spk

    blocks: list[dict] = []
    for w in words:
        if blocks and blocks[-1]["speaker"] == w["speaker"]:
            blocks[-1]["end"] = w["end"]
            blocks[-1]["words"].append(w["word"])
        else:
            blocks.append({"speaker": w["speaker"], "start": w["start"],
                           "end": w["end"], "words": [w["word"]]})

    smoothed: list[dict] = []
    for i, b in enumerate(blocks):
        curto = (b["end"] - b["start"]) < FLICKER_DUR and len(b["words"]) <= FLICKER_WORDS
        entre_iguais = (
            0 < i < len(blocks) - 1
            and blocks[i - 1]["speaker"] == blocks[i + 1]["speaker"]
            and blocks[i - 1]["speaker"] != b["speaker"]
        )
        if curto and entre_iguais and smoothed:
            smoothed[-1]["end"] = b["end"]
            smoothed[-1]["words"].extend(b["words"])
            continue
        if smoothed and smoothed[-1]["speaker"] == b["speaker"]:
            smoothed[-1]["end"] = b["end"]
            smoothed[-1]["words"].extend(b["words"])
        else:
            smoothed.append(dict(b))

    merged: list[dict] = []
    for b in smoothed:
        if (merged and merged[-1]["speaker"] == b["speaker"]
                and b["start"] - merged[-1]["end"] <= MERGE_GAP):
            merged[-1]["end"] = b["end"]
            merged[-1]["words"].extend(b["words"])
        else:
            merged.append(dict(b))

    for b in merged:
        b["text"] = "".join(b.pop("words")).strip()
    return [b for b in merged if b["text"]], stats


def titulo_e_data(inicio_epoch: float | None = None) -> tuple[str, str]:
    """Deriva titulo e data do nome do arquivo do video.

    Gravacoes do Teams vem como "<assunto>-<AAAAMMDD>_<HHMMSS>-Gravacao de Reuniao.mp4".
    Gravacao de tela (circulo do Slack) vem como "Gravando AAAA-MM-DD HHMMSS.mp4", e ali
    o horario e o do FIM do arquivo, nao o do inicio da conversa — por isso, quando o
    inicio real e conhecido (inicio_epoch, que o alinhamento com o Slack resolve), ele
    tem prioridade sobre o nome.
    """
    try:
        nome = common.find_video().stem
    except SystemExit:
        return "Reunião", ""
    if inicio_epoch:
        dt = datetime.datetime.fromtimestamp(inicio_epoch)
        return nome, f" · gravação de {dt:%d/%m/%Y %H:%M}"
    m = re.match(r"^(?P<assunto>.+?)-(?P<d>\d{8})_(?P<h>\d{6})(?:-.*)?$", nome)
    if not m:
        return nome, ""
    d, h = m.group("d"), m.group("h")
    return (m.group("assunto").strip(),
            f" · gravação de {d[6:8]}/{d[4:6]}/{d[0:4]} {h[0:2]}:{h[2:4]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", action="store_true",
                    help="usa diar.json (clusters de audio) em vez do badge do Teams")
    ap.add_argument("--vtt", nargs="?", const="", default=None,
                    help="usa os rotulos de falante do VTT do Teams (conta de quem falou); "
                         "opcionalmente o caminho do .vtt (senao tenta localizar). "
                         "Ideal p/ reuniao grande onde o badge posicional falha.")
    ap.add_argument("--slack", nargs="?", const="", default=None,
                    help="usa a transcricao do circulo do Slack (conta de quem falou, "
                         "palavra por palavra); opcionalmente o caminho do .slack.json")
    ap.add_argument("--slack-epoch0", type=float, default=None,
                    help="epoch (s) do t=0 do video; sem isso o alinhamento sai do texto")
    ap.add_argument("--cut-before", default=None,
                    help="descarta o que vem antes deste tempo (SS, MM:SS ou HH:MM:SS)")
    ap.add_argument("--cut-after", default=None,
                    help="descarta o que vem depois deste tempo (ex.: papo fora de pauta "
                         "no fim da call)")
    ap.add_argument("--titulo", default=None,
                    help="titulo do markdown (default: derivado do nome do arquivo)")
    ap.add_argument("--offset", type=float, default=-0.6,
                    help="compensacao da latencia do badge do Teams, em segundos "
                         "(calibrado por scripts/tune_offset.py)")
    args = ap.parse_args()

    common.require(OUT / "asr.json", "make asr")
    asr = json.loads((OUT / "asr.json").read_text(encoding="utf-8"))
    try:
        if args.vtt is not None:
            iv = intervals_from_vtt(args.vtt or None)
            fonte = "rótulos de conta do Teams (VTT)"
        elif args.slack is not None:
            iv = intervals_from_slack(args.slack or None, args.slack_epoch0, asr)
            fonte = "transcrição do círculo do Slack (conta de quem falou)"
        elif args.audio:
            iv = intervals_from_audio()
            fonte = "diarização por áudio (sherpa-onnx)"
        else:
            iv = intervals_from_badge(offset=args.offset)
            fonte = "badge de falante ativo do Teams"
    except FileNotFoundError as e:
        print(f"ERRO: falta {e.filename}", file=sys.stderr)
        return 1
    titulo, gravado_em = titulo_e_data(SLACK_EPOCH0)
    if args.titulo:
        titulo = args.titulo

    # corte de trecho (papo fora de pauta no fim, aquecimento no começo): recorta as
    # PALAVRAS, nao so os segmentos, para meia frase nao atravessar a fronteira
    ini = _parse_tempo(args.cut_before) or 0.0
    fim = _parse_tempo(args.cut_after)
    segmentos = asr["segments"]
    if ini or fim is not None:
        lim = fim if fim is not None else asr["duration"]
        mantidos = []
        for seg in segmentos:
            if seg["end"] <= ini or seg["start"] >= lim:
                continue
            s = dict(seg)
            if s.get("words"):
                s["words"] = [w for w in s["words"]
                              if w["start"] >= ini and w["end"] <= lim]
                if not s["words"]:
                    continue
                s["text"] = "".join(w["word"] for w in s["words"]).strip()
            mantidos.append(s)
        print(f"corte: mantendo {hms(ini)}..{hms(lim)} "
              f"({len(mantidos)} de {len(segmentos)} segmentos)")
        segmentos = mantidos

    blocks, stats = build_blocks(segmentos, iv)

    fala: dict[str, float] = {}
    palavras: dict[str, int] = {}
    for b in blocks:
        fala[b["speaker"]] = fala.get(b["speaker"], 0.0) + (b["end"] - b["start"])
        palavras[b["speaker"]] = palavras.get(b["speaker"], 0) + len(b["text"].split())
    total = sum(fala.values()) or 1.0
    ordem = sorted(fala.items(), key=lambda kv: -kv[1])

    (OUT / "turnos.json").write_text(
        json.dumps([{"start": round(b["start"], 2), "end": round(b["end"], 2),
                     "falante": b["speaker"], "text": b["text"]} for b in blocks],
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    md = [
        f"# Transcrição — {titulo}",
        "",
        f"- **Duração:** {hms(asr['duration'])}{gravado_em}",
        f"- **Transcrição:** Whisper `large-v3` local na GPU · idioma `{asr['language']}` "
        f"· {sum(len(b['text'].split()) for b in blocks):,} palavras".replace(",", "."),
        f"- **Falantes:** {fonte}",
        f"- **Turnos:** {len(blocks)} · **participantes com fala:** "
        f"{len([k for k in fala if k != DESCONHECIDO])}",
    ]
    if ini or fim is not None:
        md.append(
            f"- **Trecho:** {hms(ini)}–{hms(fim if fim is not None else asr['duration'])} "
            f"de {hms(asr['duration'])} de gravação"
        )
    md += [
        "",
        "## Participação",
        "",
        "| Participante | Tempo de fala | % | Palavras |",
        "|---|---:|---:|---:|",
    ]
    for spk, secs in ordem:
        md.append(f"| {spk} | {hms(secs)} | {100 * secs / total:.1f}% | "
                  f"{palavras.get(spk, 0):,} |".replace(",", "."))
    md += ["", "## Transcrição", ""]
    for b in blocks:
        md.append(f"**[{hms(b['start'])}] {b['speaker']}:** {b['text']}")
        md.append("")
    (OUT / "transcricao.md").write_text("\n".join(md), encoding="utf-8")

    (OUT / "transcricao.txt").write_text(
        "\n\n".join(f"[{hms(b['start'])}] {b['speaker']}: {b['text']}" for b in blocks),
        encoding="utf-8",
    )

    starts = [t["start"] for t in iv]
    srt = []
    for i, seg in enumerate(segmentos, 1):
        spk = speaker_for(seg["start"], seg["end"], iv, starts) or DESCONHECIDO
        srt.append(f"{i}\n{srt_ts(seg['start'])} --> {srt_ts(seg['end'])}\n"
                   f"[{spk}] {seg['text']}\n")
    (OUT / "transcricao.srt").write_text("\n".join(srt), encoding="utf-8")

    pw = stats["palavras"]
    print(f"fonte de falante: {fonte}")
    print(f"palavras: {pw} | rotulo direto: {100 * stats['com_rotulo'] / pw:.1f}% "
          f"| herdado do vizinho: {100 * stats['herdado'] / pw:.1f}% "
          f"| sem rotulo: {100 * stats['sem_rotulo'] / pw:.1f}%")
    print(f"{len(blocks)} turnos\n{'participante':>22}  {'tempo':>9}  {'%':>5}")
    for spk, secs in ordem:
        print(f"{spk:>22}  {hms(secs):>9}  {100 * secs / total:5.1f}")
    for f in ("transcricao.md", "transcricao.txt", "transcricao.srt", "turnos.json"):
        print(f"-> {(OUT / f).relative_to(common.PROJ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
