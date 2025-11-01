@echo off
REM Registers or updates the MCP server as a Windows service using NSSM.
REM Usage: nssm-mcp-service.bat <venvDir> <repoRoot> <nssmExe>

setlocal enabledelayedexpansion

if "%~3"=="" (
    echo Usage: %~nx0 ^<venvDir^> ^<repoRoot^> ^<nssmExe^>
    exit /b 1
)

set VENV_DIR=%~1
set REPO_ROOT=%~2
set NSSM_EXE=%~3

set SERVICE_NAME=recava-mcp-server
set PYTHON_EXE=%VENV_DIR%\Scripts\python.exe
set APP_DIR=%REPO_ROOT%\mcp_server
set LOG_DIR=%REPO_ROOT%\logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo Registering service %SERVICE_NAME% using %NSSM_EXE%

"%NSSM_EXE%" install %SERVICE_NAME% "%PYTHON_EXE%" "-m" "mcp_server.app"
"%NSSM_EXE%" set %SERVICE_NAME% AppDirectory "%REPO_ROOT%"
"%NSSM_EXE%" set %SERVICE_NAME% AppStdout "%LOG_DIR%\mcp-server.out.log"
"%NSSM_EXE%" set %SERVICE_NAME% AppStderr "%LOG_DIR%\mcp-server.err.log"
"%NSSM_EXE%" set %SERVICE_NAME% AppStdoutCreationDisposition 4
"%NSSM_EXE%" set %SERVICE_NAME% AppStderrCreationDisposition 4
"%NSSM_EXE%" set %SERVICE_NAME% Start SERVICE_AUTO_START

echo Service registered. Use 'nssm start %SERVICE_NAME%' to launch.
endlocal
