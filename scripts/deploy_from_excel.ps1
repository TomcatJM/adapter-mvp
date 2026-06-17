param(
  [string]$Source = "D:\document\up\user-password.xls",
  [int]$Row = 2,
  [string]$RemoteDir = "/opt/adapter-mvp",
  [int]$Port = 18080
)

$ErrorActionPreference = "Stop"

function Read-HostRowFromExcel {
  param([string]$Path, [int]$RowNumber)

  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  try {
    $wb = $excel.Workbooks.Open($Path, $null, $true)
    $ws = $wb.Worksheets.Item(1)
    $headers = @{}
    $cols = $ws.UsedRange.Columns.Count
    for ($c=1; $c -le $cols; $c++) {
      $headers[[string]$ws.Cells.Item(1,$c).Text] = $c
    }
    $item = [ordered]@{
      platform = [string]$ws.Cells.Item($RowNumber, $headers["平台"]).Text
      ip = [string]$ws.Cells.Item($RowNumber, $headers["ip"]).Text
      account = [string]$ws.Cells.Item($RowNumber, $headers["账号"]).Text
    }
    return [pscustomobject]$item
  } finally {
    if ($wb) { $wb.Close($false) }
    $excel.Quit()
  }
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$hostItem = Read-HostRowFromExcel -Path $Source -RowNumber $Row

if (-not $hostItem.ip -or -not $hostItem.account) {
  throw "No ip/account found in $Source row $Row"
}

$package = Join-Path $root "adapter-mvp.tar.gz"
if (Test-Path $package) { Remove-Item $package -Force }

Push-Location $root
try {
  tar --exclude=".venv" --exclude="adapter-mvp.tar.gz" --exclude="secrets/*" --exclude="logs/*" -czf $package .
} finally {
  Pop-Location
}

$target = "$($hostItem.account)@$($hostItem.ip)"
Write-Host "Deploy target: $($hostItem.platform) $target"
Write-Host "Password is not printed. If SSH asks for password, type the password from the workbook."

ssh $target "mkdir -p $RemoteDir"
scp $package "${target}:$RemoteDir/adapter-mvp.tar.gz"
ssh $target "cd $RemoteDir && tar -xzf adapter-mvp.tar.gz && chmod +x scripts/remote_install.sh && APP_DIR=$RemoteDir PORT=$Port bash scripts/remote_install.sh"

Write-Host "Verifying health endpoint..."
try {
  Invoke-RestMethod "http://$($hostItem.ip):$Port/health"
} catch {
  Write-Warning "Service may be running but port $Port is not reachable from this machine. Check firewall/security group."
}
