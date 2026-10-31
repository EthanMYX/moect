param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\..\outputs'))
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
$compiler = Join-Path $env:LOCALAPPDATA 'Programs\InnoSetup\ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Install Inno Setup 6.5+ first.' }
$exe = Join-Path $project 'dist\Moect\Moect.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Run python build.py first.' }
$version = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
$support = Join-Path $project 'build-support'
New-Item -ItemType Directory -Path $support -Force | Out-Null
New-Item -ItemType Directory -Path $output -Force | Out-Null
$bootstrap = Join-Path $support 'MicrosoftEdgeWebview2Setup.exe'
if (-not (Test-Path -LiteralPath $bootstrap)) {
    Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrap
}
$signature = Get-AuthenticodeSignature -LiteralPath $bootstrap
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'WebView2 bootstrapper Microsoft signature verification failed.'
}
& $compiler "/DAppVersion=$version" "/O$output" (Join-Path $PSScriptRoot 'Moect.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
