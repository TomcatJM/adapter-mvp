import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "hosts.masked.json"


def slug_host(platform: str, ip: str) -> str:
    platform_slug = re.sub(r"[^a-zA-Z0-9]+", "-", platform).strip("-").lower() or "host"
    return f"{platform_slug}-{ip.replace('.', '-')}"


def read_xls_with_excel_com(source: Path) -> list[dict[str, str]]:
    ps = f"""
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$wb = $excel.Workbooks.Open('{source}', $null, $true)
$ws = $wb.Worksheets.Item(1)
$used = $ws.UsedRange
$rows = $used.Rows.Count
$cols = $used.Columns.Count
$headers = @()
for ($c=1; $c -le $cols; $c++) {{ $headers += [string]$ws.Cells.Item(1,$c).Text }}
$items = @()
for ($r=2; $r -le $rows; $r++) {{
  $obj = @{{}}
  for ($c=1; $c -le $cols; $c++) {{
    $obj[$headers[$c-1]] = [string]$ws.Cells.Item($r,$c).Text
  }}
  $items += [pscustomobject]$obj
}}
$wb.Close($false)
$excel.Quit()
$items | ConvertTo-Json -Depth 4
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if not result.stdout.strip():
        return []
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else [data]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Path to .xls file")
    args = parser.parse_args()

    rows = read_xls_with_excel_com(Path(args.source))
    hosts = []
    for row in rows:
        platform = str(row.get("平台", "")).strip()
        ip = str(row.get("ip", "")).strip()
        account = str(row.get("账号", "")).strip()
        if not ip:
            continue
        host_id = slug_host(platform, ip)
        hosts.append(
            {
                "hostId": host_id,
                "platform": platform,
                "ip": ip,
                "account": account,
                "passwordRef": f"HOST_{host_id.upper().replace('-', '_')}_PASSWORD",
            }
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"hosts": hosts}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Imported {len(hosts)} host(s) to {OUTPUT}. Passwords were not written.")


if __name__ == "__main__":
    main()

