#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ViralCut — режет длинные видео на вирусные вертикальные шортсы (RU / EN).
Бесплатный локальный аналог Opus.pro / Vizard.ai.

Пайплайн:
  видео/YouTube-ссылка -> Whisper (слова с таймкодами) -> ИИ-анализ виральности
  (Claude CLI / Claude API / эвристика) -> ffmpeg: 9:16 + сочные караоке-субтитры.

Пример:
  python viralcut.py "video.mp4"
  python viralcut.py "https://youtube.com/watch?v=..." --clips 5
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "1.0.0"

# ----------------------------------------------------------------------------
# Консоль: всегда UTF-8 (Windows-дружелюбно)
# ----------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def say(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    say(f"❌ {msg}")
    sys.exit(code)


# ----------------------------------------------------------------------------
# Данные
# ----------------------------------------------------------------------------
@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Sentence:
    text: str
    start: float
    end: float
    words: list = field(default_factory=list)


@dataclass
class Clip:
    start: float
    end: float
    title: str = ""
    hook: str = ""
    hashtags: list = field(default_factory=list)
    score: int = 0
    why: str = ""

    @property
    def dur(self) -> float:
        return self.end - self.start


# ----------------------------------------------------------------------------
# Виральные лексиконы (эвристический режим)
# ----------------------------------------------------------------------------
RU_STEMS = [
    "секрет", "шок", "ошибк", "деньг", "доллар", "рубл", "миллион", "тысяч",
    "никогда", "правд", "ложь", "обман", "бесплатн", "лайфхак", "хитрост",
    "важн", "главн", "страшн", "ужас", "невероятн", "безум", "жест", "огон",
    "мощн", "провал", "успе", "побед", "проигр", "потеря", "зараб", "богат",
    "бедн", "опасн", "запомн", "представ", "внимани", "почему", "зачем",
    "истори", "случи", "оказа", "честно", "признаюсь", "факт", "доказа",
    "эксперимент", "вдруг", "внезапн", "стыдн", "боюсь", "страх", "ненавиж",
    "люблю", "лучш", "худш", "стоп", "нельзя", "запрещ", "рискн", "сложн",
]
RU_PHRASES = [
    "на самом деле", "вот что", "самое главное", "никому не", "мало кто",
    "все думают", "я расскажу", "смотрите что", "вы не поверите",
    "главная ошибка", "хватит", "перестаньте",
]
EN_STEMS = [
    "secret", "shock", "mistake", "money", "dollar", "million", "thousand",
    "never", "truth", "lie", "scam", "free", "hack", "trick", "important",
    "crazy", "insane", "terribl", "horribl", "amazing", "incredibl", "fail",
    "success", "win", "lose", "lost", "earn", "rich", "poor", "danger",
    "remember", "imagine", "attention", "why", "story", "happened",
    "actually", "honestly", "confess", "fact", "proof", "experiment",
    "suddenly", "afraid", "fear", "hate", "love", "best", "worst", "warning",
    "stop", "nobody", "everyone", "viral", "expensive", "cheap",
]
EN_PHRASES = [
    "let me tell you", "here is the", "here's the", "the one thing",
    "most people", "no one talks", "nobody talks", "you won't believe",
    "the biggest mistake", "listen to me", "i'm going to show",
]


