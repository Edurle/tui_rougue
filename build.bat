@echo off
rem 一键打包：产出 dist\shanhai_rogue.exe（单文件，无需安装 Python 即可运行）
rem 依赖资源：assets\（字体）与 data\（内容 JSON）会自动内嵌进 exe

cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo [错误] 未找到 .venv，请先执行：
    echo    python -m venv .venv
    echo    .venv\Scripts\pip install tcod pyinstaller pytest pillow
    exit /b 1
)

.venv\Scripts\pyinstaller.exe --onefile --name shanhai_rogue ^
    --add-data "assets;assets" ^
    --add-data "data;data" ^
    main.py

echo.
echo 打包完成：dist\shanhai_rogue.exe
