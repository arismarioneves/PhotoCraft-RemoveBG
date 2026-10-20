# Installs PhotoCraft-RemoveBG for the current user. No administrator rights needed.
#
#   install.ps1                    install, or update an existing install
#   install.ps1 -Model rmbg-1.4    switch to the RMBG-1.4 model (non-commercial license)
#   install.ps1 -Model isnet       switch back to the default model
param(
    [ValidateSet('', 'isnet', 'rmbg-1.4')][string]$Model = '',
    [switch]$AcceptRmbgLicense,
    [string]$DataDir = '',
    [switch]$NoShortcuts,
    [switch]$NoModel
)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host $text -ForegroundColor Red; exit 1 }

if ($DataDir) {
    # A shortcut cannot hand a custom data folder to the helper, so custom folders are for testing only.
    if (-not $NoShortcuts) { Fail '-DataDir can only be used together with -NoShortcuts.' }
} else {
    $DataDir = Join-Path $env:LOCALAPPDATA 'PhotoCraft-RemoveBG'
}

if ($Model -eq 'rmbg-1.4' -and -not $AcceptRmbgLicense) {
    Write-Host 'RMBG-1.4 is made by BRIA AI and is licensed for non-commercial use only.'
    Write-Host 'Commercial use needs an agreement with BRIA. Terms: https://huggingface.co/briaai/RMBG-1.4'
    Write-Host -NoNewline 'Type I ACCEPT to use it: '
    if ([Console]::ReadLine() -ne 'I ACCEPT') {
        Write-Host 'License not accepted. Nothing was changed.'
        exit 1
    }
}

# onnxruntime 1.30 ships Windows wheels for Python 3.11 to 3.14 only. Versioned names are tried
# first: a plain "python" on the PATH is often older, and the Microsoft Store Python only adds
# python3.x aliases, without the py launcher.
function Find-Python {
    $check = "import sys,struct;print(sys.executable if (3,11)<=sys.version_info[:2]<=(3,14) and struct.calcsize('P')==8 else '')"
    $versions = '3.12', '3.13', '3.14', '3.11'
    $candidates = @()
    foreach ($v in $versions) { $candidates += , @('py', "-$v") }
    foreach ($v in $versions) { $candidates += , @("python$v") }
    foreach ($v in $versions) {
        $candidates += , @(Join-Path $env:LOCALAPPDATA "Programs\Python\Python$($v -replace '\.')\python.exe")
    }
    $candidates += , @('py', '-3')
    $candidates += , @('python')
    foreach ($cmd in $candidates) {
        if (-not (Get-Command $cmd[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($cmd | Select-Object -Skip 1)
        try { $found = & $cmd[0] @extra -c $check 2>$null } catch { continue }
        if ($found -and (Test-Path -LiteralPath $found.Trim())) { return $found.Trim() }
    }
    return $null
}

$configFile = Join-Path $DataDir 'config.json'
$photocraft = Join-Path $env:ProgramFiles 'PhotoCraft\photocraft.exe'
if (Test-Path -LiteralPath $configFile) {
    $saved = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
    if ($saved.photocraftExe) { $photocraft = $saved.photocraftExe }
}

Step 'Looking for PhotoCraft'
if (Test-Path -LiteralPath $photocraft) {
    Write-Host "PhotoCraft: $photocraft"
} else {
    Write-Host "PhotoCraft was not found at $photocraft. Install it, or set photocraftExe in $configFile." -ForegroundColor Yellow
}

Step 'Looking for Python 3.11 to 3.14 (64-bit)'
$python = Find-Python
if (-not $python) {
    Write-Host 'Python 3.11 to 3.14 (64-bit) was not found.'
    Write-Host -NoNewline 'Install Python 3.12 now with winget? (y/N): '
    if ([Console]::ReadLine() -notmatch '^[yY]') {
        Fail 'Install Python 3.12 from python.org and run this installer again.'
    }
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $python = Find-Python
    if (-not $python) { Fail 'Python was installed but cannot be found yet. Close this window and run the installer again.' }
}
Write-Host "Python: $python"

Step 'Preparing the Python environment (a few minutes the first time)'
[IO.Directory]::CreateDirectory($DataDir) | Out-Null
$venv = Join-Path $DataDir 'venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    try { & $venvPython -c 'import sys' 2>$null } catch { }
    if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $venv -Recurse -Force }
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the Python environment.' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $source 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Could not install the Python packages. Check the internet connection and try again.' }

Step "Copying the files to $DataDir"
$app = Join-Path $DataDir 'app'
if (Test-Path -LiteralPath $app) { Remove-Item -LiteralPath $app -Recurse -Force }
$package = Join-Path $app 'removebg'
[IO.Directory]::CreateDirectory($package) | Out-Null
Get-ChildItem -LiteralPath (Join-Path $source 'removebg') |
    Where-Object { $_.Name -ne '__pycache__' } |
    Copy-Item -Destination $package -Recurse -Force

$env:PHOTOCRAFT_REMOVEBG_HOME = $DataDir
$env:PYTHONPATH = $app
& $venvPython -m removebg.config ensure-token
if ($LASTEXITCODE -ne 0) { Fail 'Could not create the control token.' }

if ($Model -eq 'rmbg-1.4') {
    & $venvPython -m removebg.config set-model rmbg-1.4 --accept-license
} elseif ($Model -eq 'isnet') {
    & $venvPython -m removebg.config set-model isnet
}
if ($LASTEXITCODE -ne 0) { Fail 'Could not save the settings.' }

if (-not $NoModel) {
    Step 'Downloading the model (about 180 MB, only the first time)'
    $key = & $venvPython -c 'from removebg.config import load_config, resolve_model; print(resolve_model(load_config())[0])'
    & $venvPython -m removebg.models ensure $key.Trim()
    if ($LASTEXITCODE -ne 0) { Fail 'Could not download the model. Check the internet connection and run the installer again.' }
}

if (-not $NoShortcuts) {
    Step 'Creating the shortcuts'
    $shell = New-Object -ComObject WScript.Shell
    function New-Shortcut($path, $target, $arguments, $icon, $description) {
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = $target
        $link.Arguments = $arguments
        $link.WorkingDirectory = $app
        $link.IconLocation = $icon
        $link.Description = $description
        $link.Save()
        Write-Host "  $path"
    }
    $pythonw = Join-Path $venv 'Scripts\pythonw.exe'
    $icon = if (Test-Path -LiteralPath $photocraft) { "$photocraft,0" } else { "$pythonw,0" }
    $name = 'PhotoCraft (Remove Background).lnk'
    $description = 'Opens PhotoCraft with Filter > Plug-ins > Remove Background (AI)'
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) $name) $pythonw '-m removebg.helper' $icon $description
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) $name) $pythonw '-m removebg.helper' $icon $description
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('SendTo')) 'Remove background.lnk') $venvPython `
        '-m removebg.sendto --pause' "$env:SystemRoot\System32\imageres.dll,72" `
        'Saves a transparent PNG of each image in a cutouts folder'
}

Step 'Done'
Write-Host @'
In PhotoCraft:
  1. Open PhotoCraft with the "PhotoCraft (Remove Background)" shortcut.
  2. Select a layer.
  3. Filter > Plug-ins > Remove Background (AI).

Loose files: right-click the images or a folder > Send to > Remove background
(on Windows 11: Show more options > Send to).
'@
