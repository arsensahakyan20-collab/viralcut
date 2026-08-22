@echo off
chcp 65001 >nul
echo === ViralCut: установка зависимостей ===
where python >nul 2>nul || (echo Python не найден! Установите: https://www.python.org/downloads/ и поставьте галочку "Add to PATH" & pause & exit /b 1)
python -m pip install --upgrade pip >nul
python -m pip install -r "%~dp0requirements.txt"
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo ffmpeg не найден. Установите его одной командой:
    echo    scoop install ffmpeg
    echo или winget install Gyan.FFmpeg
) else (
    echo ffmpeg: OK
)
echo.
echo === Готово! Пример запуска: ===
echo    python viralcut.py "моё_видео.mp4"
pause
