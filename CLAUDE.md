# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Pipeline **local** (nada de API) para transcrever gravação de reunião com identificação de falante
por **nome real**. Cobre gravação do **Teams** e gravação de tela de **círculo (huddle) do Slack**.
O vídeo de entrada vai em `input/`; cada reunião gera sua própria pasta
`output/<nome do vídeo>/`. Roda em Windows com GPU NVIDIA. Repositório git (GitHub pessoal,
privado); não tem suíte de testes nem linter configurado. Guia de primeiro uso no `README.md`.

## Setup e dependências externas

```bash
rtk make setup        # cria .venv, instala requirements.txt e cria input/ e output/
rtk make models       # scripts/download_models.py: modelos ONNX de diarização (só p/ o caminho por áudio)
```

Pré-requisitos fora do Python:
- **ffmpeg + ffprobe** — `winget install --id Gyan.FFmpeg -e`. `common.find_ffmpeg()` procura no PATH
  e, se não achar, varre a instalação do winget.
- **sh.exe no PATH** — o Makefile usa `rm -rf`, `mkdir -p`, `case` (Git for Windows).
- **GPU NVIDIA com ~5 GB de VRAM** — `transcribe.py` fixa `device="cuda"`, `float16`, sem fallback.

## Comandos

O vídeo vai em `input/` e o nome do arquivo é o parâmetro. **Sempre entre aspas** — gravação do Teams
tem espaço no nome:

```bash
rtk make run VIDEO="Reunião de Exemplo-20260101_100000-Gravação de Reunião.mp4"
```

Isso vai do vídeo ao markdown num comando: `audio → asr → falantes → transcricao.md/.txt/.srt +
turnos.json`. `VIDEO=` é opcional quando há **um único** vídeo em `input/`.

A fonte do nome do falante é escolhida por `SPEAKER=`:

| `SPEAKER=` | Como resolve o falante | Nome real |
|---|---|---|
| `auto` (default) | `.vtt` do Teams, senão `.slack.json`, senão diarização por áudio | Depende |
| `vtt` | Rótulos de conta do `.vtt` do Teams | Sim, automático |
| `slack` | Transcrição do círculo do Slack (`.slack.json`) | Sim, automático |
| `audio` | Diarização por áudio (sherpa-onnx) | Não (`Falante 1..N`) |
| `badge` | Badge roxo do Teams 1920×1080; para na revisão manual dos nomes | Sim, após revisão |

Para nomes reais sem trabalho manual: exporte o `.vtt` do Teams (ou a transcrição do círculo do
Slack, ver abaixo) e coloque em `input/` — o `auto` acha e usa. `make where VIDEO="..."` mostra qual
vídeo, qual pasta de saída e se achou `.vtt` ou `.slack.json`, sem processar nada.

Etapas individuais (todas respeitam `VIDEO=`/`OUT=`): `audio` `asr` `badges` `verify` `merge`
`merge-vtt` `merge-slack` `merge-audio` `text` `tune` `diarize` `models`.

Os alvos de `merge*` aceitam `CUT_BEFORE=`/`CUT_AFTER=` (`SS`, `MM:SS` ou `HH:MM:SS`) para descartar
trecho — o caso real é o papo fora de pauta no fim da call — e `TITULO=` para o H1 do markdown. O
corte é por **palavra**, não por segmento, para meia frase não atravessar a fronteira.

Utilitários: `where` `new` `clean` `clean-out` `distclean`. `make help` lista tudo.

**Idempotência é dos scripts, não do make** (ver invariante abaixo): cada etapa cara pula se o
artefato já existe e imprime `X ja existe -> pulando ...`. Use `FORCE=1` para refazer. Isso torna
`make run` naturalmente retomável depois de uma falha no meio.

### Como validar uma mudança (não há testes)

A verificação é empírica, por três sinais:
- **`merge` imprime a qualidade da atribuição**: `% rótulo direto / herdado do vizinho / sem rótulo`.
  Referência boa: 99,7% direto (reunião do Teams, caminho badge) e 99,2% direto / 0% sem rótulo
  (círculo do Slack, caminho `--slack`). Queda aí = atribuição piorou.
- **O caminho `--slack` imprime o alinhamento**: `N pares de apoio` e `dispersão`. Centenas de pares
  com dispersão de poucos segundos = alinhamento confiável; dezenas = desconfie do resultado.