# ----------------------------------------------------------------------------
# Внешние утилиты
# ----------------------------------------------------------------------------
def run(cmd, **kw):
    """Запуск процесса с utf-8 текстом."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(cmd, **kw)


def ensure_tools() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        die("ffmpeg не найден. Установите: scoop install ffmpeg  (или winget install Gyan.FFmpeg)")


def probe(video: Path) -> dict:
    """Длительность и размеры видео."""
    p = run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json", str(video),
    ])
    if p.returncode != 0:
        die(f"Не удалось прочитать видео: {video}\n{p.stderr.strip()[:400]}")
    data = json.loads(p.stdout)
    streams = data.get("streams") or [{}]
    return {
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "width": int(streams[0].get("width", 0) or 0),
        "height": int(streams[0].get("height", 0) or 0),
    }


def download_video(url: str, workdir: Path) -> Path:
    say("📥 Скачиваю видео (yt-dlp)…")
    out_tpl = str(workdir / "source.%(ext)s")
    p = subprocess.run(
        [sys.executable, "-m", "yt_dlp",
         "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
         "--merge-output-format", "mp4",
         "--no-playlist",
         "-o", out_tpl, url],
        text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        die("Не удалось скачать видео. Проверьте ссылку (или установите yt-dlp: pip install yt-dlp).")
    files = sorted(workdir.glob("source.*"))
    if not files:
        die("yt-dlp не создал файл видео.")
    return files[0]


def extract_audio(video: Path, wav: Path) -> None:
    p = run(["ffmpeg", "-y", "-i", str(video), "-vn",
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    if p.returncode != 0:
        die(f"Не удалось извлечь звук (есть ли аудиодорожка?):\n{p.stderr.strip()[-400:]}")


# ----------------------------------------------------------------------------
# Транскрипция (faster-whisper)
# ----------------------------------------------------------------------------
def transcribe(wav: Path, model_size: str, lang: str, total_dur: float):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("faster-whisper не установлен. Выполните: pip install -r requirements.txt")

    say(f"🎙  Распознаю речь (Whisper {model_size}, устройство: CPU)…")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    language = None if lang == "auto" else lang
    segments, info = model.transcribe(
        str(wav), language=language, word_timestamps=True,
        vad_filter=True, beam_size=5,
    )

    words: list[Word] = []
    last_pct = -1
    for seg in segments:
        for w in seg.words or []:
            t = w.word.strip()
            if t:
                words.append(Word(t, float(w.start), float(w.end)))
        if total_dur > 0:
            pct = min(99, int(seg.end / total_dur * 100))
            if pct != last_pct:
                print(f"\r    прогресс: {pct}%", end="", flush=True)
                last_pct = pct
    print("\r    прогресс: 100%")

    detected = info.language or "en"
    prob = getattr(info, "language_probability", 0.0) or 0.0
    lang_names = {"ru": "русский", "en": "английский"}
    say(f"    → язык: {lang_names.get(detected, detected)} "
        f"({prob:.0%}), слов: {len(words)}")
    if detected not in ("ru", "en"):
        say("⚠️  ViralCut официально поддерживает только русский и английский. "
            "Продолжаю, но качество не гарантируется.")
    return words, detected


def build_sentences(words: list) -> list:
    """Слова -> предложения (по пунктуации и паузам)."""
    sentences: list[Sentence] = []
    cur: list[Word] = []

    def flush():
        if cur:
            text = " ".join(w.text for w in cur)
            sentences.append(Sentence(text, cur[0].start, cur[-1].end, list(cur)))
            cur.clear()

    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_punct = w.text[-1:] in ".!?…"
        long_pause = nxt is not None and (nxt.start - w.end) > 0.9
        too_long = len(cur) >= 30
        if end_punct or long_pause or too_long:
            flush()
    flush()
    return sentences


# ----------------------------------------------------------------------------
# Анализ виральности
# ----------------------------------------------------------------------------
def transcript_for_llm(sents: list, limit_chars: int = 120_000) -> str:
    lines = [f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in sents]
    text = "\n".join(lines)
    if len(text) > limit_chars:
        say("⚠️  Транскрипт очень длинный — анализирую первые ~2 часа речи.")
        text = text[:limit_chars]
    return text


def llm_prompt(transcript: str, n: int, min_d: int, max_d: int, lang: str) -> str:
    lang_name = "Russian" if lang == "ru" else "English"
    return f"""You are a world-class viral short-form video editor (TikTok / YouTube Shorts / Reels).
Below is a video transcript with timestamps in seconds: [start-end] text.

Task: pick the {n} BEST self-contained moments to publish as viral vertical shorts.

