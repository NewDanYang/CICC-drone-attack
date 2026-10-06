param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot
)

$ErrorActionPreference = 'Stop'
$backupRoot = Join-Path $PSScriptRoot 'backups\official_A0'
$targetRoot = Join-Path $WorkspaceRoot 'src\ego-planner\src\planner\plan_manage\launch\FS-J310'

if (-not (Test-Path -LiteralPath $targetRoot)) {
    throw "Ego-Planner target directory not found: $targetRoot"
}

Copy-Item -LiteralPath (Join-Path $backupRoot 'FS-J310_ego-planner.launch') -Destination (Join-Path $targetRoot 'FS-J310_ego-planner.launch') -Force
Copy-Item -LiteralPath (Join-Path $backupRoot 'FS-J310_Param.xml') -Destination (Join-Path $targetRoot 'FS-J310_Param.xml') -Force
Write-Output "Restored official A0 Ego-Planner configuration under $targetRoot"
Write-Output "V1 Safety Recovery files were not touched by this script."
