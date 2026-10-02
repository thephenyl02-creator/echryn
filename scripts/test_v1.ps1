param(
    [string]$BaseUrl = "http://localhost:8080",
    [string]$ApiKey = "change-me",
    [string]$AnchorUrl = "https://www.instagram.com/reel/Dd10cOlujGD/",
    [string]$SpeechUrl = "https://www.instagram.com/reels/Dd66pE9PTIW/"
)

$ErrorActionPreference = "Stop"
$headers = @{ "X-API-Key" = $ApiKey }

function Invoke-EchrynExtraction {
    param(
        [string]$Url,
        [string]$Mode,
        [bool]$Multimodal,
        [string]$FrameDelivery = "urls",
        [bool]$ForceRefresh = $true
    )

    $body = @{
        url = $Url
        mode = $Mode
        multimodal = $Multimodal
        frame_delivery = $FrameDelivery
        force_refresh = $ForceRefresh
    } | ConvertTo-Json -Compress

    $params = @{
        Method = "Post"
        Uri = "$BaseUrl/v1/extractions/sync"
        Headers = $headers
        ContentType = "application/json"
        Body = $body
    }
    Invoke-RestMethod @params
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "V1 regression failed: $Message" }
}

Write-Host "1/6 health"
$health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/healthz"
Assert-True ($health.ok -eq $true) "healthz did not return ok=true"

Write-Host "2/6 metadata"
$metadata = Invoke-EchrynExtraction -Url $AnchorUrl -Mode "metadata" -Multimodal $false -FrameDelivery "none"
Assert-True ($metadata.status -eq "complete") "metadata extraction failed"
Assert-True ($metadata.visual.status -eq "skipped_by_policy") "metadata mode inspected visual media"

Write-Host "3/6 auto fallback + native resources"
$auto = Invoke-EchrynExtraction -Url $AnchorUrl -Mode "auto" -Multimodal $true -FrameDelivery "urls"
Assert-True ($auto.status -eq "complete") "auto extraction failed"
Assert-True ($auto.media.native_resources.status -in @("absent", "available")) "native resource inspection missing"
Assert-True ($auto.visual.frames.Count -gt 0) "auto fallback returned no frames"
Assert-True ($auto.visual.frames[0].delivery -eq "url") "auto frame delivery is not URL"

Write-Host "4/6 signed frame retrieval"
$tempFrame = Join-Path $env:TEMP "echryn-v1-regression.webp"
Invoke-WebRequest -Uri $auto.visual.frames[0].url -OutFile $tempFrame
$frameFile = Get-Item $tempFrame
Assert-True ($frameFile.Length -gt 0) "signed frame URL returned an empty file"
Remove-Item $tempFrame -Force

Write-Host "5/6 cache reuse"
$cached = Invoke-EchrynExtraction -Url $AnchorUrl -Mode "auto" -Multimodal $true -FrameDelivery "urls" -ForceRefresh $false
Assert-True ($cached.status -eq "complete") "cached extraction failed"
Assert-True ($cached.diagnostics.cached -eq $true) "compatible cached variant was not reused"
Assert-True ($cached.visual.frames[0].url -match "sig=") "cached frame URL was not re-signed"

Write-Host "6/6 real speech transcription"
$speech = Invoke-EchrynExtraction -Url $SpeechUrl -Mode "evidence" -Multimodal $true -FrameDelivery "urls"
Assert-True ($speech.status -eq "complete") "speaking Reel extraction failed"
Assert-True ($speech.speech.status -eq "available") "speaking Reel did not reach transcription"
Assert-True ($speech.speech.source -eq "faster_whisper") "speaking Reel did not use faster-whisper"
Assert-True (-not [string]::IsNullOrWhiteSpace($speech.speech.value.text)) "speech transcript is empty"

Write-Host ""
Write-Host "ECHRYN V1 REGRESSION: PASS"
Write-Host "metadata: PASS"
Write-Host "auto/native-resource gate: PASS"
Write-Host "signed frame delivery: PASS"
Write-Host "stable cache reuse: PASS"
Write-Host "speech transcription: PASS"
