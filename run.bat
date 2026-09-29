@echo off
rem Lance l'agregateur une fois. A declencher par le Planificateur de taches Windows.
rem Les secrets (DISCORD_WEBHOOK_URL, ANTHROPIC_API_KEY) sont lus dans le fichier .env
rem Journal : logs\run.log

setlocal
cd /d "%~dp0"

if not exist logs mkdir logs
if not exist .env (
    echo [%date% %time%] Fichier .env manquant >> logs\run.log
    exit /b 1
)

rem Charge les lignes CLE=VALEUR du .env (les lignes commencant par # sont ignorees)
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"

rem Accents correctement ecrits dans le journal
set PYTHONUTF8=1

rem Repart d'un journal neuf s'il depasse 5 Mo
for %%F in (logs\run.log) do if %%~zF GTR 5000000 move /y logs\run.log logs\run.old.log >nul

echo ===== %date% %time% ===== >> logs\run.log
".venv\Scripts\python.exe" -m besancon_events >> logs\run.log 2>&1
set RC=%ERRORLEVEL%
echo Code de sortie : %RC% >> logs\run.log
exit /b %RC%
