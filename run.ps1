# ReNU アプリ起動（Python 3.13・プロジェクトルートで -m app.main）
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }
Set-Location $root
$py = "C:\Users\yutok\AppData\Local\Programs\Python\Python313\python.exe"
# 無効な PYTHONWARNINGS が親プロセスで設定されていると "Invalid -W option" が出るため、
# cmd の子プロセスで未設定にしてから Python を起動する
cmd /c "set PYTHONWARNINGS= && `"$py`" -m app.main"
