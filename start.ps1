# 透明通道色块点击器 —— PowerShell 启动脚本（UTF-8 友好，中文不乱码）
# 用法：右键 → 使用 PowerShell 运行；或在 PowerShell 中执行 .\start.ps1

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  透明通道色块点击器" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

function Find-Python {
    foreach ($cand in @('py', 'python', 'python3')) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "[错误] 未找到 Python，请安装 Python 3.8+ 并加入 PATH" -ForegroundColor Red
    Write-Host "       下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}
Write-Host "使用解释器: $py" -ForegroundColor DarkGray

# 检查并安装依赖
& $py -c "import PyQt5" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[提示] 正在安装依赖 PyQt5 / Pillow / numpy ..." -ForegroundColor Yellow
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
}

& $py main.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 程序异常退出，请查看上方信息" -ForegroundColor Red
    Read-Host "按回车退出"
}
