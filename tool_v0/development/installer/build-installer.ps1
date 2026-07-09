$ErrorActionPreference = "Stop"
$installer = $PSScriptRoot
$development = Split-Path -Parent $installer
$tool = Split-Path -Parent $development
$root = Split-Path -Parent $tool
$stage = Join-Path $env:TEMP "pdf2markdown-v0-installer-payload"
$payload = Join-Path $installer "payload.zip"
$output = Join-Path $root "PDF2Markdown-Installer_v0.exe"
$buildOutput = Join-Path $env:TEMP "PDF2Markdown-Installer_v0-build.exe"

Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $payload -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $buildOutput -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $root,$installer -Filter "~PDF2Markdown*.CAB" -Force -ErrorAction SilentlyContinue | Remove-Item -Force
New-Item -ItemType Directory -Force -Path (Join-Path $stage "tool_v0") | Out-Null
Copy-Item -LiteralPath (Join-Path $tool "converter_core") -Destination (Join-Path $stage "tool_v0\converter_core") -Recurse
Copy-Item -LiteralPath (Join-Path $tool "README.md"),(Join-Path $tool "run_local.cmd"),(Join-Path $tool "run_api.cmd"),(Join-Path $tool "VERSION.txt") -Destination (Join-Path $stage "tool_v0")
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination (Join-Path $stage "README.md")
New-Item -ItemType Directory -Force -Path (Join-Path $stage "input"),(Join-Path $stage "output") | Out-Null
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $payload -CompressionLevel Optimal

$sed = Join-Path $installer "installer.sed"
$sedText = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=
FinishMessage=
TargetName=$buildOutput
FriendlyName=%FriendlyName%
AppLaunched=wscript.exe launch.vbs
PostInstallCmd=<None>
AdminQuietInstCmd=wscript.exe launch.vbs
UserQuietInstCmd=wscript.exe launch.vbs
SourceFiles=SourceFiles
[Strings]
InstallPrompt=PDF2Markdown converts PDFs into clean Markdown with formulas, figures, and README notes. Start installer?
FriendlyName=PDF2Markdown v0
FILE0=launch.vbs
FILE1=install.ps1
FILE2=payload.zip
[SourceFiles]
SourceFiles0=$installer\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@
$sedText | Set-Content -LiteralPath $sed -Encoding Default
$iexpress = Start-Process -FilePath "$env:WINDIR\System32\iexpress.exe" -ArgumentList @("/N",$sed) -Wait -PassThru
if ($iexpress.ExitCode -ne 0) { throw "IExpress failed with exit code $($iexpress.ExitCode)." }
if (-not (Test-Path $buildOutput)) { throw "IExpress did not create the installer." }
Copy-Item -LiteralPath $buildOutput -Destination $output -Force
Remove-Item -LiteralPath $buildOutput -Force
Get-ChildItem -LiteralPath $root,$installer -Filter "~PDF2Markdown*.CAB" -Force -ErrorAction SilentlyContinue | Remove-Item -Force
Remove-Item -LiteralPath $payload,$sed -Force -ErrorAction SilentlyContinue
Get-Item $output | Select-Object FullName,Length
