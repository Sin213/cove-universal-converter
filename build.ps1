<#
.SYNOPSIS
    Build Cove Universal Converter into a Windows Setup installer and a
    single-file portable executable. Both artifacts bundle ffmpeg and pandoc.

.DESCRIPTION
    Runs locally on Windows (PowerShell 5.1+ or PowerShell 7) and inside the
    GitHub Actions windows-latest runner. Creates a private venv, installs
    build deps, generates the .ico from the PNG, downloads the gyan.dev ffmpeg
    release-essentials build and a pandoc Windows release, then runs
    PyInstaller twice:
      * --onedir  for the Inno Setup installer (Setup.exe)
      * --onefile for the standalone Portable.exe

.EXAMPLE
    .\build.ps1
    .\build.ps1 -Version 1.2.0
#>

[CmdletBinding()]
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$App         = "cove-universal-converter"
$ReleaseDir  = "release"
$FfmpegUrl   = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$PandocVer   = "3.1.13"
$PandocUrl   = "https://github.com/jgm/pandoc/releases/download/$PandocVer/pandoc-$PandocVer-windows-x86_64.zip"

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Download-File([string]$url, [string]$dest) {
    & curl.exe --silent --show-error --fail --location --output $dest $url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $url" }
}

Step "Building $App v$Version"

