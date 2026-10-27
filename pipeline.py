#!/usr/bin/env python3
"""YouTube playlist -> metadata/captions -> optional local ASR -> Markdown/JSONL.

Run ``python pipeline.py --help``.  Requires ``yt-dlp[default]`` for network
commands, and ``faster-whisper`` only for transcribe without usable subtitles.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from html import unescape
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
ASR = DATA / "asr"
NOTES = DATA / "notes"
MANIFEST = DATA / "manifest.json"
DEFAULT_URL = "https://www.youtube.com/playlist?list=PLP12rhP6IDovry9o35uMJkYNCbXBeI2mj"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
TIME_RE = re.compile(r"(?P<start>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})")
TAG_RE = re.compile(r"<[^>]*>")
MEDIA_SUFFIXES = {".webm", ".m4a", ".mp3", ".opus", ".ogg", ".mp4", ".mkv", ".aac", ".wav", ".flac"}


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def stamp(seconds: float | int | None) -> str:
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def sec(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    n = 0.0
    for p in parts:
        n = n * 60 + float(p)
    return n


def safe_name(name: str, max_len: int = 85) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "untitled")[:max_len].rstrip(" .")


def folder(item: dict) -> Path:
    return RAW / f"{item['index']:03d}_{item['id']}"


def get_items(start: int = 1, limit: int = 0) -> list[dict]:
    if not MANIFEST.exists():
        raise SystemExit("Нет data/manifest.json. Сначала: python pipeline.py scan")
    obj = load_json(MANIFEST)
    valid = [v for v in obj["items"] if v.get("id") and v["index"] >= start]
    return valid[:limit] if limit else valid


def yt_lib():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as err:
        raise SystemExit("Установи: python -m pip install -r requirements.txt") from err
    return YoutubeDL


def opts(**kwargs) -> dict:
    return {"quiet": True, "no_warnings": False, "ignoreerrors": False,
            "retries": 5, "fragment_retries": 5, "noplaylist": True,
            "sleep_interval_requests": 1, **kwargs}


def scan(args: argparse.Namespace) -> None:
    YoutubeDL = yt_lib()
    print("Считываю состав плейлиста:", args.url, flush=True)
    with YoutubeDL(opts(extract_flat="in_playlist", noplaylist=False, skip_download=True)) as ydl:
        result = ydl.extract_info(args.url, download=False)
    if not result or not result.get("entries"):
        raise SystemExit("Плейлист не прочитан. Проверь URL, интернет, обнови yt-dlp.")
    entries = list(result["entries"])
    items = []
    for index, video in enumerate(entries, start=1):
        video = video or {}
        video_id = video.get("id")
        if not (isinstance(video_id, str) and VIDEO_ID_RE.fullmatch(video_id)):
            video_id = None
        items.append({"index": index, "id": video_id,
                      "title": video.get("title") or "Недоступное видео",
                      "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None})
    output = {"url": args.url, "title": result.get("title", ""),
              "scanned_utc": datetime.now(timezone.utc).isoformat(), "items": items}
    if MANIFEST.exists() and not args.force:
        raise SystemExit("Manifest уже существует. Для нового сканирования: scan --force")
    save_json(MANIFEST, output)
    good = sum(bool(v["id"]) for v in items)
    print(f"Всего позиций: {len(items)}; распознаны ID: {good}; неизвестны: {len(items)-good}")
    print("Создан:", MANIFEST)


def collect(args: argparse.Namespace) -> None:
    YoutubeDL = yt_lib()
    items = get_items(args.start, args.limit)
    for n, item in enumerate(items, 1):
        home = folder(item)
        home.mkdir(parents=True, exist_ok=True)
        found = list(home.glob("*.info.json"))
        if found and not args.force:
            print(f"[{n}/{len(items)}] уже есть: {item['index']:03d} {item['title']}")
            continue
        print(f"[{n}/{len(items)}] метаданные и субтитры: {item['title']}", flush=True)
        options = opts(skip_download=True, writeinfojson=True, writedescription=True,
                       writesubtitles=True, writeautomaticsub=True,
                       subtitleslangs=["en.*", "ru.*"], subtitlesformat="vtt",
                       outtmpl=str(home / "%(id)s.%(ext)s"),
                       overwrites=bool(args.force), getcomments=bool(args.comments))
        try:
            with YoutubeDL(options) as ydl:
                ydl.extract_info(item["url"], download=True)
        except Exception as exc:
            print(f"  ОШИБКА {item['id']}: {str(exc)[:250]}", file=sys.stderr)
            (home / "error.txt").write_text(str(exc), encoding="utf-8")
        time.sleep(max(0, args.pause))
    print("Готово. Проверь покрытие: python pipeline.py status")


def subtitle_file(home: Path) -> Path | None:
    candidates = list(home.glob("*.vtt"))
    if not candidates:
        return None
    def score(p: Path) -> tuple[int, int]:
        stem = p.name.lower()
        # Original English generally preferable to auto translation / Russian.
        if re.search(r"\.en(-orig)?\.vtt$", stem):
            return (0, len(stem))
        if re.search(r"\.en[-_.]", stem):
            return (1, len(stem))
        if re.search(r"\.ru(-orig)?\.vtt$", stem):
            return (2, len(stem))
        return (3, len(stem))
    return sorted(candidates, key=score)[0]


def parse_vtt(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    blocks = re.split(r"\n\s*\n", content)
    rows = []
    for block in blocks:
        lines = block.splitlines()
        match_index = next((i for i, s in enumerate(lines) if TIME_RE.search(s)), None)
        if match_index is None:
            continue
        match = TIME_RE.search(lines[match_index])
        content_lines = lines[match_index + 1:]
        # Remove YouTube VTT inline timestamps, markup and invisible spacers.
        text = unescape(" ".join(content_lines))
        text = TAG_RE.sub("", text).replace("\u200b", "")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        start, end = sec(match.group("start")), sec(match.group("end"))
        if rows and text == rows[-1]["text"]:
            rows[-1]["end"] = max(rows[-1]["end"], end)
        elif rows and text.startswith(rows[-1]["text"]) and len(text) > len(rows[-1]["text"]):
            # Captions use rolling lines; replace partial text by fuller text.
            rows[-1]["text"] = text
            rows[-1]["end"] = max(rows[-1]["end"], end)
        else:
            rows.append({"start": start, "end": end, "text": text})
    return rows


def audio_file(home: Path) -> Path | None:
    paths = [p for p in home.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES]
    return sorted(paths, key=lambda p: p.name)[0] if paths else None


def transcribe(args: argparse.Namespace) -> None:
    YoutubeDL = yt_lib()
    items = get_items(args.start, args.limit)
    model = None
    for n, item in enumerate(items, 1):
        home = folder(item)
        home.mkdir(parents=True, exist_ok=True)
        target = ASR / f"{item['index']:03d}_{item['id']}.json"
        if target.exists() and not args.force:
            print(f"[{n}/{len(items)}] распознано ранее: {item['title']}")
            continue
        if subtitle_file(home) and not args.force_asr:
            print(f"[{n}/{len(items)}] есть субтитры, Whisper не требуется: {item['title']}")
            continue
        audio = audio_file(home)
        if not audio:
            print(f"[{n}/{len(items)}] загружаю только аудио: {item['title']}", flush=True)
            options = opts(format="bestaudio/best", outtmpl=str(home / "%(id)s.%(ext)s"),
                           continuedl=True, overwrites=False)
            try:
                with YoutubeDL(options) as ydl:
                    ydl.download([item["url"]])
            except Exception as exc:
                print(f"  Не удалось получить аудио: {str(exc)[:250]}", file=sys.stderr)
                continue
            audio = audio_file(home)
        if not audio:
            print(f"  Не найден аудиофайл: {item['id']}", file=sys.stderr)
            continue
        if model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SystemExit("Установи faster-whisper: python -m pip install -r requirements.txt") from exc
            print(f"Загружаю Whisper {args.model} ({args.device}/{args.compute_type})", flush=True)
            model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
        print(f"[{n}/{len(items)}] STT: {item['title']}", flush=True)
        try:
            segments, detected = model.transcribe(str(audio), beam_size=5, vad_filter=True,
                                                  language=args.language or None)
            rows = [{"start": round(s.start, 3), "end": round(s.end, 3),
                     "text": s.text.strip()} for s in segments if s.text.strip()]
            save_json(target, {"video_id": item["id"], "model": args.model,
                               "language": detected.language, "source": "faster-whisper",
                               "segments": rows})
            print(f"  сегментов: {len(rows)}; язык: {detected.language}")
            if not args.keep_audio:
                audio.unlink(missing_ok=True)
        except Exception as exc:
            print(f"  STT ошибка: {exc}", file=sys.stderr)
    print("Готово. Теперь: python pipeline.py build")


def get_data(item: dict, prefer_asr: bool = False) -> tuple[dict, list[dict], str]:
    home = folder(item)
    infofiles = list(home.glob("*.info.json")) if home.exists() else []
    meta = load_json(infofiles[0]) if infofiles else {}
    asr = ASR / f"{item['index']:03d}_{item['id']}.json"
    sub = subtitle_file(home) if home.exists() else None
    if asr.exists() and (prefer_asr or sub is None):
        obj = load_json(asr)
        return meta, obj.get("segments", []), f"ASR: {obj.get('model', '')} ({obj.get('language', '')})"
    if sub:
        return meta, parse_vtt(sub), f"Субтитры YouTube: {sub.name}"
    if asr.exists():
        obj = load_json(asr)
        return meta, obj.get("segments", []), "ASR: " + obj.get("model", "")
    return meta, [], "отсутствует"


def get_links(description: str) -> list[str]:
    urls = [u.rstrip(".,);!?\u3002") for u in URL_RE.findall(description)]
    return list(dict.fromkeys(urls))


def build(args: argparse.Namespace) -> None:
    NOTES.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    selected = get_items(args.start, args.limit)
    docs = []
    records = []
    for item in selected:
        meta, rows, source = get_data(item, args.prefer_asr)
        title = str(meta.get("title") or item["title"])
        url = str(meta.get("webpage_url") or item["url"])
        description = str(meta.get("description") or "")
        links = get_links(description)
        chapters = meta.get("chapters") or []
        prefix = f"{item['index']:03d}"
        filename = f"{prefix}_{safe_name(title)}.md"
        header = [f"# {prefix}. {title}", "",
                  f"- **Видео:** {url}",
                  f"- **Канал:** {meta.get('uploader') or 'неизвестно'}",
                  f"- **Дата публикации:** {meta.get('upload_date') or 'неизвестно'}",
                  f"- **Длительность:** {stamp(meta.get('duration'))}",
                  f"- **Источник текста:** {source}", "",
                  "## Описание автора", "", description or "*Описание недоступно.*", "",
                  "## Ссылки и ресурсы", ""]
        header.extend(f"- {link}" for link in links)
        if not links:
            header.append("*Ссылки не обнаружены.*")
        header.extend(["", "## Главы видео", ""])
        for ch in chapters:
            start = int(ch.get("start_time") or 0)
            header.append(f"- [{stamp(start)}]({url}&t={start}s) — {ch.get('title', '')}")
        if not chapters:
            header.append("*Главы недоступны.*")
        header.extend(["", "## Транскрипт с таймкодами", ""])
        if rows:
            for row in rows:
                start = int(row["start"])
                header.append(f"[{stamp(start)}]({url}&t={start}s) {row['text']}")
                header.append("")
        else:
            header.append("*Текста нет: проверь субтитры или запусти transcribe.*")
        header.extend(["", "## Заметки исследователя (пока не заполнены)", "",
                       "- **Что реализовано в этой серии:**", "- **Технологии и версии:**",
                       "- **Исходный код / репозиторий / файлы:**",
                       "- **Проблемы и решения:**", "- **Что можно перенести в AI VTuber:**",
                       "- **Неопределённости / что проверить по видео:**", ""])
        (NOTES / filename).write_text("\n".join(header), encoding="utf-8")
        rec = {"index": item["index"], "id": item["id"], "title": title,
               "url": url, "upload_date": meta.get("upload_date"),
               "duration": meta.get("duration"), "description": description,
               "links": links, "chapters": chapters, "source": source,
               "transcript": rows, "note": str((Path("data") / "notes" / filename).as_posix())}
        records.append(rec)
        docs.append({"index": item["index"], "id": item["id"], "title": title,
                     "url": url, "source": source, "segments": len(rows),
                     "description_links": len(links), "note": filename})
    with (DATA / "knowledge.jsonl").open("w", encoding="utf-8") as f:
        for obj in records:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    with (DATA / "index.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "id", "title", "url", "source", "segments", "description_links", "note"])
        writer.writeheader()
        writer.writerows(docs)
    timeline = ["# AI waifu creation — индекс роликов", "",
                "*Это автоматически собранный указатель, а не проверенный анализ реализации.*", ""]
    for d in docs:
        timeline.append(f"- **{d['index']:03d}** [{d['title']}]({d['url']}) — "
                        f"[заметка](notes/{d['note'].replace(' ', '%20')}) — {d['source']}")
    (DATA / "TIMELINE.md").write_text("\n".join(timeline) + "\n", encoding="utf-8")
    count = sum(d["segments"] > 0 for d in docs)
    print(f"Сформировано заметок: {len(docs)}; с текстом: {count}")
    print("Файлы: data/notes/, data/knowledge.jsonl, data/index.csv, data/TIMELINE.md")


def videos(args: argparse.Namespace) -> None:
    """Optionally download full videos for visual/code analysis (requires permission)."""
    YoutubeDL = yt_lib()
    output_dir = DATA / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    items = get_items(args.start, args.limit)
    for n, item in enumerate(items, 1):
        base = f"{item['index']:03d}_{item['id']}"
        if any(output_dir.glob(base + ".*")) and not args.force:
            print(f"[{n}/{len(items)}] ранее загружено: {item['title']}")
            continue
        print(f"[{n}/{len(items)}] видео: {item['title']}", flush=True)
        options = opts(format=f"bv*[height<={args.height}]+ba/b[height<={args.height}]/best",
                       merge_output_format="mp4", continuedl=True,
                       outtmpl=str(output_dir / (base + ".%(ext)s")),
                       overwrites=bool(args.force))
        try:
            with YoutubeDL(options) as ydl:
                ydl.download([item["url"]])
        except Exception as exc:
            print(f"  Ошибка загрузки: {str(exc)[:250]}", file=sys.stderr)
        time.sleep(1)
    print("Загруженные видео: data/videos/")


def status(args: argparse.Namespace) -> None:
    items = get_items(args.start, args.limit)
    meta = cap = asr = audio = 0
    missing = []
    for item in items:
        home = folder(item)
        hasmeta = home.exists() and bool(list(home.glob("*.info.json")))
        hassub = home.exists() and bool(subtitle_file(home))
        hasasr = (ASR / f"{item['index']:03d}_{item['id']}.json").exists()
        hasaudio = home.exists() and audio_file(home) is not None
        meta += bool(hasmeta)
        cap += bool(hassub)
        asr += bool(hasasr)
        audio += bool(hasaudio)
        if not (hassub or hasasr):
            missing.append(item)
    print(f"Роликов в выборке: {len(items)}\nМетаданные: {meta}\nYouTube-субтитры: {cap}"
          f"\nWhisper: {asr}\nАудио на диске: {audio}\nБез транскрипта: {len(missing)}")
    for item in missing[:20]:
        print(f"  - {item['index']:03d} {item['title']} — {item['url']}")
    if len(missing) > 20:
        print(f"  ... и ещё {len(missing)-20}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    ps = sub.add_parser("scan", help="прочитать список видео и порядок")
    ps.add_argument("--url", default=DEFAULT_URL)
    ps.add_argument("--force", action="store_true", help="перезаписать manifest")
    ps.set_defaults(func=scan)
    for name, func in [("collect", collect), ("transcribe", transcribe), ("videos", videos), ("build", build), ("status", status)]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--start", type=int, default=1, help="позиция видео в плейлисте")
        cmd.add_argument("--limit", type=int, default=0, help="максимум роликов, 0=все")
        cmd.set_defaults(func=func)
        if name == "collect":
            cmd.add_argument("--pause", type=float, default=1.0)
            cmd.add_argument("--comments", action="store_true", help="добавить комментарии в info.json; долго и много данных")
            cmd.add_argument("--force", action="store_true", help="повторить извлечение, даже если metadata есть")
        elif name == "transcribe":
            cmd.add_argument("--model", default="small", help="small, medium, large-v3, ...")
            cmd.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
            cmd.add_argument("--compute-type", default="int8", help="для GPU: int8_float16")
            cmd.add_argument("--language", default="", help="например en; пусто = автоопределение")
            cmd.add_argument("--force", action="store_true", help="перезаписать прежний результат ASR")
            cmd.add_argument("--force-asr", action="store_true", help="распознавать даже если есть субтитры")
            cmd.add_argument("--keep-audio", action="store_true", help="не удалять аудиофайл после STT")
        elif name == "videos":
            cmd.add_argument("--height", type=int, default=720, help="максимальная высота кадра, по умолчанию 720")
            cmd.add_argument("--force", action="store_true")
        elif name == "build":
            cmd.add_argument("--prefer-asr", action="store_true", help="предпочесть Whisper при наличии обоих вариантов")
    args = parser.parse_args()
    if hasattr(args, "start") and args.start < 1:
        parser.error("--start должен быть >= 1")
    if hasattr(args, "limit") and args.limit < 0:
        parser.error("--limit должен быть >= 0")
    args.func(args)


if __name__ == "__main__":
    main()
