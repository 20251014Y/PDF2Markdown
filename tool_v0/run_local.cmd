@echo off
@chcp 65001 >nul
@setlocal
@set "PYTHONUTF8=1"
@set "PYTHONIOENCODING=utf-8"
@set "PYTHONPATH=%~dp0"
@set "PDF2MD_ROOT=%~dp0.."
@set "PDF2MD_BACKEND=local"
@cd /d "%~dp0.."
@if exist "%~dp0.python\python.exe" (
  @"%~dp0.python\python.exe" -m converter_core.batch --backend local %*
) else (
  @"%~dp0.python-dev\Scripts\python.exe" -m converter_core.batch --backend local %*
)
@set "PDF2MD_EXIT=%ERRORLEVEL%"
@if not "%PDF2MD_NO_PAUSE%"=="1" if "%~1"=="" (
  @echo.
  @pause
)
@exit /b %PDF2MD_EXIT%
