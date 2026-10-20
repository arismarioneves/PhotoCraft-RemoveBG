# Removes PhotoCraft-RemoveBG for the current user. PhotoCraft itself is not touched.
param([string]$DataDir = (Join-Path $env:LOCALAPPDATA 'PhotoCraft-RemoveBG'))
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($DataDir).TrimEnd('\') + '\'

function Inside($path) { return $path -and $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) }

# The venv python.exe is a launcher that starts the base interpreter as a child, so stop both.
$all = @(Get-CimInstance Win32_Process)
$launchers = @($all | Where-Object { (Inside $_.ExecutablePath) -and $_.CommandLine -like '*removebg.helper*' })
$ids = @($launchers.ProcessId)
$targets = @($all | Where-Object { $ids -contains $_.ProcessId -or $ids -contains $_.ParentProcessId })
foreach ($p in $targets) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped the helper (PID $($p.ProcessId))."
}

$shell = New-Object -ComObject WScript.Shell
$name = 'PhotoCraft (Remove Background).lnk'
$shortcuts = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) $name),
    (Join-Path ([Environment]::GetFolderPath('Programs')) $name),
    (Join-Path ([Environment]::GetFolderPath('SendTo')) 'Remove background.lnk')
)
foreach ($s in $shortcuts) {
    if ((Test-Path -LiteralPath $s) -and (Inside $shell.CreateShortcut($s).TargetPath)) {
        Remove-Item -LiteralPath $s -Force
        Write-Host "Removed: $s"
    }
}

if (Test-Path -LiteralPath $DataDir) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -LiteralPath $DataDir -Recurse -Force
            break
        } catch {
            if ($attempt -eq 5) { throw }
            Start-Sleep -Seconds 1
        }
    }
    Write-Host "Removed: $DataDir"
}
Write-Host 'PhotoCraft itself was not changed.'
