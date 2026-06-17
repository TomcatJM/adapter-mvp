param(
  [string]$Source = "D:\document\up\user-password.xls",
  [int]$Row = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
python (Join-Path $root "scripts\remote_ops.py") restart --source $Source --row $Row
