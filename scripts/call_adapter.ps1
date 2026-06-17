param(
  [string]$BaseUrl = "http://47.116.102.238:18080",
  [ValidateSet("preview", "execute", "status", "audit", "health")]
  [string]$Mode = "preview",
  [string]$TaskId = "manual-check-1",
  [string]$Operator = "admin",
  [string]$HostId = "host-47-116-102-238",
  [string]$ApprovalId = "",
  [string]$TokenPath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $TokenPath) {
  $TokenPath = Join-Path $root "secrets\adapter_api_token.txt"
}

function Get-AdapterHeaders {
  if (-not (Test-Path -LiteralPath $TokenPath)) {
    throw "Token file not found: $TokenPath"
  }
  $token = (Get-Content -Raw -LiteralPath $TokenPath).Trim()
  if (-not $token) {
    throw "Token file is empty: $TokenPath"
  }
  return @{ Authorization = "Bearer $token" }
}

if ($Mode -eq "health") {
  Invoke-RestMethod "$BaseUrl/health"
  return
}

$headers = Get-AdapterHeaders

if ($Mode -eq "status") {
  Invoke-RestMethod "$BaseUrl/adapter/status/$TaskId" -Headers $headers
  return
}

if ($Mode -eq "audit") {
  Invoke-RestMethod "$BaseUrl/adapter/audit/$TaskId" -Headers $headers
  return
}

$params = @{
  hostId = $HostId
  timeoutSeconds = 15
}

if ($Mode -eq "execute") {
  if ($ApprovalId) {
    $params.approvalId = $ApprovalId
  } else {
    $params.approved = $true
  }
}

$body = @{
  taskId = $TaskId
  operator = $Operator
  system = "ssh"
  action = "check_connectivity"
  env = "dev"
  params = $params
} | ConvertTo-Json -Depth 8 -Compress

Invoke-RestMethod "$BaseUrl/adapter/$Mode" `
  -Method POST `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
