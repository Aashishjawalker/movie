# ==============================================================================
# movie CLI - One-line Universal Installer for Windows (PowerShell)
# ==============================================================================

$ErrorActionPreference = 'Stop'

$Repo = if ($env:GITHUB_REPO) { $env:GITHUB_REPO } else { "Aashishjawalker/movie" }
$Branch = if ($env:BRANCH) { $env:BRANCH } else { "main" }

Write-Host @"
  __  __  ______      _____ ______ 
 |  \/  |/ __ \ \    / /_ _|  ____|
 | \  / | |  | \ \  / / | || |__   
 | |\/| | |  | |\ \/ /  | ||  __|  
 | |  | | |__| | \  /  _| || |____ 
 |_|  |_|\____/   \/  |___|______| 
"@ -ForegroundColor Cyan

Write-Host "Installing movie CLI..." -ForegroundColor White

# 1. Check for Python
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    $PythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Python 3 is not installed or not in your PATH." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/ or run: winget install Python.Python.3.12" -ForegroundColor Yellow
    Exit 1
}

# 2. Destination folders
$InstallDir = Join-Path $env:USERPROFILE ".local\share\movie"
$BinDir = Join-Path $env:USERPROFILE ".local\bin"

if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }

# 3. Download Archive
$ArchiveUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$TempZip = Join-Path $env:TEMP "movie-install.zip"
$TempExtract = Join-Path $env:TEMP "movie-extract-$(Get-Random)"

Write-Host "==> Downloading from $Repo..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $ArchiveUrl -OutFile $TempZip

Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
$ExtractedFolder = (Get-ChildItem -Path $TempExtract -Directory)[0].FullName

# Copy to ~/.local/share/movie
Copy-Item -Path "$ExtractedFolder\*" -Destination $InstallDir -Recurse -Force

# Clean temp files
Remove-Item -Path $TempZip -Force -ErrorAction SilentlyContinue
Remove-Item -Path $TempExtract -Recurse -Force -ErrorAction SilentlyContinue

# 4. Create movie.cmd wrapper
$CmdLauncher = Join-Path $BinDir "movie.cmd"
"@echo off`r`npython `"$InstallDir\movie.py`" %*" | Out-File -FilePath $CmdLauncher -Encoding ascii -Force

# 5. Ensure $BinDir is in User PATH
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
    $env:Path = "$env:Path;$BinDir"
    Write-Host "Note: Added $BinDir to your User PATH." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✓ movie installed successfully!" -ForegroundColor Green
Write-Host "Installed to: $InstallDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "To start, restart PowerShell or run:" -ForegroundColor White
Write-Host "  movie" -ForegroundColor Green
