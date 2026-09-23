@echo off
setlocal
cd /d "%~dp0\.."
echo Starting Validation PostgreSQL DB Manager...
if not "%VALIDATION_PG_CTL%"=="" if not "%VALIDATION_PG_DATA%"=="" (
  "%VALIDATION_PG_CTL%" -D "%VALIDATION_PG_DATA%" status >nul 2>&1
  if errorlevel 1 (
    "%VALIDATION_PG_CTL%" -D "%VALIDATION_PG_DATA%" -l "%CD%\logs\postgresql.log" start
  )
)
start "" python Validation\DB_Manager\db_manager.py
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:5050
