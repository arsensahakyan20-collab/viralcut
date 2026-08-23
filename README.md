# 🎬 ViralCut

**Бесплатный локальный аналог [Opus.pro](https://www.opus.pro/) и [Vizard.ai](https://vizard.ai/): режет длинные видео на вирусные вертикальные шортсы. Русский и английский.**

*Free, local, open-source alternative to Opus.pro / Vizard.ai: turns long videos into viral vertical shorts. Russian & English. [English docs below ⬇](#-english)*

---

## Что делает

Даёшь длинное видео (файл или ссылку на YouTube) — получаешь готовые шортсы:

1. 🎙 **Распознаёт речь** с таймкодами каждого слова (Whisper, работает локально, RU/EN)
2. 🧠 **Находит самые виральные моменты** — эмоции, деньги, ошибки, секреты, сильные заявления, повороты истории. Анализ делает Claude (через Claude Code CLI или API-ключ), а без ИИ — встроенная эвристика
3. ✂️ **Режет в вертикальный формат 9:16** (1080×1920) — размытый фон или центральный кроп
4. 💬 **Вжигает сочные караоке-субтитры** — крупные, по 2–3 слова, активное слово подсвечивается жёлтым (как в Opus.pro)
5. 📄 **Пишет отчёт** — заголовок, хук, хэштеги и оценка виральности для каждого клипа

Всё работает **на твоём компьютере, бесплатно, без подписок и лимитов минут**.

## Установка (Windows)

```bat
:: 1. Python 3.10+ и ffmpeg (если ещё нет)
scoop install python ffmpeg
:: или: winget install Python.Python.3.12 Gyan.FFmpeg

:: 2. Зависимости
pip install -r requirements.txt
```

Или просто запусти **`install.bat`**.

## Использование

```bat
:: Из локального файла
python viralcut.py "C:\видео\подкаст.mp4"

:: Прямо с YouTube
python viralcut.py "https://www.youtube.com/watch?v=XXXX"

:: Настройки
python viralcut.py "видео.mp4" --clips 8 --min-dur 20 --max-dur 45 --style crop
```

Результат — папка `shorts_<имя>` с клипами `01_score92_Заголовок.mp4` и `report.md`.

### Режимы ИИ-анализа

| Режим | Что нужно | Качество отбора |
|---|---|---|
| `--ai claude` | установленный [Claude Code](https://claude.com/claude-code) (CLI) | ⭐⭐⭐ лучший |
| `--ai api` | переменная `ANTHROPIC_API_KEY` | ⭐⭐⭐ лучший |
| `--ai off` | ничего | ⭐⭐ эвристика по виральным словам, вопросам, цифрам |

По умолчанию `--ai auto`: пробует Claude CLI → API → эвристику.

### Все параметры

```
--clips N        сколько шортсов (по умолч. 6)
--min-dur N      мин. длина клипа в сек (15)
--max-dur N      макс. длина клипа в сек (60)
--lang auto|ru|en
--model tiny|base|small|medium|large-v3   (точность/скорость Whisper)
--style blur|crop     9:16: размытый фон или кроп
--no-captions         без субтитров
--brand "ТЕКСТ"       яркая надпись внизу каждого клипа (сайт/бренд)
--brand-color auto|yellow|pink|cyan|lime|orange|crimson
                      цвет надписи (auto = каждому клипу свой цвет)
--font "Arial Black"  шрифт субтитров
--out ПАПКА           куда сложить результат
```

Пример с брендированием:

```bat
python viralcut.py "видео.mp4" --brand "mysite.com - мой продукт"
```

## Честное сравнение с Opus.pro / Vizard.ai

| | ViralCut | Opus.pro / Vizard |
|---|---|---|
| Цена | **бесплатно, без лимитов** | $15–30+/мес, лимит минут |
| Приватность | **всё локально** | видео уходит в облако |
| Языки | русский + английский | много |
| ИИ-отбор моментов | Claude / эвристика | собственные модели |
| Караоке-субтитры | ✅ | ✅ |
| Автослежение за лицом | ❌ (blur/crop) | ✅ |
| Скорость | зависит от CPU | быстрое облако |

ViralCut не делает нейросетевой трекинг лиц и не имеет веб-интерфейса — это честная цена за «бесплатно и локально». Для говорящей головы в кадре режим `--style crop` покрывает 90% случаев.

## Дорожная карта

- [ ] Автокроп по лицу спикера
- [ ] Шаблоны стилей субтитров (цвета, шрифты, позиция)
- [ ] Веб-интерфейс
- [ ] Эмодзи-акценты в субтитрах
- [ ] Авто-хук текстом поверх первых секунд

---

## 🇬🇧 English

**ViralCut** turns long videos into viral vertical shorts — locally, for free.

**Pipeline:** Whisper transcription with word-level timestamps → AI virality analysis (Claude CLI / Claude API / built-in heuristic) → ffmpeg cuts 9:16 clips (blurred-background or center-crop) with Opus-style karaoke captions (2–3 big words, active word highlighted) → markdown report with titles, hooks, hashtags and virality scores.

### Install

```bash
pip install -r requirements.txt
# plus ffmpeg: scoop install ffmpeg / winget install Gyan.FFmpeg / apt install ffmpeg
```

### Use

```bash
python viralcut.py "podcast.mp4" --clips 6
python viralcut.py "https://youtube.com/watch?v=XXXX" --min-dur 20 --max-dur 45
```

Output: a `shorts_<name>` folder with ready-to-post MP4s and `report.md`.

Supported speech languages: **Russian and English**.

## License

MIT
