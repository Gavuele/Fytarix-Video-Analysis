# AI Waifu Research Pipeline

Автоматическое извлечение **метаданных, описаний, ссылок, YouTube-субтитров и речи (если субтитров нет)** из плейлиста [AI waifu creation — Just Rayen](https://www.youtube.com/playlist?list=PLP12rhP6IDovry9o35uMJkYNCbXBel2mj). Отдельная необязательная команда скачивает полные видео для анализа кода, показанного на экране.

**Важно.** Скрипт передан как локальный инструмент, а не как уже проведённый анализ плейлиста. На стороне автора проекта внешний YouTube не опрашивался, поэтому количество доступных роликов, успешность загрузок и содержание видео пока не проверены. Учитывайте [правила YouTube](https://www.youtube.com/t/terms), авторские права и разрешения при скачивании/копировании материалов. Не публикуйте скачанные видео или чужие расшифровки без соответствующих прав.

## Быстрый старт — Windows PowerShell

1. Установить **Python 3.11 или 3.12**, **Deno** и **FFmpeg**. Два последних — через PowerShell:

```powershell
winget install -e --id DenoLand.Deno
winget install -e --id Gyan.FFmpeg
```

Перезапустить PowerShell после установки, чтобы обновился PATH.

2. Распаковать архив и перейти в папку с `pipeline.py`:

```powershell
cd C:\Path\To\ai-waifu-research-pipeline
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Если установлен Python 3.12, заменить `py -3.11` на `py -3.12`. Можно не активировать виртуальное окружение — это исключает ошибки с PowerShell ExecutionPolicy.

3. **Первые три видео — пробный прогон**:

```powershell
.\.venv\Scripts\python.exe pipeline.py scan
.\.venv\Scripts\python.exe pipeline.py collect --limit 3
.\.venv\Scripts\python.exe pipeline.py status --limit 3
.\.venv\Scripts\python.exe pipeline.py transcribe --limit 3 --model small --device cpu
.\.venv\Scripts\python.exe pipeline.py build --limit 3
```

Сначала скрипт использует найденные субтитры; Whisper обрабатывает только видео **без VTT-субтитров**. При распознавании модель загружается при первом запуске, в дальнейшем — из локального кэша. Аудиофайл после успешного распознавания удаляется, если не добавлен `--keep-audio`.

4. **Все доступные видео** (повторный запуск пропускает обработанные файлы):

```powershell
.\.venv\Scripts\python.exe pipeline.py collect
.\.venv\Scripts\python.exe pipeline.py transcribe --model small --device cpu
.\.venv\Scripts\python.exe pipeline.py build
.\.venv\Scripts\python.exe pipeline.py status
```

### GPU (Windows, NVIDIA)

Для совместимой CUDA 12 + cuDNN 9 используйте:

```powershell
.\.venv\Scripts\python.exe pipeline.py transcribe --model medium --device cuda --compute-type int8_float16
```

**Внимание:** наличие видеокарты и драйвера само по себе недостаточно: `faster-whisper` / CTranslate2 требуется доступ к нужным cuBLAS и cuDNN DLL. При ошибках с DLL вернитесь к `--device cpu --compute-type int8` и настройте CUDA отдельно по [инструкции быстрее-Whisper](https://github.com/SYSTRAN/faster-whisper#requirements). Не нужно скачивать видео целиком для ASR.

### Дополнительно: скачать ВСЕ полноценные видео

Только при наличии соответствующего разрешения, свободного дискового пространства и с учётом условий YouTube:

```powershell
.\.venv\Scripts\python.exe pipeline.py videos --limit 3 --height 720
.\.venv\Scripts\python.exe pipeline.py videos --height 720
```

Полные ролики окажутся в `data/videos/`. Для совмещения видео и аудио требуются FFmpeg/FFprobe. Количество гигабайт зависит от длительности, качества и форматов — проверьте свободное место до запуска.

### Дополнительно: комментарии

Комментарии могут содержать ссылки на GitHub, исправления и обновления автора. Сбор может быть очень долгим и выдавать неполный результат:

```powershell
.\.venv\Scripts\python.exe pipeline.py collect --limit 3 --comments --force
```

Поскольку `--force` пересоздаёт метаданные, используйте только для нужной части плейлиста. Собирайте только то, на что у вас есть право, и не публикуйте пользовательские данные.

## Как выглядит результат

```
ai-waifu-research-pipeline/
  pipeline.py
  README.md
  requirements.txt
  prompts/
    01_video_analysis.md
    02_stage_synthesis.md
    03_vtuber_comparison.md
  data/
    manifest.json              # номера, названия и URL плейлиста
    raw/
      001_VIDEOID/
        VIDEOID.info.json      # полная metadata + chapters + description
        VIDEOID.description
        VIDEOID.en.vtt         # при наличии
        VIDEOID.webm           # лишь если понадобился Whisper
    asr/                       # результаты ASR с таймкодами
    videos/                    # необязательные полные видео
    notes/                     # одна Markdown-заметка на видео
    TIMELINE.md                # хронологический индекс ссылок
    knowledge.jsonl            # структурированный корпус для AI-поиска
    index.csv                  # краткий Excel-совместимый индекс
```

`data/notes/` можно подключить к Obsidian как часть хранилища (папку с Markdown). Для переноса в другой проект удобнее копировать `data/notes/` + `data/TIMELINE.md`.

## Анализ ИИ в три прохода

1. По одной серии: откройте `prompts/01_video_analysis.md`, анализируйте Markdown-выписки из `data/notes/`, сохраняя ссылки с таймкодами. Для технических деталей, которые показаны *только* на экране, сверяйтесь с оригинальным видео и ссылками на GitHub из описания.
2. Пакетами по 5–10 серий: используйте `prompts/02_stage_synthesis.md`, чтобы восстановить этапы разработки, изменения архитектуры и причины переработок.
3. После полного цикла: используйте `prompts/03_vtuber_comparison.md`, чтобы сопоставить найденные решения с собственным стеком Tauri + React + TypeScript + Live2D/VTube Studio + STT/TTS + LLM.

**Не загружайте все 103 длинных транскрипта в один запрос.** Контекст модели ограничен, и детали потеряются. Сначала серия → затем блок серий → затем общая архитектура и практический roadmap. Для поисковой работы можно индексировать `knowledge.jsonl` в SQLite FTS5 / RAG, но это отдельный следующий этап.

## Важные ограничения

- Не каждый ролик может быть доступен; приватные, удалённые, ограниченные или недоступные материалы не восстанавливаются. Итого может быть меньше 103.
- `collect` повторно обрабатывает видео, если `*.info.json` не появился, и пропускает его иначе. Для попытки повторного получения недостающих субтитров используйте `--force`.
- Машинные субтитры иногда ошибаются в названиях моделей, команд, имён переменных и версий. **Проверяйте по экрану и GitHub**, особенно код и инструкции установки.
- Полные видео и кадры отдельно нужны для того, что речь не описывает: UI, графы нод, изображения кода, анимация, графика.
- Некоторые запросы YouTube могут вернуть rate limit, 403, требование входа или CAPTCHA. Уменьшайте интенсивность и повторяйте позже, если это допустимо; не пытайтесь обходить ограничения доступа.
- `yt-dlp` для YouTube требует актуальный JS-рантайм Deno и комплект EJS, поэтому ставится пакет `yt-dlp[default]`.
- Созданные AI-конспекты следует проверять на соответствие первоисточникам; временные отметки позволяют это делать быстро.

## Справка по командам

```powershell
.\.venv\Scripts\python.exe pipeline.py --help
.\.venv\Scripts\python.exe pipeline.py collect --help
.\.venv\Scripts\python.exe pipeline.py transcribe --help
```

## Источники документации

- https://github.com/yt-dlp/yt-dlp/wiki/Installation
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
- https://github.com/yt-dlp/yt-dlp/blob/master/README.md
- https://github.com/SYSTRAN/faster-whisper
- https://docs.deno.com/runtime/getting_started/installation/
