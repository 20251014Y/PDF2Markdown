param(
    [string]$TestInstallRoot = "",
    [switch]$Unattended
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "PDF2Markdown v0 Installer"
$script:ProgressForm = $null
$script:ProgressLabel = $null
$script:ProgressBar = $null
$script:LogBox = $null
$script:InstallPathLabel = $null
$script:TimeLabel = $null
$script:SizeLabel = $null
$script:DownloadLabel = $null
$script:InstallStopwatch = $null
$script:UiTimer = $null
$script:ActivityDots = 0
$script:InstallerMutex = $null
$script:CancelRequested = $false
$script:AllowProgressClose = $false

function Get-GpuInfo {
    $command = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $command) {
        $candidate = Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"
        if (Test-Path $candidate) { $command = $candidate }
    }
    if (-not $command) { return "未检测到 NVIDIA GPU" }
    try {
        return ((& $command --query-gpu=name,memory.total --format=csv,noheader 2>$null | Select-Object -First 1) -join "").Trim()
    }
    catch { return "NVIDIA GPU 信息读取失败" }
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Format-Bytes([double]$Bytes) {
    if ($Bytes -ge 1073741824) { return ("{0:N2} GB" -f ($Bytes / 1073741824)) }
    if ($Bytes -ge 1048576) { return ("{0:N1} MB" -f ($Bytes / 1048576)) }
    if ($Bytes -ge 1024) { return ("{0:N1} KB" -f ($Bytes / 1024)) }
    return ("{0:N0} B" -f $Bytes)
}

function Get-ProjectSizeText([string]$Mode) {
    if ($Mode -eq "api") { return "预计项目总大小：约 100–300 MB（API轻量版）" }
    return "预计项目总大小：约 7–8 GB（本地模型版）"
}

function Set-DownloadInfo([string]$Text) {
    if (-not $script:DownloadLabel) { return }
    $script:DownloadLabel.Tag = $Text
    $script:DownloadLabel.Text = "当前处理：" + $Text
    [Windows.Forms.Application]::DoEvents()
}

function Stamp-ReadmeMode([string]$InstallRoot, [string]$Mode) {
    $modeText = if ($Mode -eq "api") { "工具版本：v0；当前运行模式：MinerU API（联网、轻量）" } else { "工具版本：v0；当前运行模式：本地 MinerU VLM（GPU、可离线）" }
    foreach ($readme in @((Join-Path $InstallRoot "README.md"), (Join-Path $InstallRoot "tool_v0\README.md"))) {
        if (Test-Path -LiteralPath $readme) {
            $text = Get-Content -LiteralPath $readme -Raw -Encoding UTF8
            $text = $text -replace "(?s)^> (?:当前安装版本|工具版本)：.*?\r?\n\r?\n", ""
            Write-Utf8NoBom $readme ("> " + $modeText + [Environment]::NewLine + [Environment]::NewLine + $text)
        }
    }
}

function Show-ProgressWindow {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $script:ProgressForm = New-Object Windows.Forms.Form
    $script:ProgressForm.Text = "PDF2Markdown v0 - 正在安装"
    $script:ProgressForm.Size = New-Object Drawing.Size(640,480)
    $script:ProgressForm.StartPosition = "CenterScreen"
    $script:ProgressForm.FormBorderStyle = "FixedDialog"
    $script:ProgressForm.ControlBox = $true
    $script:ProgressForm.MinimizeBox = $true
    $script:ProgressForm.MaximizeBox = $false
    $script:ProgressForm.ShowInTaskbar = $true
    $script:ProgressForm.Add_Activated({
        param($sender,$eventArgs)
        if ($sender.WindowState -eq [Windows.Forms.FormWindowState]::Minimized) {
            $sender.WindowState = [Windows.Forms.FormWindowState]::Normal
            $sender.BringToFront()
        }
    })
    $script:ProgressForm.Add_FormClosing({
        param($sender,$eventArgs)
        if ($script:AllowProgressClose) { return }
        $answer = [Windows.Forms.MessageBox]::Show(
            "安装仍在进行。是否停止安装并关闭窗口？",
            "停止安装",
            [Windows.Forms.MessageBoxButtons]::YesNo,
            [Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($answer -eq [Windows.Forms.DialogResult]::Yes) {
            $script:CancelRequested = $true
        } else {
            $eventArgs.Cancel = $true
        }
    })
    $heading = New-Object Windows.Forms.Label
    $heading.Text = if ($installMode -eq "api") { "正在安装 PDF2Markdown_API v0" } else { "正在安装 PDF2Markdown_Local v0" }
    $heading.Font = New-Object Drawing.Font -ArgumentList @("Microsoft YaHei UI",16,[Drawing.FontStyle]::Bold)
    $heading.SetBounds(28,22,540,38)
    $script:ProgressForm.Controls.Add($heading)
    $script:ProgressLabel = New-Object Windows.Forms.Label
    $script:ProgressLabel.Text = "准备安装……"
    $script:InstallPathLabel = New-Object Windows.Forms.Label
    $script:InstallPathLabel.Text = "安装路径：" + $InstallRoot
    $script:InstallPathLabel.ForeColor = [Drawing.Color]::DarkCyan
    $script:InstallPathLabel.SetBounds(30,66,560,24)
    $script:ProgressForm.Controls.Add($script:InstallPathLabel)
    $script:SizeLabel = New-Object Windows.Forms.Label
    $script:SizeLabel.Text = Get-ProjectSizeText $installMode
    $script:SizeLabel.ForeColor = [Drawing.Color]::DarkCyan
    $script:SizeLabel.SetBounds(30,96,560,24)
    $script:ProgressForm.Controls.Add($script:SizeLabel)
    $script:ProgressLabel.SetBounds(30,128,560,26)
    $script:ProgressForm.Controls.Add($script:ProgressLabel)
    $script:ProgressBar = New-Object Windows.Forms.ProgressBar
    $script:ProgressBar.Minimum = 0
    $script:ProgressBar.Maximum = 100
    $script:ProgressBar.Value = 0
    $script:ProgressBar.Style = "Continuous"
    $script:ProgressBar.SetBounds(30,158,560,28)
    $script:ProgressForm.Controls.Add($script:ProgressBar)
    $script:TimeLabel = New-Object Windows.Forms.Label
    $script:TimeLabel.Text = "已耗时：00:00"
    $script:TimeLabel.SetBounds(30,196,260,25)
    $script:ProgressForm.Controls.Add($script:TimeLabel)
    $script:DownloadLabel = New-Object Windows.Forms.Label
    $script:DownloadLabel.Text = "当前处理：等待开始"
    $script:DownloadLabel.ForeColor = [Drawing.Color]::RoyalBlue
    $script:DownloadLabel.SetBounds(30,224,560,25)
    $script:ProgressForm.Controls.Add($script:DownloadLabel)
    $script:LogBox = New-Object Windows.Forms.TextBox
    $script:LogBox.Multiline = $true
    $script:LogBox.ReadOnly = $true
    $script:LogBox.ScrollBars = "Vertical"
    $script:LogBox.SetBounds(30,256,560,119)
    $script:ProgressForm.Controls.Add($script:LogBox)
    $notice = New-Object Windows.Forms.Label
    $notice.Text = if ($installMode -eq "api") {
        "API 模式仅安装便携运行环境，不下载本地模型；需要稳定网络。"
    } else {
        "网络速度和硬盘性能会影响实际安装时间。"
    }
    $notice.SetBounds(30,388,560,24)
    $script:ProgressForm.Controls.Add($notice)
    $script:InstallStopwatch = [Diagnostics.Stopwatch]::StartNew()
    $script:UiTimer = New-Object Windows.Forms.Timer
    $script:UiTimer.Interval = 500
    $script:UiTimer.Add_Tick({
        $elapsed = $script:InstallStopwatch.Elapsed
        $script:TimeLabel.Text = "已耗时：{0:00}:{1:00}" -f [int]$elapsed.TotalMinutes,$elapsed.Seconds
        $script:ActivityDots = ($script:ActivityDots + 1) % 4
        if ($script:DownloadLabel.Tag) {
            $script:DownloadLabel.Text = "当前处理：" + $script:DownloadLabel.Tag + ("." * $script:ActivityDots)
        }
    })
    $script:UiTimer.Start()
    $script:ProgressForm.Show()
    [Windows.Forms.Application]::DoEvents()
}

function Set-Activity([string]$Message) {
    Set-DownloadInfo $Message
}

function Update-Progress([string]$Message, [int]$Percent) {
    if (-not $script:ProgressForm) { return }
    $script:ProgressLabel.Text = "$Message  （$Percent%）"
    if ($Percent -lt 0) { $Percent = 0 }
    if ($Percent -gt 100) { $Percent = 100 }
    $script:ProgressBar.Value = $Percent
    $script:LogBox.AppendText("[$(Get-Date -Format HH:mm:ss)] $Message" + [Environment]::NewLine)
    $script:LogBox.SelectionStart = $script:LogBox.TextLength
    $script:LogBox.ScrollToCaret()
    [Windows.Forms.Application]::DoEvents()
}

function Run-External([string]$FilePath, [string]$Arguments, [string]$FailureMessage, [string]$MonitorPath = "", [string]$MonitorLabel = "") {
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "$FailureMessage：找不到要启动的文件 $FilePath"
    }
    $activity = ($FailureMessage -replace '(?i)failed','' -replace '失败','').Trim(" ","：",":")
    if (-not $activity) { $activity = "运行 " + [IO.Path]::GetFileName($FilePath) }
    Set-Activity $activity
    if ($MonitorLabel) { Set-DownloadInfo ($MonitorLabel + "：安装组件正在处理，耗时取决于网络和硬盘") }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw "$FailureMessage (process did not start)" }
    while (-not $process.HasExited) {
        if (-not $Unattended) { [Windows.Forms.Application]::DoEvents() }
        if ($script:CancelRequested) {
            try { $process.Kill() } catch {}
            throw "用户取消了安装"
        }
        Start-Sleep -Milliseconds 150
    }
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    $process.Dispose()
    if ($exitCode -ne 0) { throw "$FailureMessage (exit code $exitCode)" }
}

function Select-InstallMode {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object Windows.Forms.Form
    $form.Text = "PDF2Markdown v0 安装程序"
    $form.Size = New-Object Drawing.Size(640,660)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $true
    $form.ControlBox = $true
    $form.ShowInTaskbar = $true
    $form.Add_Activated({
        param($sender,$eventArgs)
        if ($sender.WindowState -eq [Windows.Forms.FormWindowState]::Minimized) {
            $sender.WindowState = [Windows.Forms.FormWindowState]::Normal
            $sender.BringToFront()
        }
    })

    $title = New-Object Windows.Forms.Label
    $title.Text = "选择安装模式"
    $title.Font = New-Object Drawing.Font -ArgumentList @("Microsoft YaHei UI",18,[Drawing.FontStyle]::Bold)
    $title.SetBounds(28,20,520,42)
    $form.Controls.Add($title)

    $local = New-Object Windows.Forms.RadioButton
    $local.Text = "本地模型（高准确、离线；体积大、速度较慢）"
    $local.Checked = $true
    $local.Font = New-Object Drawing.Font -ArgumentList @("Microsoft YaHei UI",11,[Drawing.FontStyle]::Bold)
    $local.SetBounds(34,82,540,32)
    $form.Controls.Add($local)
    $localInfo = New-Object Windows.Forms.Label
    $localInfo.Text = "适合长期反复使用和不想上传论文的场景；需要 NVIDIA 显卡，首次安装下载较大。"
    $localInfo.SetBounds(58,116,520,42)
    $form.Controls.Add($localInfo)
    $gpu = New-Object Windows.Forms.Label
    $gpu.Text = "检测到 GPU：" + (Get-GpuInfo)
    $gpu.ForeColor = [Drawing.Color]::DarkCyan
    $gpu.SetBounds(58,158,520,26)
    $form.Controls.Add($gpu)
    $localPathLabel = New-Object Windows.Forms.Label
    $localPathLabel.Text = "本地模式路径：" + (Join-Path (Get-DownloadsFolder) "PDF2Markdown_Local")
    $localPathLabel.SetBounds(58,186,520,24)
    $form.Controls.Add($localPathLabel)
    $localSizeLabel = New-Object Windows.Forms.Label
    $localSizeLabel.Text = Get-ProjectSizeText "local"
    $localSizeLabel.ForeColor = [Drawing.Color]::DarkSlateGray
    $localSizeLabel.SetBounds(58,218,520,24)
    $form.Controls.Add($localSizeLabel)

    $api = New-Object Windows.Forms.RadioButton
    $api.Text = "MinerU API（快速、轻量；联网，准确性可能有瑕疵）"
    $api.Font = New-Object Drawing.Font -ArgumentList @("Microsoft YaHei UI",11,[Drawing.FontStyle]::Bold)
    $api.SetBounds(34,252,540,32)
    $form.Controls.Add($api)
    $apiInfo = New-Object Windows.Forms.Label
    $apiInfo.Text = "适合快速转换和轻量分发；PDF会上传到 MinerU 服务端，结果仍整理为本项目的 Markdown 输出。"
    $apiInfo.SetBounds(58,286,520,42)
    $form.Controls.Add($apiInfo)
    $apiPathLabel = New-Object Windows.Forms.Label
    $apiPathLabel.Text = "API模式路径：" + (Join-Path (Get-DownloadsFolder) "PDF2Markdown_API")
    $apiPathLabel.SetBounds(58,330,520,24)
    $form.Controls.Add($apiPathLabel)
    $apiSizeLabel = New-Object Windows.Forms.Label
    $apiSizeLabel.Text = Get-ProjectSizeText "api"
    $apiSizeLabel.ForeColor = [Drawing.Color]::DarkSlateGray
    $apiSizeLabel.SetBounds(58,358,520,24)
    $form.Controls.Add($apiSizeLabel)

    $keyLabel = New-Object Windows.Forms.Label
    $keyLabel.Text = "MinerU API Token"
    $keyLabel.Enabled = $false
    $keyLabel.SetBounds(58,390,140,24)
    $form.Controls.Add($keyLabel)
    $key = New-Object Windows.Forms.TextBox
    $key.Enabled = $false
    $key.UseSystemPasswordChar = $true
    $key.SetBounds(58,416,520,28)
    $form.Controls.Add($key)
    $apiHelp = New-Object Windows.Forms.TextBox
    $apiHelp.Multiline = $true
    $apiHelp.ReadOnly = $true
    $apiHelp.BorderStyle = "None"
    $apiHelp.BackColor = $form.BackColor
    $apiHelp.Text = "API Key 获取：" + [Environment]::NewLine +
        "1. 登录 https://mineru.net/ 并注册账号。" + [Environment]::NewLine +
        "2. 点击 API/API管理 - 创建Token - 复制备用。" + [Environment]::NewLine +
        "以后换Token：在项目 tool_v0\.runtime-home\api 中重新配置。"
    $apiHelp.ForeColor = [Drawing.Color]::DimGray
    $apiHelp.Enabled = $false
    $apiHelp.SetBounds(58,448,520,64)
    $form.Controls.Add($apiHelp)

    $note = New-Object Windows.Forms.Label
    $note.Text = "两种模式可同时安装，目录、配置、缓存和输出互不影响。"
    $note.ForeColor = [Drawing.Color]::DarkCyan
    $note.SetBounds(58,512,520,26)
    $form.Controls.Add($note)

    $install = New-Object Windows.Forms.Button
    $install.Text = "安装本地模式"
    $install.SetBounds(382,580,120,34)
    $form.AcceptButton = $install
    $form.Controls.Add($install)
    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = "取消"
    $cancel.SetBounds(510,580,70,34)
    $cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.CancelButton = $cancel
    $form.Controls.Add($cancel)

    $updateMode = {
        $isApi = $api.Checked
        $key.Enabled = $isApi
        $keyLabel.Enabled = $isApi
        $apiHelp.Enabled = $isApi
        $gpu.Visible = -not $isApi
        $install.Text = if ($isApi) { "安装 API 模式" } else { "安装本地模式" }
    }
    $local.Add_CheckedChanged($updateMode)
    $api.Add_CheckedChanged($updateMode)
    $install.Add_Click({
        if ($api.Checked -and [string]::IsNullOrWhiteSpace($key.Text)) {
            [Windows.Forms.MessageBox]::Show(
                "请输入在 MinerU API 管理页面创建的精准解析 Token。",
                "缺少 API Token",
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Warning
            ) | Out-Null
            $key.Focus()
            return
        }
        $form.Tag = @{
            mode = if ($api.Checked) { "api" } else { "local" }
            api_key = if ($api.Checked) { $key.Text.Trim() } else { "" }
        }
        $form.DialogResult = [Windows.Forms.DialogResult]::OK
        $form.Close()
    })
    & $updateMode
    if ($form.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { return $null }
    return $form.Tag
}

function Get-DownloadsFolder {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    $valueName = "{374DE290-123F-4565-9164-39C4925E467B}"
    try {
        $raw = (Get-ItemProperty -LiteralPath $key -Name $valueName -ErrorAction Stop).$valueName
        return [Environment]::ExpandEnvironmentVariables($raw)
    }
    catch {
        return (Join-Path $env:USERPROFILE "Downloads")
    }
}

function Step([string]$Message) {
    Write-Host ""
    Write-Host ("=" * 68) -ForegroundColor DarkCyan
    Write-Host $Message -ForegroundColor Cyan
    $percent = 0
    if ($Message -match '^(\d+)/(\d+)') {
        $percent = [int]((([int]$Matches[1] - 1) * 100) / [int]$Matches[2])
        if ($percent -gt 95) { $percent = 95 }
    }
    Update-Progress $Message $percent
    Set-Activity $Message
}
function Download([string]$Url, [string]$Destination) {
    Write-Host "Downloading: $Url"
    $name = [IO.Path]::GetFileName($Destination)
    Set-Activity ("下载 " + $name)
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $response = $request.GetResponse()
    $targetBytes = [double]$response.ContentLength
    $targetText = if ($targetBytes -gt 0) { Format-Bytes $targetBytes } else { "未知" }
    $inputStream = $response.GetResponseStream()
    $outputStream = $null
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            $outputStream = [IO.File]::Open($Destination, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
            break
        }
        catch [System.IO.IOException] {
            if ($attempt -eq 20) { throw }
            Set-Activity ("等待文件释放：" + $name)
            Set-DownloadInfo ($name + "，目标大小：" + $targetText + "，等待系统释放临时文件")
            Start-Sleep -Milliseconds 500
            if (-not $Unattended) { [Windows.Forms.Application]::DoEvents() }
        }
    }
    $buffer = New-Object byte[] (1024 * 128)
    $downloaded = [double]0
    $lastDownloaded = [double]0
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        Set-DownloadInfo ($name + "，目标大小：" + $targetText + "，网速：计算中")
        while (($read = $inputStream.Read($buffer,0,$buffer.Length)) -gt 0) {
            $outputStream.Write($buffer,0,$read)
            $downloaded += [double]$read
            if ($script:CancelRequested) { throw "用户取消了安装" }
            if (-not $Unattended -and $timer.ElapsedMilliseconds -ge 700) {
                $elapsedSeconds = [double]$timer.Elapsed.TotalSeconds
                if ($elapsedSeconds -le 0) { $elapsedSeconds = 0.1 }
                $speed = ($downloaded - $lastDownloaded) / $elapsedSeconds
                if ($speed -lt 0) { $speed = 0 }
                Set-Activity ("下载 " + $name)
                Set-DownloadInfo ($name + "，目标大小：" + $targetText + "，网速：" + (Format-Bytes $speed) + "/s")
                $lastDownloaded = $downloaded
                $timer.Restart()
                [Windows.Forms.Application]::DoEvents()
            }
        }
    }
    finally {
        if ($outputStream) { $outputStream.Dispose() }
        $inputStream.Dispose()
        $response.Dispose()
    }
    Set-Activity ("下载 " + $name + " 完成")
    Set-DownloadInfo ($name + "，目标大小：" + $targetText + "，已完成")
}