- **`make tune`** varre offsets de 0 a −2,4 s e minimiza `fragmentos` (turnos de ≤3 palavras) e
  `d_media` (distância da troca de falante até a fronteira de segmento do ASR).
- **`verify_tiles` imprime um sparkline por decil** da reunião para cada posição de tile — revela se
  a posição trocou de dono no meio (roster refluiu).

## Arquitetura

Pipeline de artefatos em disco: cada script é uma etapa idempotente que lê e escreve JSON em `$OUT`.
O acoplamento é **pelos arquivos**, não por imports — qualquer etapa roda sozinha se os arquivos de
entrada existirem. Exceções: `tune_offset.py` e `resolve.py` importam `merge` como biblioteca.

```
input/<video>  ──> extract_audio ──> audio.wav ──> transcribe ──> asr.json   (segmentos + palavras c/ ts)
      │                                  │
      │                                  └───────> diarize ────> diar.json   (clusters de voz, sem nome)
      │
      └──> active_speaker ──> active_speaker.json ──> verify_tiles ──> frames/verify_NN.png
                                                                      tile_names.json  (preenchido À MÃO)
input/<video>.vtt ─────────────────────────────────────────────┐
input/<video>.slack.json + slack_users.json ───────────────────┤
                                                                ├──> merge ──> transcricao.md / .txt / .srt
                                        asr.json ───────────────┘                turnos.json
```

**A decisão central:** ASR e atribuição de falante são eixos independentes. O `merge` cruza os dois
**palavra por palavra**, então trocar a fonte de falante não exige reprocessar o áudio.

### Invariante: nenhum caminho trafega pelo mecanismo de targets do make

Nome de gravação do Teams tem espaço, e o make não sabe lidar com isso — alvo ou prerequisite
derivado de caminho com espaço vira vários alvos (`target 'de' given more than once`), quebra o
controle de dependência e transforma `rm -rf "$(OUT)"` em `rm -rf` com N argumentos que **não apaga
nada, silenciosamente**. Por isso:

- Todos os targets são `.PHONY`; nenhum é derivado de `VIDEO`/`OUT`. A única exceção é `$(SEG_MODEL)`,
  cujo caminho é fixo e sem espaço.
- Caminho chega aos scripts **só por variável de ambiente** (`VT_VIDEO`, `VT_OUT`, `VT_FORCE`).
- Quem resolve caminho é **`scripts/resolve.py`** (`video` | `out` | `vtt` | `slack` | `names`), que imprime em
  formato POSIX; o Makefile consome sempre entre aspas: `d="$$($(R) out)"`.
- `$(MAKE)` também vai entre aspas — no Windows ele expande para `C:/Program Files (x86)/.../make`
  e os parênteses quebram o `sh`.

Ao mexer no Makefile: **não "restaure" targets de arquivo para ganhar incrementalidade** — essa
responsabilidade é do `common.skip_if_done()`.

### `active_speaker.py` + `verify_tiles.py`: por que são dois passos

O Teams pinta o badge do falante ativo com o roxo da marca (`#6264A7`). `active_speaker.py` varre
duas faixas verticais a 2 fps e registra **geometria**, não identidade: `(t, side, yc, px)`. Não
assume grade fixa de tiles, porque o layout do roster muda durante a reunião.

`verify_tiles.py` descobre a grade *a posteriori*, agrupando os `yc` observados com tolerância de
10 px, e recorta 5 amostras espalhadas no tempo de cada grupo num contato-sheet. O nome sai da
**leitura desses PNGs** (por humano ou por Claude) para `tile_names.json` — o mapeamento
posição→nome nunca é chutado. `make run SPEAKER=badge` para nesse ponto com instruções e sai com
código 0; `resolve.py names` é o que detecta se já há nome preenchido.

### O falante de call do Slack vem da transcrição do círculo, não dos pixels

Gravação de círculo do Slack **não tem badge com nome**: o tile mostra só o vídeo da pessoa, e o
arranjo do grid muda no meio da conversa (2×2, 3+2, 2+1 conforme gente entra, sai ou liga a câmera).
O sinal visual de quem fala existe — uma **pílula branca com barras verdes** no canto inferior
esquerdo do tile de quem está falando (`R≈100, G≈200, B≈115`), contra pílula escura com microfone
cortado para quem está mudo — mas ele entrega **posição**, e no Slack posição não identifica pessoa.
Por isso o caminho posicional (`badge`) não foi portado.

