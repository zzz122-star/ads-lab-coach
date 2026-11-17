param([ValidateSet('start','stop')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
try {
    $candidates = @(
        (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe')
    )
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidates += $pythonCommand.Source }
    $pythonPath = $null
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            & $candidate -c 'import streamlit, yaml' 2>$null
            if ($LASTEXITCODE -eq 0) { $pythonPath = $candidate; break }
        }
    }
    if (-not $pythonPath) { throw '未找到安装了 Streamlit 的 Python。请先安装 requirements.txt 中的依赖。' }
    & $pythonPath (Join-Path $PSScriptRoot 'launcher.py') $Action
    if ($LASTEXITCODE -ne 0) { throw '启动或停止失败，请查看 ads-lab-coach\data 中的日志。' }
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'ADS 实验陪练') | Out-Null
    exit 1
}