try {
    $selection = if ($Unattended) { @{ mode = "local"; api_key = "" } } else { Select-InstallMode }
    if (-not $selection) { Write-Host "Installation cancelled."; exit 0 }
    $installMode = $selection.mode
    if ($installMode -notin @("local","api")) { throw "未知安装模式：$installMode" }
    $mutexCreated = $false
    $mutexName = if ($installMode -eq "local") { "Local\PDF2Markdown_Installer_Local" } else { "Local\PDF2Markdown_Installer_API" }
    $script:InstallerMutex = New-Object System.Threading.Mutex($true,$mutexName,[ref]$mutexCreated)
    if (-not $mutexCreated) {
        if (-not $Unattended) {
            [Windows.Forms.MessageBox]::Show(
                $(if ($installMode -eq "api") { "PDF2Markdown API安装程序已经在运行，本次不会重复启动。" } else { "PDF2Markdown本地安装程序已经在运行，本次不会重复启动。" }),
                "安装程序已运行",
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
        }
        exit 0
    }
    $downloadsFolder = [IO.Path]::GetFullPath((Get-DownloadsFolder)).TrimEnd("\")
    $projectFolder = if ($installMode -eq "api") { "PDF2Markdown_API" } else { "PDF2Markdown_Local" }
    $InstallRoot = if ($Unattended -and $TestInstallRoot) {
        [IO.Path]::GetFullPath($TestInstallRoot)
    } else {
        [IO.Path]::GetFullPath((Join-Path $downloadsFolder $projectFolder))
    }
    if (Test-Path -LiteralPath $InstallRoot) {
        $toolCandidates = Get-ChildItem -LiteralPath $InstallRoot -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^tool(?:_v\d+)?$' }
        if ($toolCandidates) {
            $toolSummary = "发现程序目录：" + (($toolCandidates | Select-Object -ExpandProperty Name) -join "、")
            Add-Type -AssemblyName System.Windows.Forms
            $message = "检测到下载目录中已经存在$projectFolder。" + [Environment]::NewLine +
                   $toolSummary + [Environment]::NewLine + [Environment]::NewLine +
                   "是否删除旧程序并重新安装？" + [Environment]::NewLine + [Environment]::NewLine +
                   "input和output文件夹及其中内容会完整保留。" + [Environment]::NewLine +
                   $(if ($installMode -eq "api") { "本地模型分支不受影响。" } else { "MinerU API分支不受影响。" })
            $answer = if ($Unattended) {
            [Windows.Forms.DialogResult]::Yes
            } else {
            [Windows.Forms.MessageBox]::Show($message,"重新安装",[Windows.Forms.MessageBoxButtons]::YesNo,[Windows.Forms.MessageBoxIcon]::Warning)
            }
            if ($answer -ne [Windows.Forms.DialogResult]::Yes) {
            exit 0
            }
            if (-not $Unattended) {
            Show-ProgressWindow
            Update-Progress "准备重新安装" 0
            Set-Activity "清理旧程序，保留input和output"
            }
            $actualParent = [IO.Path]::GetFullPath((Split-Path -Parent $InstallRoot)).TrimEnd("\")
            if ((-not $Unattended) -and (($actualParent -ne $downloadsFolder) -or ((Split-Path -Leaf $InstallRoot) -ne $projectFolder))) {
            throw "安全检查失败：拒绝删除非预期目录。"
            }
            $cleanupScript = Join-Path $env:TEMP ("pdf2markdown-clean-old-{0}-{1}.ps1" -f $installMode,$PID)
        @'
param([string]$Root)
$ErrorActionPreference = "Stop"
Get-ChildItem -LiteralPath $Root -Force | Where-Object {
    $_.Name -notin @("input","output")
} | Remove-Item -Recurse -Force
'@ | Set-Content -LiteralPath $cleanupScript -Encoding UTF8
            $cleanupPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
            $cleanupArguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " + [char]34 + $cleanupScript + [char]34 + " -Root " + [char]34 + $InstallRoot + [char]34
            Run-External $cleanupPowerShell $cleanupArguments "清理旧程序失败"
            Remove-Item -LiteralPath $cleanupScript -Force -ErrorAction SilentlyContinue
        }
    }
    if ((-not $Unattended) -and (-not $script:ProgressForm)) { Show-ProgressWindow }
    $totalSteps = if ($installMode -eq "api") { 5 } else { 7 }
    Step "1/$totalSteps  检查Windows、运行条件和磁盘空间"
    if (-not [Environment]::Is64BitOperatingSystem) { throw "64-bit Windows is required." }
    if ($installMode -eq "local") {
        $nvidia = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
        if (-not $nvidia) {
            $candidate = Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"
            if (Test-Path $candidate) { $nvidia = $candidate }
        }
        if (-not $nvidia) { throw "NVIDIA driver was not detected." }
        & $nvidia --query-gpu=name,memory.total,driver_version --format=csv,noheader
    }
    $driveName = ([IO.Path]::GetPathRoot($InstallRoot)).TrimEnd(":\")
    $requiredSpace = if ($installMode -eq "api") { 2GB } else { 12GB }
    if ((Get-PSDrive -Name $driveName).Free -lt $requiredSpace) { throw "可用磁盘空间不足。" }

    Step "2/$totalSteps  创建input、output和tool_v0"
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $payload = Join-Path $PSScriptRoot "payload.zip"
    if (-not (Test-Path $payload)) { throw "payload.zip is missing." }
    Expand-Archive -LiteralPath $payload -DestinationPath $InstallRoot -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot "input"),(Join-Path $InstallRoot "output") | Out-Null
    $tool = Join-Path $InstallRoot "tool_v0"
    if ($installMode -eq "api") {
        Remove-Item -LiteralPath (Join-Path $tool "run_local.cmd") -Force -ErrorAction SilentlyContinue
    } else {
        Remove-Item -LiteralPath (Join-Path $tool "run_api.cmd") -Force -ErrorAction SilentlyContinue
    }
    Stamp-ReadmeMode $InstallRoot $installMode
    Write-Utf8NoBom (Join-Path $tool "installation-mode.json") (@{
        schema_version = 1
        mode = $installMode
        provider = if ($installMode -eq "api") { "mineru-api" } else { "mineru-local" }
        api = @{
            enabled = ($installMode -eq "api")
            provider = "mineru-api"
            base_url = "https://mineru.net/api/v4"
            credential_storage = "windows-dpapi"
        }
    } | ConvertTo-Json -Depth 5)
    $pythonHome = Join-Path $tool ".python"
    $tempPrefix = "pdf2markdown-{0}-{1}" -f $installMode,$PID
    $pythonArchive = Join-Path $env:TEMP ($tempPrefix + "-python-3.12.10-embed-amd64.zip")
    $getPip = Join-Path $env:TEMP ($tempPrefix + "-get-pip.py")

    Step "3/$totalSteps  安装便携Python 3.12"
    if (-not (Test-Path (Join-Path $pythonHome "python.exe"))) {
        Download "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" $pythonArchive
        New-Item -ItemType Directory -Force -Path $pythonHome | Out-Null
        Expand-Archive -LiteralPath $pythonArchive -DestinationPath $pythonHome -Force
        $pth = Join-Path $pythonHome "python312._pth"
        $pthText = Get-Content -LiteralPath $pth -Raw
        $pthText = $pthText.Replace("#import site","import site")
        if ($pthText -notmatch '(?m)^\.\.$') {
            $pthText = $pthText.TrimEnd() + [Environment]::NewLine + ".." + [Environment]::NewLine
        }
        Set-Content -LiteralPath $pth -Value $pthText -Encoding ASCII
    }
    $python = Join-Path $pythonHome "python.exe"
    if (-not (Test-Path -LiteralPath $python)) { throw "便携Python解压失败：找不到 $python" }
    if (-not (Test-Path -LiteralPath (Join-Path $pythonHome "Scripts\pip.exe"))) {
        Download "https://bootstrap.pypa.io/get-pip.py" $getPip
        Run-External $python ([char]34 + $getPip + [char]34) "安装pip失败"
    }

    if ($installMode -eq "local") {
        Step "4/7  下载并安装PyTorch CUDA"
        Run-External $python "-m pip --disable-pip-version-check --no-input install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128" "安装PyTorch CUDA失败" $pythonHome "PyTorch CUDA组件"

        Step "5/7  安装MinerU VLM与转换组件"
        Run-External $python '-m pip install "mineru[vlm]==3.4.2" "transformers==4.57.6"' "安装MinerU VLM失败" $pythonHome "MinerU与依赖组件"
        Run-External $python "-m pip install pdfplumber pypdf pillow requests httpx rich" "安装转换组件失败" $pythonHome "Markdown转换组件"

        Step "6/7  下载MinerU VLM模型（约2.2 GB）"
        $modelCache = Join-Path $tool ".models\modelscope"
        New-Item -ItemType Directory -Force -Path $modelCache | Out-Null
        $env:MODELSCOPE_CACHE = $modelCache
        $env:MODELSCOPE_HOME = $modelCache
        $modelPathFile = Join-Path $env:TEMP ($tempPrefix + "-model-path.txt")
        $downloadScript = Join-Path $env:TEMP ($tempPrefix + "-download-model.py")
    @'
import sys
from pathlib import Path
from modelscope import snapshot_download
model_path = snapshot_download("OpenDataLab/MinerU2.5-Pro-2605-1.2B", cache_dir=sys.argv[1])
Path(sys.argv[2]).write_text(model_path, encoding="utf-8")
print(model_path)
'@ | Set-Content -LiteralPath $downloadScript -Encoding ASCII
        $downloadArguments = ([char]34 + $downloadScript + [char]34 + " " + [char]34 + $modelCache + [char]34 + " " + [char]34 + $modelPathFile + [char]34)
        Run-External $python $downloadArguments "下载MinerU VLM模型失败" $modelCache "MinerU VLM模型"
        Remove-Item -LiteralPath $downloadScript -Force -ErrorAction SilentlyContinue
        $modelPath = (Get-Content -LiteralPath $modelPathFile -Raw -Encoding UTF8).Trim()
        Remove-Item -LiteralPath $modelPathFile -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path (Join-Path $modelPath "model.safetensors"))) { throw "Downloaded model is incomplete." }

        $runtimeHome = Join-Path $tool ".runtime-home"
        New-Item -ItemType Directory -Force -Path $runtimeHome | Out-Null
        $config = @{
            "latex-delimiter-config" = @{ display = @{left='$$';right='$$'}; inline = @{left='$';right='$'} }
            "models-dir" = @{ vlm = $modelPath }
            "model-source" = "modelscope"
            "config_version" = "1.3.2"
        }
        Write-Utf8NoBom (Join-Path $runtimeHome "mineru.json") ($config | ConvertTo-Json -Depth 6)
        Step "7/7  精简运行环境并创建启动入口"
    } else {
        Step "4/5  安装API转换组件并保存Token"
        Run-External $python "-m pip --disable-pip-version-check --no-input install pdfplumber pypdf pillow requests httpx rich" "安装API转换组件失败" $pythonHome "API转换组件"
        $oldPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = $tool
            $env:PDF2MD_BOOTSTRAP_TOKEN = $selection.api_key
            Run-External $python "-m converter_core.credentials from-env" "保存MinerU API Token失败"
        }
        finally {
            Remove-Item Env:\PDF2MD_BOOTSTRAP_TOKEN -ErrorAction SilentlyContinue
            $env:PYTHONPATH = $oldPythonPath
        }
        Step "5/5  精简运行环境并创建启动入口"
    }

    Get-ChildItem -LiteralPath $pythonHome -Recurse -File -Filter "*.lib" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    $launcherName = if ($installMode -eq "api") { "PDF2Markdown_API.cmd" } else { "PDF2Markdown_Local.cmd" }
    $toolLauncher = if ($installMode -eq "api") { "run_api.cmd" } else { "run_local.cmd" }
    $launcher = Join-Path $InstallRoot $launcherName
    $launcherLines = @(
        "@echo off",
        "chcp 65001 >nul",
        'cd /d "%~dp0"',
        ('call ".\tool_v0\' + $toolLauncher + '"')
    )
    Set-Content -LiteralPath $launcher -Value $launcherLines -Encoding ASCII
    Remove-Item -LiteralPath $pythonArchive,$getPip -Force -ErrorAction SilentlyContinue
    Update-Progress "安装完成" 100
    $script:AllowProgressClose = $true
    Write-Host "Installation completed: $InstallRoot" -ForegroundColor Green
    $doneMessage = "安装完成！" + [Environment]::NewLine + [Environment]::NewLine + "把PDF放入input文件夹，然后双击项目根目录中的$launcherName。"
    if (-not $Unattended) {
        [Windows.Forms.MessageBox]::Show($doneMessage,"安装完成",[Windows.Forms.MessageBoxButtons]::OK,[Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        Start-Process explorer.exe -ArgumentList $InstallRoot
    }
}
catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($script:ProgressForm) {
        Update-Progress "安装失败：$($_.Exception.Message)" $script:ProgressBar.Value
        [Windows.Forms.MessageBox]::Show(("安装失败：" + [Environment]::NewLine + [Environment]::NewLine + $_.Exception.Message),"安装失败",[Windows.Forms.MessageBoxButtons]::OK,[Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }
    exit 1
}
finally {
    if ($script:UiTimer) { $script:UiTimer.Stop() }
    if ($script:InstallStopwatch) { $script:InstallStopwatch.Stop() }
    $script:AllowProgressClose = $true
    if ($script:ProgressForm) { $script:ProgressForm.Close() }
    if ($script:InstallerMutex) {
        try { $script:InstallerMutex.ReleaseMutex() } catch {}
        $script:InstallerMutex.Dispose()
    }
}
