Rules:
- Each clip must be {min_d}-{max_d} seconds long.
- Prefer moments with a strong hook in the first 2 seconds: emotion, conflict,
  intrigue, money, mistakes, secrets, bold claims, numbers, story twists.
- A clip must start at a sentence beginning and make sense on its own.
- The video language is {lang_name}. Write title, hook and hashtags in {lang_name}.
- Do not invent timestamps: use only times that exist in the transcript.

Return ONLY a JSON array (no markdown, no commentary):
[{{"start": 12.4, "end": 41.0, "title": "catchy title up to 60 chars",
   "hook": "up to 6 words", "hashtags": ["#a", "#b", "#c"],
   "score": 87, "why": "one short sentence"}}]

TRANSCRIPT:
{transcript}
"""


def parse_llm_json(raw: str):
    """Достаёт первый JSON-массив из ответа модели."""
    if not raw:
        return None
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        i, j = raw.find("["), raw.rfind("]")
        if i == -1 or j <= i:
            return None
        raw = raw[i:j + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def analyze_claude_cli(prompt: str):
    exe = shutil.which("claude")
    if not exe:
        return None
    say("🧠 Анализ виральности: Claude CLI…")
    try:
        p = run([exe, "-p", "--output-format", "text"], input=prompt, timeout=600)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p.returncode != 0:
        return None
    return parse_llm_json(p.stdout)


def analyze_claude_api(prompt: str, api_model: str):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    say(f"🧠 Анализ виральности: Claude API ({api_model})…")
    import urllib.request
    body = json.dumps({
        "model": api_model,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        say(f"⚠️  Claude API недоступен: {e}")
        return None
    text = "".join(b.get("text", "") for b in data.get("content", []))
    return parse_llm_json(text)


def sentence_score(s: Sentence, lang: str) -> float:
    text = s.text.lower()
    tokens = re.findall(r"\w+", text)
    stems = RU_STEMS if lang == "ru" else EN_STEMS
    phrases = RU_PHRASES if lang == "ru" else EN_PHRASES
    score = 0.0
    for t in tokens:
        if any(t.startswith(st) for st in stems):
            score += 2.0
    for ph in phrases:
        if ph in text:
            score += 2.5
    if "?" in s.text:
        score += 2.0
    if "!" in s.text:
        score += 1.5
    if re.search(r"\d", s.text):
        score += 1.2
    if tokens and len(tokens) <= 8:
        score += 0.8
    return score


def analyze_heuristic(sents: list, lang: str, n: int, min_d: int, max_d: int) -> list:
    say("🧠 Анализ виральности: эвристика (без ИИ — установите Claude CLI "
        "или задайте ANTHROPIC_API_KEY для более умного отбора)…")
    scores = [sentence_score(s, lang) for s in sents]

    candidates = []
    for i in range(len(sents)):
        j = i
        while j < len(sents) and sents[j].end - sents[i].start < min_d:
            j += 1
        best = None
        while j < len(sents) and sents[j].end - sents[i].start <= max_d:
            dur = sents[j].end - sents[i].start
            total = sum(scores[i:j + 1])
            val = total / math.sqrt(max(dur, 1.0)) + 0.6 * scores[i]
            if best is None or val > best[0]:
                best = (val, i, j)
            j += 1
        if best:
            candidates.append(best)

    candidates.sort(reverse=True)
    chosen: list[Clip] = []
    max_val = candidates[0][0] if candidates else 1.0
    for val, i, j in candidates:
        if len(chosen) >= n:
            break
        st, en = sents[i].start, sents[j].end
        overlap = any(min(en, c.end) - max(st, c.start) > 0.15 * min(en - st, c.dur)
                      for c in chosen)
        if overlap:
            continue
        title = sents[i].text.strip()
        if len(title) > 57:
            title = title[:57].rstrip() + "…"
        tags = ["#shorts", "#рек", "#рекомендации"] if lang == "ru" \
            else ["#shorts", "#viral", "#fyp"]
        chosen.append(Clip(st, en, title=title, hook="",
                           hashtags=tags,
                           score=max(1, int(val / max_val * 100)) if max_val else 50,
                           why="эвристический отбор"))
    chosen.sort(key=lambda c: -c.score)
    return chosen


def pick_clips(sents, lang, args, video_dur) -> list:
    raw = None
    if args.ai in ("auto", "claude"):
        raw = analyze_claude_cli(
            llm_prompt(transcript_for_llm(sents), args.clips,
                       args.min_dur, args.max_dur, lang))
    if raw is None and args.ai in ("auto", "api"):
        raw = analyze_claude_api(
            llm_prompt(transcript_for_llm(sents), args.clips,
                       args.min_dur, args.max_dur, lang),
            args.api_model)

    clips: list[Clip] = []
    if raw:
        for item in raw:
            try:
                c = Clip(
                    start=float(item["start"]), end=float(item["end"]),
                    title=str(item.get("title", ""))[:80],
                    hook=str(item.get("hook", ""))[:60],
                    hashtags=[str(h) for h in item.get("hashtags", [])][:6],
                    score=int(item.get("score", 50)),
                    why=str(item.get("why", ""))[:200],
                )
            except (KeyError, TypeError, ValueError):
                continue
            if c.end > c.start:
                clips.append(c)
        if clips:
            say(f"    → ИИ предложил {len(clips)} фрагментов")

    if not clips:
        clips = analyze_heuristic(sents, lang, args.clips,
                                  args.min_dur, args.max_dur)
    if not clips:
        die("Не нашёл подходящих фрагментов. Попробуйте --min-dur поменьше.")

    # Привязка к границам предложений + рамки длительности
    normalized = []
    for c in clips:
        snap_clip(c, sents, args.min_dur, args.max_dur, video_dur)
        if c.dur >= max(4.0, args.min_dur * 0.5):
            normalized.append(c)

    # финальная дедупликация пересечений
    normalized.sort(key=lambda c: -c.score)
    final: list[Clip] = []
    for c in normalized:
        if len(final) >= args.clips:
            break
        if any(min(c.end, f.end) - max(c.start, f.start) > 0.2 * min(c.dur, f.dur)
               for f in final):
            continue
        final.append(c)
    return final


def snap_clip(c: Clip, sents: list, min_d: int, max_d: int, video_dur: float) -> None:
    """Прижимает клип к границам предложений и рамкам длительности."""
    starts = [s.start for s in sents]
    ends = [s.end for s in sents]

    def nearest(values, target, tol=5.0):
        best = min(values, key=lambda v: abs(v - target), default=None)
        return best if best is not None and abs(best - target) <= tol else target

    c.start = max(0.0, nearest(starts, c.start))
    c.end = min(video_dur, nearest(ends, c.end))

    if c.dur < min_d:  # расширяем до следующего конца предложения
        for e in ends:
            if e >= c.start + min_d:
                c.end = min(video_dur, e)
                break
        else:
            c.end = min(video_dur, c.start + min_d)
    if c.dur > max_d:  # обрезаем по последнему предложению в пределах max_d
        fit = [e for e in ends if c.start < e <= c.start + max_d]
        c.end = fit[-1] if fit else c.start + max_d

    c.start = max(0.0, c.start - 0.15)  # небольшой «вдох» перед фразой


# ----------------------------------------------------------------------------
# Субтитры (ASS, караоке-стиль как в Opus.pro)
# ----------------------------------------------------------------------------
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,50,50,600,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

HIGHLIGHT = r"{\c&H00FFFF&\fscx112\fscy112}"  # жёлтый + лёгкое увеличение
RESET = r"{\r}"


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def clean_caption_word(text: str) -> str:
    t = text.strip().strip(",.;:—-–")
    t = t.replace("{", "(").replace("}", ")")
    return t.upper()


def group_caption_words(words: list, max_words=3, max_chars=16, max_gap=0.6) -> list:
    groups, cur = [], []
    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            chars = sum(len(clean_caption_word(x.text)) for x in cur) \
                + len(cur) + len(clean_caption_word(w.text))
            if (len(cur) >= max_words or gap > max_gap or chars > max_chars
                    or cur[-1].text[-1:] in ".!?…"):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list, clip_start: float, font: str) -> str:
    """Караоке-субтитры: группа из 2-3 слов, активное слово подсвечено."""
    shifted = [Word(w.text, max(0.0, w.start - clip_start),
                    max(0.0, w.end - clip_start)) for w in words]
    lines = [ASS_HEADER.format(font=font)]
    for group in group_caption_words(shifted):
        display = [clean_caption_word(w.text) for w in group]
        if not any(display):
            continue
        group_end = max(group[-1].end, group[-1].start + 0.3) + 0.10
        for i, w in enumerate(group):
            t0 = w.start if i > 0 else group[0].start
            t1 = group[i + 1].start if i + 1 < len(group) else group_end
            if t1 <= t0:
                t1 = t0 + 0.05
            parts = []
            for k, d in enumerate(display):
                if not d:
                    continue
                parts.append(f"{HIGHLIGHT}{d}{RESET}" if k == i else d)
            text = " ".join(parts)
            lines.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},"
                         f"Cap,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Рендер клипов
# ----------------------------------------------------------------------------
def slugify(text: str, max_len: int = 40) -> str:
    t = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    t = re.sub(r"[\s-]+", "_", t)
    return t[:max_len].rstrip("_") or "clip"


def render_clip(video: Path, c: Clip, words: list, out_path: Path,
                style: str, captions: bool, font: str, workdir: Path) -> bool:
    clip_words = [w for w in words if w.start >= c.start - 0.2 and w.end <= c.end + 0.5]

    if style == "crop":
        base = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase," \
               "crop=1080:1920[base]"
    else:  # blur
        base = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=32:4[bg];"
                "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")

    ass_name = None
    if captions and clip_words:
        ass_name = f"cap_{out_path.stem}.ass"
        (workdir / ass_name).write_text(
            build_ass(clip_words, c.start, font), encoding="utf-8-sig")
        fc = f"{base};[base]ass={ass_name}[v]"
    else:
        fc = base.replace("[base]", "[v]", 1) if style == "crop" \
            else base.replace("overlay=(W-w)/2:(H-h)/2[base]",
                              "overlay=(W-w)/2:(H-h)/2[v]")

    cmd = ["ffmpeg", "-y",
           "-ss", f"{c.start:.3f}", "-t", f"{c.dur:.3f}",
           "-i", str(video.resolve()),
           "-filter_complex", fc,
           "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart",
           str(out_path.resolve())]
    p = run(cmd, cwd=str(workdir))
    if p.returncode != 0:
        say(f"⚠️  ffmpeg не смог срендерить клип {out_path.name}:\n"
            f"{p.stderr.strip()[-500:]}")
        return False
    return True


# ----------------------------------------------------------------------------
# Отчёт
# ----------------------------------------------------------------------------
def fmt_tc(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def write_report(outdir: Path, source: str, clips: list, files: list,
                 lang: str) -> Path:
    rep = outdir / "report.md"
    lines = [f"# 🎬 ViralCut — отчёт\n",
             f"Источник: `{source}`  \nЯзык: **{lang}**  \nКлипов: **{len(files)}**\n"]
    for c, f in zip(clips, files):
        lines.append(f"\n---\n\n## {f.name}\n")
        lines.append(f"- ⏱ {fmt_tc(c.start)} → {fmt_tc(c.end)} ({c.dur:.0f} сек)")
        lines.append(f"- 🔥 Виральность: **{c.score}/100**")
        if c.title:
            lines.append(f"- 📝 Заголовок: **{c.title}**")
        if c.hook:
            lines.append(f"- 🪝 Хук: {c.hook}")
        if c.hashtags:
            lines.append(f"- #️⃣ Хэштеги: {' '.join(c.hashtags)}")
        if c.why:
            lines.append(f"- 💡 Почему: {c.why}")
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return rep


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        prog="viralcut",
        description="ViralCut — режет длинные видео на вирусные шортсы (RU/EN).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("input", help="путь к видеофайлу или ссылка на YouTube")
    ap.add_argument("--clips", type=int, default=6, help="сколько шортсов сделать")
    ap.add_argument("--min-dur", type=int, default=15, help="мин. длина клипа, сек")
    ap.add_argument("--max-dur", type=int, default=60, help="макс. длина клипа, сек")
    ap.add_argument("--lang", choices=["auto", "ru", "en"], default="auto",
                    help="язык речи")
    ap.add_argument("--model", default="small",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    help="модель Whisper (small = баланс, medium точнее)")
    ap.add_argument("--style", choices=["blur", "crop"], default="blur",
                    help="9:16: blur = размытый фон, crop = центральный кроп")
    ap.add_argument("--ai", choices=["auto", "claude", "api", "off"],
                    default="auto",
                    help="анализ: claude = Claude CLI, api = Claude API, "
                         "off = эвристика")
    ap.add_argument("--api-model", default="claude-sonnet-5",
                    help="модель для Claude API")
    ap.add_argument("--no-captions", action="store_true",
                    help="без встроенных субтитров")
    ap.add_argument("--font", default="Arial Black", help="шрифт субтитров")
    ap.add_argument("--out", default=None, help="папка результатов")
    ap.add_argument("--keep-temp", action="store_true",
                    help="не удалять временные файлы")
    ap.add_argument("--version", action="version", version=f"ViralCut {VERSION}")
    args = ap.parse_args()

    if args.min_dur < 3 or args.max_dur <= args.min_dur:
        die("Неверные длительности: нужно 3 <= min-dur < max-dur.")

    say(f"🎬 ViralCut v{VERSION} — вирусные шортсы из длинных видео (RU/EN)")
    ensure_tools()

    is_url = re.match(r"^https?://", args.input, re.IGNORECASE) is not None
    if is_url:
        src_name = "video"
    else:
        src = Path(args.input)
        if not src.exists():
            die(f"Файл не найден: {src}")
        src_name = src.stem

    outdir = Path(args.out) if args.out else Path.cwd() / f"shorts_{slugify(src_name)}"
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="viralcut_"))

    try:
        video = download_video(args.input, workdir) if is_url else Path(args.input)
        if is_url:
            src_name = "video"
        meta = probe(video)
        if meta["duration"] < args.min_dur + 5:
            die("Видео слишком короткое — тут нечего резать 🙂")
        say(f"🎞  Видео: {fmt_tc(meta['duration'])}, "
            f"{meta['width']}x{meta['height']}")

        wav = workdir / "audio.wav"
        extract_audio(video, wav)

        words, lang = transcribe(wav, args.model, args.lang, meta["duration"])
        if len(words) < 20:
            die("Речь почти не распознана — в видео мало слов? "
                "Попробуйте --model medium.")
        if args.lang != "auto":
            lang = args.lang
        if lang not in ("ru", "en"):
            lang = "en"

        sents = build_sentences(words)
        clips = pick_clips(sents, lang, args, meta["duration"])

        say(f"✂️  Режу {len(clips)} клипов (стиль: {args.style}, "
            f"субтитры: {'выкл' if args.no_captions else 'вкл'})…")
        files = []
        ok_clips = []
        for idx, c in enumerate(clips, 1):
            name = f"{idx:02d}_score{c.score:02d}_{slugify(c.title)}.mp4"
            out_path = outdir / name
            if render_clip(video, c, words, out_path, args.style,
                           not args.no_captions, args.font, workdir):
                files.append(out_path)
                ok_clips.append(c)
                say(f"    [{idx}/{len(clips)}] {name} ({c.dur:.0f}с) ✔")

        if not files:
            die("Ни один клип не срендерился.")

        rep = write_report(outdir, args.input, ok_clips, files, lang)
        say(f"📄 Отчёт: {rep}")
        say(f"✅ Готово! {len(files)} шортсов в папке: {outdir}")
    finally:
        if not args.keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\n⏹  Остановлено пользователем.")
        sys.exit(130)
