
# ==========================================
# 実験用サーバー監視スクリプト
# ==========================================

$backendDir = "D:\GithubProjects\running-support-app\backend"

$pythonExe = "C:\Users\satou\anaconda3\envs\running-osmnx\python.exe"

$ngrokExe = "C:\Users\satou\AppData\Local\Microsoft\WindowsApps\ngrok.exe"

$ngrokDomain = "difficult-comply-unchain.ngrok-free.dev"

# 監視間隔：10秒
$checkInterval = 10

function Start-FastAPI {
    Write-Host "[FastAPI] Starting..."

    return Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @(
            "-m", "uvicorn",
            "app.main:app",
            "--reload",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--no-access-log"
        ) `
        -WorkingDirectory $backendDir `
        -PassThru
}

function Start-Ngrok {
    Write-Host "[ngrok] Starting..."

    return Start-Process `
        -FilePath $ngrokExe `
        -ArgumentList @(
            "http", "8000",
            "--url", $ngrokDomain,
            "--inspect=false"
        ) `
        -WorkingDirectory $backendDir `
        -PassThru
}

# 初回起動
$fastapiProcess = Start-FastAPI
$ngrokProcess = Start-Ngrok

Write-Host "=== Server monitoring started ==="

while ($true) {
    Start-Sleep -Seconds $checkInterval

    $fastapiProcess.Refresh()
    $ngrokProcess.Refresh()

    if ($fastapiProcess.HasExited) {
        Write-Host "[FastAPI] Process stopped. Restarting..."

        $fastapiProcess = Start-FastAPI
    }

    if ($ngrokProcess.HasExited) {
        Write-Host "[ngrok] Process stopped. Restarting..."

        $ngrokProcess = Start-Ngrok
    }
}
