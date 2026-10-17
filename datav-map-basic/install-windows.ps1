$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ZipPath = Join-Path $ProjectRoot 'datav-map-basic-windows-x64-node_modules.zip'
$NodeModulesPath = Join-Path $ProjectRoot 'node_modules'

if (-not (Test-Path $ZipPath)) {
  throw "Windows dependency archive not found: $ZipPath"
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
  throw "Unsupported Node.js version: $nodeVersion. Vite 7 requires Node.js 20.19+ or 22.12+."
}

if (Test-Path $NodeModulesPath) {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $backupPath = Join-Path $ProjectRoot "node_modules.backup-$stamp"
  Move-Item -LiteralPath $NodeModulesPath -Destination $backupPath
  Write-Host "Backed up existing node_modules to: $backupPath"
}

Expand-Archive -LiteralPath $ZipPath -DestinationPath $ProjectRoot -Force

$BinPath = Join-Path $ProjectRoot 'node_modules\.bin'
New-Item -ItemType Directory -Path $BinPath -Force | Out-Null
Set-Content -LiteralPath (Join-Path $BinPath 'vite.cmd') -Encoding ASCII -Value @(
  '@ECHO off'
  'SETLOCAL'
  'node "%~dp0..\vite\bin\vite.js" %*'
)
Set-Content -LiteralPath (Join-Path $BinPath 'tsc.cmd') -Encoding ASCII -Value @(
  '@ECHO off'
  'SETLOCAL'
  'node "%~dp0..\typescript\bin\tsc" %*'
)
Set-Content -LiteralPath (Join-Path $BinPath 'tsserver.cmd') -Encoding ASCII -Value @(
  '@ECHO off'
  'SETLOCAL'
  'node "%~dp0..\typescript\bin\tsserver" %*'
)

$esbuild = Join-Path $ProjectRoot 'node_modules\@esbuild\win32-x64\esbuild.exe'
$rollup = Join-Path $ProjectRoot 'node_modules\@rollup\rollup-win32-x64-msvc\rollup.win32-x64-msvc.node'
if (-not (Test-Path $esbuild) -or -not (Test-Path $rollup) -or -not (Test-Path (Join-Path $BinPath 'vite.cmd'))) {
  throw 'Windows native dependency check failed. Re-extract the archive or run npm ci with network access.'
}

Write-Host 'Windows x64 dependencies installed successfully.'
Write-Host 'Start development server: npm run dev'
Write-Host 'LAN access: npm run dev:lan'