O que resolve é o doc **"Transcrição do círculo"** que o Slack gera quando as *Anotações da IA* estão
ligadas: JSON no formato do AWS Transcribe em streaming, com **timestamp e user id por palavra**.
É o mesmo papel do `.vtt` do Teams (rótulo = a CONTA de quem falou, não diarização), só com
granularidade melhor. Como pegar:

1. na thread do círculo no Slack, abra as anotações da IA e baixe o anexo `transcricao_do_circulo`;
2. salve em `input/` como `<nome do vídeo>.slack.json`;
3. `make run` (ou `make merge-slack`) acha sozinho.

`slack_users.json` na raiz do projeto mapeia user id → nome (`{"U00000000AA": "Nome Sobrenome"}`, ver `slack_users.example.json`); ele é
do workspace, não da reunião, então cresce e se reaproveita. User id sem nome sai como o próprio id,
com aviso — nunca é chutado.

**O alinhamento é o único ponto delicado.** O Slack marca tempo em epoch; o whisper, em segundos
desde o início do vídeo. Não dá para usar o mtime do arquivo (muda ao copiar) nem o início do
círculo (a gravação começa antes ou depois), então `_align_epoch()` tira o deslocamento **do próprio
texto**: para cada palavra de 6+ caracteres que aparece no máximo 3 vezes de cada lado, o candidato é
`epoch do Slack − t do whisper`; o modo do histograma (bin de 1 s) é o deslocamento, e a mediana dos
que caíram no modo refina. Num círculo real deu 722 pares de apoio e bateu com o mtime menos a
duração, ao segundo. `--slack-epoch0` força o valor se algum dia isso falhar.

### `transcribe.py` processa em janelas (não é opcional)

O `feature_extractor` do faster-whisper monta a STFT do waveform **inteiro** em memória, e o
`np.fft.rfft` faz upcast de float32 para float64 — numa reunião de 1h20 isso é ~3,7 GB de pico
(0,67 GiB do array com janela Hann + 1,34 GiB do upcast + 1,35 GiB da saída complex128), e estoura a
RAM da máquina com outros programas abertos. O `chunk_length` do faster-whisper **não** resolve: ele
só dimensiona a janela do modelo, as features continuam sendo calculadas para todo o áudio.

Por isso `transcribe.py` fatia o áudio em janelas de `--window` segundos (default 900 = 15 min,
`WINDOW=` no Makefile) e transcreve cada uma, somando o offset nos timestamps de segmento e de
palavra. Pico por janela: ~0,8 GB, independente da duração da reunião.

`_cut_points()` escolhe o limite de cada janela no **vale de energia** mais silencioso numa faixa de
±10 s em volta do múltiplo de `window`, para não partir palavra no meio. Medido no vídeo de
arquitetura (1h18, 6 janelas): 4 dos 5 cortes caíram abaixo de 1% do RMS médio. Se não houver pausa
real na faixa de busca, o corte cai no ponto menos ruim — aceitável, já que
`condition_on_previous_text=False` significa que não há contexto a perder entre janelas.

### `merge.py` é o coração

1. Normaliza qualquer fonte para `[{start, end, speaker}]`.
2. Atribui falante **por palavra** (não por segmento) pela maior sobreposição temporal; sem
   sobreposição, o mais próximo dentro de `FILL_TOL` (2,5 s); ainda nada, herda do anterior.
3. `OFFSET` negativo compensa a latência com que o Teams acende o badge — sem isso as primeiras
   palavras de cada turno caem no falante anterior.
4. Suaviza flicker (bloco < 0,8 s e ≤ 3 palavras cercado pelo mesmo falante) e junta turnos
   contíguos do mesmo falante com pausa ≤ `MERGE_GAP` (3 s).

### Contrato de ambiente (`common.py`)

- `VT_VIDEO` — nome do arquivo em `input/`, ou caminho. `find_video()` resolve nome solto contra
  `input/` primeiro, depois a raiz do projeto. Vazio = o **único** vídeo de `input/` (erro explícito
  se houver 0 ou >1, e mensagem específica se achar vídeo solto na raiz).
- `VT_OUT` — diretório de saída. Vazio = derivado: `output/<nome do vídeo>` (`common.OUTPUT`), para
  rastrear qual input gerou o quê. Explícito = relativo à raiz do projeto.