# --- 1. Build environment ----------------------------------------------------
Step "[1/8] Creating build venv"
if (Test-Path .buildenv) { Remove-Item -Recurse -Force .buildenv }
python -m venv .buildenv
& .\.buildenv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.buildenv\Scripts\python.exe -m pip install --quiet `
    PySide6 Pillow pillow-heif pypdf xhtml2pdf pyinstaller

# --- 2. Generate .ico from the PNG ------------------------------------------
Step "[2/8] Generating cove_icon.ico"
& .\.buildenv\Scripts\python.exe -c @"
from PIL import Image
Image.open('cove_icon.png').save(
    'cove_icon.ico',
    sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)],
)
"@

# --- 3. Download ffmpeg ------------------------------------------------------
Step "[3/8] Downloading ffmpeg (gyan.dev release-essentials)"
$ffTmp = Join-Path ([IO.Path]::GetTempPath()) ("ffmpeg-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $ffTmp | Out-Null
$ffZip = Join-Path $ffTmp "ffmpeg.zip"
Download-File $FfmpegUrl $ffZip
Expand-Archive -Path $ffZip -DestinationPath $ffTmp -Force

$ffRoot = Get-ChildItem -Path $ffTmp -Directory |
          Where-Object { $_.Name -like 'ffmpeg-*' } |
          Select-Object -First 1
if (-not $ffRoot) { throw "Could not locate extracted ffmpeg folder under $ffTmp" }

$ffmpegExe     = Join-Path $ffRoot.FullName "bin\ffmpeg.exe"
$ffmpegLicense = Join-Path $ffRoot.FullName "LICENSE"
if (-not (Test-Path $ffmpegExe)) { throw "ffmpeg.exe missing from downloaded archive" }

# --- 4. Download pandoc ------------------------------------------------------
Step "[4/8] Downloading pandoc $PandocVer"
$pdTmp = Join-Path ([IO.Path]::GetTempPath()) ("pandoc-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $pdTmp | Out-Null
$pdZip = Join-Path $pdTmp "pandoc.zip"
Download-File $PandocUrl $pdZip
Expand-Archive -Path $pdZip -DestinationPath $pdTmp -Force
$pandocExe = Get-ChildItem -Path $pdTmp -Filter pandoc.exe -Recurse |
             Select-Object -First 1 -ExpandProperty FullName
if (-not $pandocExe) { throw "pandoc.exe missing from downloaded archive" }

# --- 5. PyInstaller: one-dir (installer input) -------------------------------
Step "[5/8] PyInstaller (one-dir for installer)"
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist  }

$commonArgs = @(
    '--noconfirm', '--clean', '--log-level', 'WARN',
    '--windowed',
    '--name', $App,
    '--icon', 'cove_icon.ico',
    '--paths', '.',
    '--add-data', ("cove_icon.png" + [IO.Path]::PathSeparator + "."),
    '--hidden-import', 'xhtml2pdf',
    '--hidden-import', 'reportlab',
    '--hidden-import', 'pillow_heif',
    '--hidden-import', 'pypdf',
    '--exclude-module', 'PySide6.QtWebEngineCore',
    '--exclude-module', 'PySide6.QtWebEngineWidgets',
    '--exclude-module', 'PySide6.QtQml',
    '--exclude-module', 'PySide6.QtQuick',
    '--exclude-module', 'PySide6.QtPdf',
    '--exclude-module', 'PySide6.Qt3DCore',
    '--exclude-module', 'PySide6.QtCharts',
    '--exclude-module', 'PySide6.QtDataVisualization',
    '--exclude-module', 'tkinter',
    '--add-binary', ($ffmpegExe + [IO.Path]::PathSeparator + '.'),
    '--add-binary', ($pandocExe + [IO.Path]::PathSeparator + '.'),
    'packaging\launcher.py'
)

& .\.buildenv\Scripts\pyinstaller.exe @commonArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onedir) failed" }

$dirAppDir = Join-Path 'dist' $App
Copy-Item cove_icon.png $dirAppDir -Force
if (Test-Path README.md) { Copy-Item README.md $dirAppDir -Force }
if (Test-Path LICENSE)   { Copy-Item LICENSE   $dirAppDir -Force }
if (Test-Path $ffmpegLicense) {
    Copy-Item $ffmpegLicense (Join-Path $dirAppDir "FFMPEG-LICENSE.txt") -Force
}

# --- 6. PyInstaller: one-file (portable) -------------------------------------
Step "[6/8] PyInstaller (one-file portable)"
$portableName = "$App-portable"
& .\.buildenv\Scripts\pyinstaller.exe `
    --noconfirm --clean --log-level WARN `
    --onefile --windowed `
    --name $portableName `
    --icon cove_icon.ico `
    --paths . `
    --add-data ("cove_icon.png" + [IO.Path]::PathSeparator + ".") `
    --hidden-import xhtml2pdf `
    --hidden-import reportlab `
    --hidden-import pillow_heif `
    --hidden-import pypdf `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.QtCharts `
    --exclude-module PySide6.QtDataVisualization `
    --exclude-module tkinter `
    --add-binary ($ffmpegExe + [IO.Path]::PathSeparator + '.') `
    --add-binary ($pandocExe + [IO.Path]::PathSeparator + '.') `
    packaging\launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onefile) failed" }

# --- 7. Build installer + stage portable -------------------------------------
Step "[7/8] Building Setup installer with Inno Setup"
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

$iscc = $null
foreach ($candidate in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)) {
    if ($candidate -and (Test-Path $candidate)) { $iscc = $candidate; break }
}
if (-not $iscc) {
    $inPath = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($inPath) { $iscc = $inPath.Source }
}
if (-not $iscc) { throw "Inno Setup (iscc.exe) not found. Install Inno Setup 6." }

$absSource  = (Resolve-Path $dirAppDir).Path
$absRelease = (Resolve-Path $ReleaseDir).Path
$absIcon    = (Resolve-Path cove_icon.ico).Path

& $iscc `
    "/DAppVersion=$Version" `
    "/DSourceDir=$absSource" `
    "/DOutputDir=$absRelease" `
    "/DIconFile=$absIcon" `
    packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }

Step "Staging portable exe"
$portableSrc  = Join-Path 'dist' "$portableName.exe"
$portableDest = Join-Path $ReleaseDir ("{0}-{1}-Portable.exe" -f $App, $Version)
if (Test-Path $portableDest) { Remove-Item -Force $portableDest }
Copy-Item $portableSrc $portableDest -Force

# --- 8. Cleanup --------------------------------------------------------------
Step "[8/8] Cleaning up"
Remove-Item -Recurse -Force .buildenv, build, dist, cove_icon.ico -ErrorAction SilentlyContinue
Get-ChildItem -Filter *.spec | Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $ffTmp, $pdTmp -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Get-ChildItem $ReleaseDir -Filter "*$Version*" | ForEach-Object {
    Write-Host ("  {0}" -f $_.FullName)
}
