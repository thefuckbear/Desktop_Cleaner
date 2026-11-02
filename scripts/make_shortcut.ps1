# 创建桌面快捷方式（只新建，绝不覆盖/删除桌面已有文件）
# 用法: pwsh -File scripts\make_shortcut.ps1 [-DryRun]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$root      = Split-Path -Parent $PSScriptRoot
$launcher  = Join-Path $root 'scripts\launch_gui.pyw'
$icon      = Join-Path $root 'assets\icon.ico'
$pythonw   = 'C:\Python313\pythonw.exe'
$desktop   = [Environment]::GetFolderPath('Desktop')
$lnkName   = 'Desktop Organizer.lnk'
$lnkPath   = Join-Path $desktop $lnkName

Write-Output "root      : $root"
Write-Output "launcher  : $launcher"
Write-Output "icon      : $icon"
Write-Output "pythonw   : $pythonw"
Write-Output "desktop   : $desktop"
Write-Output "target lnk: $lnkPath"

if (-not (Test-Path $pythonw)) { throw "找不到 pythonw.exe: $pythonw" }
if (-not (Test-Path $launcher)) { throw "找不到启动器: $launcher" }
if (-not (Test-Path $icon)) { throw "找不到图标: $icon" }

# 铁律：桌面已有同名文件则绝不覆盖，改为带序号的新名字
if (Test-Path $lnkPath) {
    $i = 2
    do {
        $lnkName = "Desktop Organizer ($i).lnk"
        $lnkPath = Join-Path $desktop $lnkName
        $i++
    } while ((Test-Path $lnkPath) -and $i -lt 100)
    Write-Output "同名已存在，改用: $lnkName"
}

if ($DryRun) {
    Write-Output "[DryRun] 将创建: $lnkPath"
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath       = $pythonw
$sc.Arguments        = '"' + $launcher + '"'
$sc.WorkingDirectory = $root
$sc.IconLocation     = $icon + ',0'
$sc.Description      = 'Desktop Organizer — AI 给建议，人拍板，可回滚的桌面整理工具'
$sc.WindowStyle      = 1
$sc.Save()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($sc) | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null

if (Test-Path $lnkPath) {
    $fi = Get-Item $lnkPath
    Write-Output "OK 已创建: $($fi.FullName)  ($($fi.Length) bytes)"
} else {
    throw "快捷方式创建失败"
}
