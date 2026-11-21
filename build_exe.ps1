# Run from any directory. Output: dist\Tarneebot.exe
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildPython = Join-Path $projectDirectory ".venv\Scripts\python.exe"

Push-Location -LiteralPath $projectDirectory
try {
    if (-not (Test-Path -LiteralPath $buildPython)) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
    }
    & $buildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install the build dependencies." }

    $buildArguments = @(
        "--noconfirm", "--onefile", "--windowed", "--noupx",
        "--name", "Tarneebot",
        "--distpath", (Join-Path $projectDirectory "dist"),
        "--workpath", (Join-Path $projectDirectory "build\exe"),
        "--specpath", (Join-Path $projectDirectory "build"),
        "--paths", $projectDirectory,
        (Join-Path $projectDirectory "launch_gui.py")
    )
    & $buildPython -m PyInstaller @buildArguments
    if ($LASTEXITCODE -ne 0) { throw "Building Tarneebot.exe failed." }
    Write-Host "Built $(Join-Path $projectDirectory 'dist\Tarneebot.exe')"
} finally {
    Pop-Location
}
