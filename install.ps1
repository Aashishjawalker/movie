# ==============================================================================
# movie CLI - One-line Universal Installer for Windows (PowerShell)
# Automatically installs Python if missing, sets up movie CLI globally.
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

# Helper function to find Python across known paths and PATH
function Find-PythonExecutable {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command python3 -ErrorAction SilentlyContinue }
    if (-not $cmd) { $cmd = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $cmd) {
        $KnownPaths = @(
            "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
            "C:\Python312\python.exe",
            "C:\Python311\python.exe",
            "C:\Program Files\Python312\python.exe",
            "C:\Program Files\Python311\python.exe"
        )
        foreach ($p in $KnownPaths) {
            if (Test-Path $p) {
                $dir = Split-Path $p
                $env:Path = "$dir;$dir\Scripts;$env:Path"
                return $p
            }
        }
    } else {
        return $cmd.Source
    }
    return $null
}

# 1. Check for Python; auto-install if not found
$PythonPath = Find-PythonExecutable

if (-not $PythonPath) {
    Write-Host ""
    Write-Host "==> Python 3 was not found. Installing Python 3 automatically..." -ForegroundColor Yellow
    
    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($Winget) {
        Write-Host "==> Installing Python 3.12 via Windows Package Manager..." -ForegroundColor Cyan
        Start-Process -FilePath "winget" -ArgumentList "install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent" -Wait -NoNewWindow
    } else {
        Write-Host "==> Downloading official Python 3 installer from python.org..." -ForegroundColor Cyan
        $TempInstaller = Join-Path $env:TEMP "python-installer.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe" -OutFile $TempInstaller
        Write-Host "==> Installing Python silently..." -ForegroundColor Cyan
        Start-Process -FilePath $TempInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
        Remove-Item $TempInstaller -Force -ErrorAction SilentlyContinue
    }

    # Refresh PATH environment variable in current process
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $MachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$UserPath;$MachinePath;$env:Path"

    $PythonPath = Find-PythonExecutable
}

if (-not $PythonPath) {
    Write-Host "[ERROR] Could not automatically install Python." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/ and re-run." -ForegroundColor Yellow
    Exit 1
}

Write-Host "Using Python: $PythonPath" -ForegroundColor DarkGray

# Ensure windows-curses is available
Write-Host "==> Checking terminal dependencies..." -ForegroundColor Cyan
Start-Process -FilePath $PythonPath -ArgumentList "-m pip install --quiet windows-curses" -Wait -NoNewWindow -ErrorAction SilentlyContinue

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
"@echo off`r`n`"$PythonPath`" `"$InstallDir\movie.py`" %*" | Out-File -FilePath $CmdLauncher -Encoding ascii -Force

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
Write-Host "You can now run:" -ForegroundColor White
Write-Host "  movie" -ForegroundColor Green
