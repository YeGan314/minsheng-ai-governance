$ErrorActionPreference = 'Stop'

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $PackageRoot '..\frontend'
$ZipPath = Join-Path $PackageRoot 'frontend-windows-x64-node_modules.zip'
$NodeModulesPath = Join-Path $FrontendRoot 'node_modules'

if (-not (Test-Path $ZipPath)) {
  throw "Frontend dependency archive not found: $ZipPath"
}
if (-not (Test-Path (Join-Path $FrontendRoot 'package.json'))) {
  throw "Frontend project not found: $FrontendRoot"
}

$nodeVersion = (& node --version 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $nodeVersion) {
  throw 'Node.js was not found. Install Node.js 20.19+ or 22.12+ first.'
}

$versionText = $nodeVersion -replace '^v', ''
$versionParts = $versionText.Split('.')
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
$supportedNode = (($major -eq 20 -and $minor -ge 19) -or ($major -eq 22 -and $minor -ge 12) -or ($major -gt 22))
if (-not $supportedNode) {
  throw "Unsupported Node.js version: $nodeVersion. Vite requires Node.js 20.19+ or 22.12+."
}

if (Test-Path $NodeModulesPath) {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $backupPath = Join-Path $FrontendRoot "node_modules.backup-$stamp"
  Move-Item -LiteralPath $NodeModulesPath -Destination $backupPath
  Write-Host "Backed up existing frontend node_modules to: $backupPath"
}

Expand-Archive -LiteralPath $ZipPath -DestinationPath $FrontendRoot -Force

$BinPath = Join-Path $FrontendRoot 'node_modules\.bin'
New-Item -ItemType Directory -Path $BinPath -Force | Out-Null
Set-Content -LiteralPath (Join-Path $BinPath 'vite.cmd') -Encoding ASCII -Value @(
  '@ECHO off'
  'SETLOCAL'
  'node "%~dp0..\vite\bin\vite.js" %*'
)

$esbuild = Join-Path $FrontendRoot 'node_modules\@esbuild\win32-x64\esbuild.exe'
$rollup = Join-Path $FrontendRoot 'node_modules\@rollup\rollup-win32-x64-msvc\rollup.win32-x64-msvc.node'
$vite = Join-Path $FrontendRoot 'node_modules\.bin\vite.cmd'
if (-not (Test-Path $esbuild) -or -not (Test-Path $rollup) -or -not (Test-Path $vite)) {
  throw 'Frontend Windows dependency check failed.'
}

Write-Host 'Frontend Windows x64 dependencies installed successfully.'
Write-Host 'Run: Set-Location ..\frontend; npm run dev'