- `VT_FORCE` — refaz etapa cujo artefato já existe (`skip_if_done`).
- `add_cuda_dll_dirs()` **precisa** rodar antes de `import faster_whisper` — as DLLs de cuBLAS/cuDNN
  vêm dos wheels `nvidia-*-cu12` e não estão no PATH.
- `require(path, comando)` — pré-condição com instrução acionável; substitui os prerequisites que o
  make fazia.
- `read_wav_mono_f32(path, expected_rate)` — leitor de WAV PCM 16-bit sem soundfile/librosa; usado
  por `transcribe.py` e `diarize.py`.

## Armadilhas conhecidas

1. **Coordenadas do badge são cravadas** para 1920×1080 com roster à direita: `active_speaker.py:27`
   (`LEFT_X, RIGHT_X = 1682, 1800`) e `verify_tiles.py:25` (`BADGE_X, BADGE_W, BADGE_H`). Quebra em
   720p/1440p/4K, Zoom, Meet, gravação de tela, tela cheia de conteúdo, speaker view. Para outro
   layout, recalibrar com `python scripts/probe_badges.py 00:10:00 00:30:00`.
2. **`merge` assume mapeamento posição→nome fixo** para toda a reunião. Roster que reflui (reunião
   grande) gera nomes errados — usar `SPEAKER=vtt`. Foi o que aconteceu numa reunião de
   17 participantes: `tile_names.json` ficou todo `null` e a transcrição saiu
   pelo VTT.
3. **`transcribe.py` tem domínio e idioma fixos**: `language="pt"` (`:52`) e um `INITIAL_PROMPT`
   (`:29-35`) com o glossário de falências/recuperação judicial. Reunião em outro idioma sai como
   lixo; reunião de outro assunto tem o vocabulário enviesado. Não é parametrizável hoje.
4. **Diarização por áudio usa embeddings treinados em inglês** (`wespeaker_en_voxceleb_*`) —
   funcionam em pt-BR, com perda.
5. **Artefatos são grandes** (`audio.wav` 120–160 MB por reunião). `input/`, `output/`, `models/`,
   `.venv/` e `slack_users.json` (dado do workspace) estão no `.gitignore` — nunca versionar.
6. **A transcrição do círculo do Slack só existe se as Anotações da IA estiverem ligadas — e
   termina quando alguém as desliga no meio.** Medido num círculo real: o Slack transcreveu
   até 00:46:48 e a gravação seguiu até 00:57:45, porque um participante desligou as anotações no meio
   da call. O que vem depois **não fica sem falante, fica com o falante errado**:
   `build_blocks` herda o rótulo do vizinho e os 11 minutos finais viram um único turno gigante do
   último que falou. Confira sempre a janela que o `merge` imprime (`00:00:15..00:46:48 do vídeo`)
   contra a duração do vídeo, e corte o resto com `CUT_AFTER=` se não for aproveitável.
7. **O nome do arquivo de gravação de tela marca o FIM, não o início.** `Gravando 2026-01-01
   175704.mp4` acabou 17:57; a conversa começou 16:59. Por isso `titulo_e_data()` prefere o epoch
   resolvido pelo alinhamento (`SLACK_EPOCH0`) ao horário do nome.
8. **O nome do `.vtt` que o Teams exporta não casa com o do `.mp4`** — ele corta o sufixo de
   timestamp e troca caracteres inválidos. Ex.: `...Etapa A  Etapa B-2026...mp4`
   (espaço duplo, onde havia `/`) contra `...Etapa A _ Etapa B.vtt` (underscore).
   `merge._locate_vtt()` cobre isso casando os 20 primeiros caracteres do nome — o que pode emparelhar
   errado se `input/` tiver vários vídeos cujos títulos comecem igual. Nesse caso, passe `VTT=caminho`.

## Convenções ao editar

- **Comentários e docstrings em pt-BR sem acento; strings de saída para o usuário com acento.**
  (`# NAO assumimos grade fixa` vs. `"Não identificado"`.) Manter.
- Docstring de módulo explica **o porquê** da abordagem, não só o que o script faz — é onde mora o
  raciocínio de design (ex.: por que a grade de tiles é descoberta e não assumida).
- Chaves de JSON intermediário em inglês (`start`, `end`, `speaker`, `words`); no `turnos.json` de
  saída, `falante`. Variáveis locais em português.
- Constantes de tuning ficam no topo do módulo com um comentário justificando o valor.
