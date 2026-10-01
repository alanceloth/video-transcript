# video-transcript

Transcreve gravação de reunião **localmente** (nada vai para API) e identifica quem falou pelo
**nome real**. Funciona com gravação do **Teams** e com gravação de tela de **círculo (huddle) do
Slack**.

```
input/<vídeo>.mp4  ──make run──>  output/<nome do vídeo>/transcricao.md
```

## Pré-requisitos

| O quê | Como instalar |
|---|---|
| Windows com GPU NVIDIA (~5 GB de VRAM) | — a transcrição roda em CUDA, sem fallback para CPU |
| Python 3.12 | `winget install --id Python.Python.3.12 -e` |
| Git for Windows (traz o `sh` que o `make` usa) | `winget install --id Git.Git -e` |
| GNU make | `winget install --id ezwinports.make -e` |
| ffmpeg + ffprobe | `winget install --id Gyan.FFmpeg -e` |

## Primeira vez

```bash
make setup     # cria .venv, instala as dependências e cria input/ e output/
make models    # baixa os modelos de diarização (~145 MB) para models/
```

`make models` roda `scripts/download_models.py`, que baixa da release oficial do sherpa-onnx e pula
o que já existe. Os modelos só são usados quando não há fonte de nome (ver abaixo), mas vale baixar
logo. O modelo de transcrição (whisper large-v3, ~3 GB) **não** precisa de passo manual: é baixado
sozinho na primeira transcrição e fica no cache do Hugging Face.

## Uso

1. Coloque o vídeo em `input/`.
2. Rode, **com o nome entre aspas** (gravação do Teams tem espaço no nome):

   ```bash
   make run VIDEO="Reunião de Exemplo-20260101_100000-Gravação de Reunião.mp4"
   ```

   Se houver um único vídeo em `input/`, `VIDEO=` é opcional: `make run`.
3. O resultado sai em `output/<nome do vídeo>/`:

   | Arquivo | Conteúdo |
   |---|---|
   | `transcricao.md` | transcrição com falante e horário, pronta para ler |
   | `transcricao.txt` | a mesma coisa em texto puro |
   | `transcricao.srt` | legenda para abrir junto com o vídeo |
   | `turnos.json` | turnos estruturados (falante, início, fim, texto) |

   Os demais arquivos da pasta (`audio.wav`, `asr.json`...) são intermediários: guardá-los permite
   refazer só uma etapa sem retranscrever. Rodar de novo pula o que já está pronto; `FORCE=1` refaz.

`make where VIDEO="..."` mostra qual vídeo, qual pasta de saída e qual fonte de nomes seria usada,
sem processar nada.

## De onde vem o nome de quem falou

Por padrão (`SPEAKER=auto`) o pipeline procura, nesta ordem:

1. **`.vtt` do Teams** — exporte a transcrição da reunião no Teams e salve em `input/` ao lado do
   vídeo. Nomes reais, automático.
2. **Transcrição do círculo do Slack** — com as *Anotações da IA* ligadas no círculo, baixe o anexo
   `transcricao_do_circulo` da thread e salve em `input/` como `<nome do vídeo>.slack.json`. Os user
   ids viram nomes por `slack_users.json` na raiz do projeto (copie de `slack_users.example.json`).
3. **Diarização por áudio** — sem nenhum dos dois, separa as vozes e rotula `Falante 1..N`.

Para forçar uma fonte: `SPEAKER=vtt | slack | audio | badge`. `badge` lê o badge roxo do falante no
vídeo do Teams (1920×1080) e para numa revisão manual dos nomes.

## Ajustes comuns

```bash
# cortar o papo fora de pauta no fim (ou no começo) e dar título ao markdown
make merge-vtt VIDEO="..." CUT_AFTER=40:21 TITULO="Reunião de exemplo"

# apagar a saída de um vídeo e rodar tudo de novo
make new VIDEO="..."
```

`make help` lista todas as etapas e variáveis. Detalhes de arquitetura, limitações conhecidas e
como validar uma mudança estão em [`CLAUDE.md`](CLAUDE.md).

## O que não vai para o git

`input/`, `output/`, `models/`, `.venv/` e `slack_users.json` estão no `.gitignore`: vídeos e
transcrições são dados de reunião, e modelos/ambiente são recriados com `make setup` + `make models`.
