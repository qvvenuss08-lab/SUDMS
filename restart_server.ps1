$ErrorActionPreference = 'Stop'
$sudmsRoot = $env:SUDMS_RESTART_ROOT
if (-not $sudmsRoot) { throw 'SUDMS project directory is missing.' }
# ตรวจโปรแกรมที่เปิดพอร์ตจริง ปิดเฉพาะ Python ที่ให้บริการหน้า SUDMS
$sudmsListeners = @(Get-NetTCPConnection -LocalPort 5056 -State Listen -ErrorAction SilentlyContinue)
foreach ($sudmsListener in $sudmsListeners) {
    $sudmsProcessId = [int]$sudmsListener.OwningProcess
    $sudmsProcess = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $sudmsProcessId)
    if (-not $sudmsProcess) { continue }
    if ($sudmsProcess.Name -notmatch '^python(w)?\.exe$' -or $sudmsProcess.CommandLine -notmatch '(app\.py|run_latest\.py|run_mobile\.py)') {
        throw 'Port 5056 belongs to a different program. It was not stopped.'
    }
    Add-Type -AssemblyName System.Net.Http
    $sudmsHttpHandler = New-Object System.Net.Http.HttpClientHandler
    $sudmsHttpHandler.UseProxy = $false
    $sudmsHttpClient = [System.Net.Http.HttpClient]::new($sudmsHttpHandler)
    $sudmsHttpClient.Timeout = [TimeSpan]::FromSeconds(8)
    try {
        $sudmsLoginHtml = $sudmsHttpClient.GetStringAsync('http://127.0.0.1:5056/login').GetAwaiter().GetResult()
        if (-not $sudmsLoginHtml.Contains('SUDMS')) { throw 'The running website is not SUDMS. It was not stopped.' }
    } finally {
        $sudmsHttpClient.Dispose()
    }
    # รวมตัวควบคุม reloader/venv ที่เป็น Python ของแอปเดียวกัน เพื่อไม่ให้รันรุ่นเก่าขึ้นมาอีก
    $sudmsRootProcess = $sudmsProcess
    for ($sudmsDepth=0; $sudmsDepth -lt 5; $sudmsDepth++) {
        $sudmsParent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $sudmsRootProcess.ParentProcessId)
        if (-not $sudmsParent -or $sudmsParent.Name -notmatch '^python(w)?\.exe$' -or $sudmsParent.CommandLine -notmatch '(app\.py|run_latest\.py|run_mobile\.py)') { break }
        $sudmsRootProcess = $sudmsParent
    }
    $sudmsCurrent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $sudmsRootProcess.ProcessId)
    if ($sudmsCurrent -and $sudmsCurrent.CreationDate -eq $sudmsRootProcess.CreationDate) {
        Write-Host ('Stopping confirmed SUDMS server process ' + $sudmsRootProcess.ProcessId)
        & taskkill.exe /PID $sudmsRootProcess.ProcessId /T /F
    }
}
for ($sudmsWait=0; $sudmsWait -lt 25; $sudmsWait++) {
    if (-not (Get-NetTCPConnection -LocalPort 5056 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 200
}
if (Get-NetTCPConnection -LocalPort 5056 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 5056 is still occupied. The new server was not started.' }
Write-Host 'Port 5056 is free. Starting SUDMS from the current project source.'
