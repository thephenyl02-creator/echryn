param(
    [string]$Url = "https://www.instagram.com/reel/Dd10cOlujGD/",
    [switch]$NonMultimodal
)

$ErrorActionPreference = "Stop"

$headers = @{
    "X-API-Key" = "change-me"
}

$body = @{
    url = $Url
    mode = "evidence"
    multimodal = (-not $NonMultimodal)
    force_refresh = $true
} | ConvertTo-Json -Compress

$result = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8080/v1/extractions/sync" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body

# Keep the latest response available in the caller's PowerShell session.
$global:EchrynResult = $result

Write-Host ""
Write-Host "status:" $result.status
Write-Host "multimodal:" $result.diagnostics.multimodal
Write-Host "sampled frames:" $result.media.sampled_frames
Write-Host "returned frames:" $result.visual.frames.Count
Write-Host ""

Write-Host "speech:"
$result.speech | ConvertTo-Json -Depth 20

Write-Host ""
Write-Host "provenance:"
$result.provenance | ConvertTo-Json -Depth 20
