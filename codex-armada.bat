@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

if defined PYTHON (
  "%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if not errorlevel 1 (
    "%PYTHON%" -m codex_armada %*
    exit /b
  )
)

where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    py -%%V -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 (
      py -%%V -m codex_armada %*
      exit /b
    )
  )
)

for %%P in (python3 python) do (
  where %%P >nul 2>nul
  if not errorlevel 1 (
    %%P -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 (
      %%P -m codex_armada %*
      exit /b
    )
  )
)

echo ERROR: Python 3.11 or newer was not found. Set PYTHON to a compatible executable. 1>&2
exit /b 2
