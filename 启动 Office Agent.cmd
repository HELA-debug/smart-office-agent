@echo off
chcp 65001 >nul 2>nul
title Office Agent
cd /d "%~dp0"
setlocal

echo.
echo   Office Agent
echo.

rem ===========================================================================
rem ASCII ONLY. cmd.exe reads a batch file byte by byte, and a line that mixes
rem multibyte characters can make it resume mid-character, so the next line
rem dies with "is not recognized as an internal or external command".
rem All Chinese text therefore lives in scripts\messages\*.txt and is printed
rem with `type` (the console is already switched to UTF-8 above).
rem To change the wording, edit those txt files - never add Chinese here.
rem ===========================================================================

if not exist "%~dp0scripts\launch.py" goto no_launcher

rem A machine-wide PYTHONHOME (a python installed at a drive root sets it to
rem "E:\") overrides the venv stdlib, so the interpreter loads another
rem version's Lib and dies before printing anything:
rem   AssertionError: SRE module mismatch
rem That also breaks the "does this python work" probe below, which then looks
rem like "no python found". Clear both before any python runs.
set "PYTHONHOME="
set "PYTHONPATH="

set "PY="
set "PYARG="

rem Find a Python that actually runs, WITHOUT trusting PATH. On many machines
rem the only `python` on PATH is the Microsoft Store redirector
rem (python.exe -> AppInstallerPythonRedirector.exe): it prints nothing and
rem exits 9009, which looks exactly like "I clicked it and nothing happened".
rem   1) the project venv - present after the first run, always correct
call :try "%~dp0.venv\Scripts\python.exe"

rem   2) the official py launcher (installed into C:\Windows by python.org)
if not defined PY for /f "delims=" %%P in ('where py 2^>nul') do call :try_py "%%P"

rem   3) python from PATH, but skip the Store redirector first
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do call :try_skip_store "%%P"

rem   4) python.org default install dirs (user did not tick "Add to PATH")
if not defined PY call :scan "%LocalAppData%\Programs\Python"
if not defined PY call :scan "%ProgramFiles%"
if not defined PY call :scan "%ProgramFiles(x86)%"

if not defined PY goto no_python

"%PY%" %PYARG% "%~dp0scripts\launch.py" %*
set "RC=%ERRORLEVEL%"

rem 0 = finished normally (user closed the window, or Ctrl+C)
rem 2 = launcher already explained the problem and waited for a key; do not
rem     make the user press twice
if "%RC%"=="0" goto done
if "%RC%"=="2" goto done

rem Python died before printing anything: do not let the window vanish
type "%~dp0scripts\messages\crashed.txt"
pause >nul
goto done

rem ------------------------------------------------------------------ helpers
:try
rem %1 = full path to python.exe; must be able to import sys to count
if defined PY exit /b
if not exist "%~1" exit /b
"%~1" -c "import sys" >nul 2>nul
if errorlevel 1 exit /b
set "PY=%~1"
exit /b

:try_py
rem %1 = py.exe; ask it for a 3.x and keep it only if that works
if defined PY exit /b
if not exist "%~1" exit /b
"%~1" -3 -c "import sys" >nul 2>nul
if errorlevel 1 exit /b
set "PY=%~1"
set "PYARG=-3"
exit /b

:try_skip_store
rem %1 = python.exe found on PATH; reject the Store redirector
if defined PY exit /b
echo %~1 | find /i "WindowsApps" >nul && exit /b
call :try "%~1"
exit /b

:scan
rem %1 = parent folder; look for Python3*\python.exe inside it
if defined PY exit /b
for /d %%D in ("%~1\Python3*") do call :try "%%~fD\python.exe"
exit /b

rem ------------------------------------------------------------------- errors
:no_python
type "%~dp0scripts\messages\no-python.txt"
pause >nul
start "" "https://www.python.org/downloads/"
endlocal & exit /b 1

:no_launcher
type "%~dp0scripts\messages\no-launcher.txt"
pause >nul
endlocal & exit /b 1

:done
endlocal & exit /b %RC%
