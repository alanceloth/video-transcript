# Transcricao de reuniao com identificacao de falante por nome real.
#
# O video de entrada mora em input/. Passe o nome do arquivo em VIDEO= — sempre entre
# aspas, porque gravacao do Teams tem espaco no nome:
#
#   make run VIDEO="Reuniao de Exemplo-20260101_100000-Gravacao de Reuniao.mp4"
#
# Cada video gera sua pasta em output/<nome do video>/ (transcricao.md, .txt, .srt...).
#
# Nenhum caminho trafega pelo mecanismo de targets do make (espaco quebraria); quem
# resolve caminho e scripts/resolve.py, e quem decide se uma etapa pode ser pulada e o
# proprio script, olhando se o artefato existe (FORCE=1 refaz).
#
# Requer sh.exe no PATH (vem com o Git for Windows) e ffmpeg (winget install Gyan.FFmpeg).

VIDEO     ?=
# vazio = o Python deriva output/<nome do video> (ver scripts/common.py)
OUT       ?=
# auto = .vtt do Teams se existir, senao diarizacao por audio | vtt | audio | badge
SPEAKER   ?= auto
OFFSET    ?= -0.6
SPEAKERS  ?= -1
EMBEDDING ?= campp
# janela de transcricao em segundos; menor = menos RAM de pico (ver scripts/transcribe.py)
WINDOW    ?= 900
VTT       ?=
SLACK     ?=
# corte de trecho (papo fora de pauta) e titulo do markdown; ver scripts/merge.py
CUT_BEFORE ?=
CUT_AFTER ?=
TITULO    ?=
FORCE     ?=

PY        := .venv/Scripts/python.exe
SYS_PY    := python
SCRIPTS   := scripts
R         := $(PY) $(SCRIPTS)/resolve.py
CORTE     := $(if $(CUT_BEFORE),--cut-before $(CUT_BEFORE)) \
             $(if $(CUT_AFTER),--cut-after $(CUT_AFTER)) \
             $(if $(TITULO),--titulo "$(TITULO)")

# tudo chega aos scripts por ambiente, nunca por argv/target
export VT_VIDEO := $(VIDEO)
export VT_OUT   := $(OUT)
export VT_FORCE := $(FORCE)

.PHONY: help setup run all audio asr badges verify merge merge-vtt merge-slack \
        merge-audio text tune diarize models new where clean clean-out distclean

help:
	@echo ""
	@echo "  make setup                      cria .venv e instala as dependencias"
	@echo "  make run VIDEO=\"arquivo.mp4\"    pipeline completo de input/arquivo.mp4 ate o markdown"
	@echo "  make where VIDEO=\"arquivo.mp4\"  mostra qual video e qual pasta de saida seriam usados"
	@echo ""
	@echo "  fonte do nome do falante (SPEAKER=):"
	@echo "    auto    .vtt do Teams, senao transcricao do Slack, senao diarizacao (default)"
	@echo "    vtt     forca os rotulos de conta do .vtt          (nomes reais, automatico)"
	@echo "    slack   transcricao do circulo do Slack            (nomes reais, automatico)"
	@echo "    audio   forca diarizacao por audio                 (Falante 1..N, sem nome)"
	@echo "    badge   badge roxo do Teams 1920x1080              (nomes reais, revisao manual)"
	@echo ""
	@echo "  etapas individuais (respeitam VIDEO=):"
	@echo "    make audio         extrai o wav 16 kHz mono"
	@echo "    make asr           transcreve com whisper large-v3 na GPU"
	@echo "    make badges        varre o video e acha o falante ativo pelo badge do Teams"
	@echo "    make verify        gera as folhas de conferencia dos nomes"
	@echo "    make merge         regera os entregaveis pelo badge (usa OFFSET)"
	@echo "    make merge-vtt     regera os entregaveis pelos falantes do .vtt"
	@echo "    make merge-slack   regera os entregaveis pela transcricao do circulo do Slack"
	@echo "    make merge-audio   regera os entregaveis com Falante 1..N"
	@echo "    make text          dump do texto puro + nomes citados na fala"
	@echo "    make tune          calibra o OFFSET de latencia do badge"
	@echo "    make diarize       agrupa vozes (SPEAKERS=4; -1 detecta)"
	@echo "    make models        baixa os modelos de diarizacao"
	@echo ""
	@echo "  saida de cada video: output/<nome do video>/"
	@echo ""
	@echo "  make new VIDEO=\"arquivo.mp4\"    apaga a saida e roda tudo de novo"
	@echo "  make clean / clean-out / distclean"
	@echo ""
	@echo "  CUT_AFTER=40:21 corta o fim (papo fora de pauta); CUT_BEFORE, TITULO tambem valem."
	@echo "  FORCE=1 refaz etapa cujo artefato ja existe."
	@echo "  variaveis: SPEAKER=$(SPEAKER) OFFSET=$(OFFSET) SPEAKERS=$(SPEAKERS) EMBEDDING=$(EMBEDDING)"
	@echo ""

setup:
	$(SYS_PY) -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt
	@mkdir -p input output
	@echo "venv pronto em .venv | coloque os videos em input/ (saida vai para output/)"

where:
	@echo "video: $$($(R) video)"
	@echo "saida: $$($(R) out)"
	@if v=$$($(R) vtt 2>/dev/null); then echo "vtt:   $$v"; \
	 else echo "vtt:   (nenhum ao lado do video)"; fi
	@if s=$$($(R) slack 2>/dev/null); then echo "slack: $$s"; \
	 else echo "slack: (nenhum ao lado do video)"; fi

