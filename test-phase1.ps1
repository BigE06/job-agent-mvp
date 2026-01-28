$BaseUrl = "http://127.0.0.1:8000"
try {
    Write-Host "1. Root Check..." -NoNewline
    $r = Invoke-RestMethod "$BaseUrl/"
    Write-Host "OK" -ForegroundColor Green
    
    Write-Host "2. Importing Data..." -NoNewline
    $body = '[{"title":"Test Job","company":"Test Co","url":"http://test","status":"new"}]'
    $r = Invoke-RestMethod "$BaseUrl/jobs/import" -Method Post -Body $body -ContentType "application/json"
    Write-Host "OK ($($r.message))" -ForegroundColor Green

    Write-Host "3. Reading Data..." -NoNewline
    $jobs = Invoke-RestMethod "$BaseUrl/jobs"
    if ($jobs.Count -gt 0) { Write-Host "OK (Found $($jobs.Count))" -ForegroundColor Green }
    else { Write-Host "FAIL" -ForegroundColor Red }
} catch { Write-Host "Error: $_" -ForegroundColor Red }
