#requires -version 5.1
<#
.SYNOPSIS
Prepara el host Windows 11 para ejecutar el MCP server como servicio.

.DESCRIPTION
1. Crea/actualiza un entorno virtual Python.
2. Instala dependencias del MCP server.
3. Descarga NSSM (si no existe) y registra el servicio opcionalmente.

Ejemplo:
  .\install.ps1 -RepoRoot "C:\recava-agent-audit" -RegisterService
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$RepoRoot = (Resolve-Path "..\..").Path,

    [switch]$RegisterService,

    [string]$PythonExe = "py"
)

$ErrorActionPreference = "Stop"

function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }

$mcpDir = Join-Path $RepoRoot "mcp_server"
$venvDir = Join-Path $mcpDir ".venv"
$pythonArgs = "-3.11"

Write-Info "Usando repositorio: $RepoRoot"

if (-not (Test-Path $mcpDir)) {
    throw "Directorio $mcpDir no encontrado. Asegúrate de clonar el repo antes."
}

if (-not (Test-Path $venvDir)) {
    Write-Info "Creando entorno virtual en $venvDir"
    & $PythonExe $pythonArgs -m venv $venvDir
} else {
    Write-Info "Entorno virtual ya existe, se reutilizará."
}

$pipExe = Join-Path $venvDir "Scripts\pip.exe"

Write-Info "Instalando dependencias..."
& $pipExe install --upgrade pip
& $pipExe install -r (Join-Path $mcpDir "requirements.txt")

if ($RegisterService) {
    $nssmDir = Join-Path $RepoRoot "ops\windows\nssm"
    $nssmExe = Join-Path $nssmDir "nssm.exe"

    if (-not (Test-Path $nssmExe)) {
        Write-Info "Descargando NSSM..."
        New-Item -ItemType Directory -Path $nssmDir -Force | Out-Null
        $nssmZip = Join-Path $nssmDir "nssm.zip"
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $nssmZip
        Expand-Archive -Path $nssmZip -DestinationPath $nssmDir -Force
        Remove-Item $nssmZip
        $nssmExe = Get-ChildItem -Path $nssmDir -Recurse -Filter "nssm.exe" | Select-Object -First 1 -ExpandProperty FullName
    }

    if (-not $nssmExe) {
        throw "No se pudo localizar nssm.exe. Descarga manualmente desde https://nssm.cc/"
    }

    $serviceBat = Join-Path $RepoRoot "ops\windows\nssm-mcp-service.bat"
    Write-Info "Registrando servicio NSSM mediante $serviceBat"
    & $serviceBat $venvDir $RepoRoot $nssmExe
}

Write-Info "Instalación completada."
