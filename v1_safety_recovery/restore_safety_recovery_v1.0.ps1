$ErrorActionPreference = "Stop"
$root = "C:\Users\admin\tcei_baseline_work\official_source_20260927_225142"
$backup = "C:\Users\admin\tcei_optimization\backups\official_20260927_225142"
$files = @(
  "src\mission_pkg\src\mavros_cnt.cpp",
  "src\mission_pkg\include\mavros_cnt.h",
  "src\mission_pkg\launch\llm_mission.launch"
)
foreach ($rel in $files) {
  Copy-Item (Join-Path $backup $rel) (Join-Path $root $rel) -Force
}
Write-Output "Restored original V1.0 source files."
