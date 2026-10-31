@echo off
REM run.bat - start miagpt in this window (Windows). No service, no systemd.
REM First run creates .venv and installs the two dependencies.
REM   run.bat            start it
REM   run.bat --check    check the install without starting
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto ready

echo first run: creating .venv and installing dependencies
py -3 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto install
python -m venv .venv

:install
if not exist ".venv\Scripts\python.exe" goto nopython
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

:ready
if not exist ".env" goto noenv
if not exist "persona.md" goto nopersona
".venv\Scripts\python.exe" bot.py %*
echo.
echo miagpt stopped.
pause
exit /b 0

:nopython
echo could not create a virtualenv.
echo install Python 3.11 or newer from python.org and tick "Add python.exe to PATH".
pause
exit /b 1

:noenv
echo no .env found - run:  copy .env.example .env   and put your bot token in it
pause
exit /b 1

:nopersona
echo no persona.md found - run:  copy persona.example.md persona.md   and write yours
pause
exit /b 1
