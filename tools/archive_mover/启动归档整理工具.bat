@echo off
setlocal
title Archive Mover

:: Resolve project root directory
set "PROJECT_ROOT=%~dp0..\.."
pushd "%PROJECT_ROOT%"

:: Add user local bin to PATH if uv or python is there
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

:: Launch GUI without keeping a black DOS console window open when no CLI args are passed
if "%~1"=="" (
    if exist ".venv\Scripts\pythonw.exe" (
        start "" ".venv\Scripts\pythonw.exe" tools\archive_mover\run.py
        popd
        endlocal
        exit /b 0
    )
)

:: Prefer project virtualenv python directly (for CLI mode or fallback)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools\archive_mover\run.py %*
) else (
    uv run python tools\archive_mover\run.py %*
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Program exited with error code: %errorlevel%
    pause
)

popd
endlocal