# pipeline completo: audio -> asr -> falantes -> transcricao.md/.txt/.srt + turnos.json
run:
	@echo "video: $$($(R) video)"
	@echo "saida: $$($(R) out)"
	@$(PY) $(SCRIPTS)/extract_audio.py
	@$(PY) $(SCRIPTS)/transcribe.py --window $(WINDOW)
	@src="$(SPEAKER)"; \
	if [ "$$src" = auto ]; then \
	  if $(R) vtt >/dev/null 2>&1; then src=vtt; \
	    echo ""; echo "-> .vtt encontrado: usando os rotulos de conta do Teams (nomes reais)"; \
	  elif $(R) slack >/dev/null 2>&1; then src=slack; \
	    echo ""; echo "-> transcricao do circulo do Slack encontrada: usando a conta de quem falou (nomes reais)"; \
	  else src=audio; \
	    echo ""; echo "-> sem .vtt ao lado do video: caindo para diarizacao por audio"; \
	    echo "   (falantes sairao como \"Falante 1..N\"; para nomes reais coloque o .vtt em input/)"; \
	  fi; \
	fi; \
	case "$$src" in \
	  vtt) $(PY) $(SCRIPTS)/merge.py --vtt $(VTT) $(CORTE) ;; \
	  slack) $(PY) $(SCRIPTS)/merge.py --slack $(SLACK) $(CORTE) ;; \
	  audio) "$(MAKE)" --no-print-directory models \
	         && $(PY) $(SCRIPTS)/diarize.py --speakers $(SPEAKERS) --embedding $(EMBEDDING) \
	         && $(PY) $(SCRIPTS)/merge.py --audio ;; \
	  badge) $(PY) $(SCRIPTS)/active_speaker.py && $(PY) $(SCRIPTS)/verify_tiles.py \
	         && if $(R) names >/dev/null 2>&1; then $(PY) $(SCRIPTS)/merge.py --offset $(OFFSET); \
	         else o=$$($(R) out); echo ""; \
	           echo "PROXIMO PASSO (o badge nao carrega o nome, so a posicao):"; \
	           echo "  1. abra $$o/frames/verify_NN.png"; \
	           echo "  2. leia o nome no badge roxo e preencha \"name\" em $$o/tile_names.json"; \
	           echo "  3. rode: make merge VIDEO=\"$(VIDEO)\""; fi ;; \
	  *) echo "ERRO: SPEAKER=$$src invalido (use auto|vtt|slack|audio|badge)" >&2; exit 2 ;; \
	esac

# compatibilidade: o fluxo antigo era o do badge
all:
	@"$(MAKE)" --no-print-directory run SPEAKER=badge VIDEO="$(VIDEO)" OUT="$(OUT)" FORCE="$(FORCE)"

audio:
	$(PY) $(SCRIPTS)/extract_audio.py

asr:
	$(PY) $(SCRIPTS)/transcribe.py --window $(WINDOW)

badges:
	$(PY) $(SCRIPTS)/active_speaker.py

verify:
	$(PY) $(SCRIPTS)/verify_tiles.py

merge:
	$(PY) $(SCRIPTS)/merge.py --offset $(OFFSET) $(CORTE)

# falantes do .vtt do Teams (conta de quem falou) — cobertura garantida e nomes reais;
# ideal p/ reuniao grande onde o roster reflui e o badge posicional falha
merge-vtt:
	$(PY) $(SCRIPTS)/merge.py --vtt $(VTT) $(CORTE)

# falante da transcricao do circulo do Slack: a conta de quem falou, palavra por palavra.
# Equivalente do --vtt para call do Slack, onde o tile nao mostra o nome de quem fala e o
# arranjo do grid muda no meio da conversa (badge posicional nao serve).
merge-slack:
	$(PY) $(SCRIPTS)/merge.py --slack $(SLACK) $(CORTE)

merge-audio:
	$(PY) $(SCRIPTS)/merge.py --audio $(CORTE)

text:
	$(PY) $(SCRIPTS)/dump_asr.py

tune:
	$(PY) $(SCRIPTS)/tune_offset.py

diarize:
	$(PY) $(SCRIPTS)/diarize.py --speakers $(SPEAKERS) --embedding $(EMBEDDING)

# idempotente: o script pula o que ja existe (FORCE=1 rebaixa)
models:
	@$(PY) $(SCRIPTS)/download_models.py

new:
	@"$(MAKE)" --no-print-directory clean-out VIDEO="$(VIDEO)" OUT="$(OUT)"
	@"$(MAKE)" --no-print-directory run VIDEO="$(VIDEO)" OUT="$(OUT)" SPEAKER=$(SPEAKER)

# apaga os derivados mas mantem audio.wav, asr.json e tile_names.json (revisado a mao)
clean:
	@d="$$($(R) out)"; rm -rf "$$d/frames" "$$d/asr.jsonl" "$$d/asr.txt" \
	  "$$d/transcricao.md" "$$d/transcricao.txt" "$$d/transcricao.srt" "$$d/turnos.json"; \
	  echo "limpo (mantidos audio.wav, asr.json, active_speaker.json, tile_names.json): $$d"

clean-out:
	@d="$$($(R) out)"; rm -rf "$$d"; echo "removido: $$d"

distclean:
	@"$(MAKE)" --no-print-directory clean-out VIDEO="$(VIDEO)" OUT="$(OUT)"
	rm -rf .venv models
