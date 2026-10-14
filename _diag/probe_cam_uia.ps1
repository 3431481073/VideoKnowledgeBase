# 用 UI Automation 读相机应用的控件树，查它到底是不是视频模式。
# PrintWindow 抓不到 UWP 的 XAML 控件层（只有视频层），所以只能走 UIA。
param([string]$Tag = "default", [string]$Uri = "microsoft.windows.camera:")

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Kill-Cam {
  Get-Process WindowsCamera -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
  Start-Sleep -Milliseconds 2500
}

Kill-Cam
Start-Process $Uri
$hwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 50; $i++) {
  Start-Sleep -Milliseconds 400
  $p = Get-Process WindowsCamera -ErrorAction SilentlyContinue
  if (-not $p) { continue }
  $w = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($e in $w) {
    try { if ($e.Current.Name -eq "相机" -or $e.Current.Name -eq "Camera") { $hwnd = $e.Current.NativeWindowHandle; break } } catch {}
  }
  if ($hwnd -ne [IntPtr]::Zero) { break }
}
if ($hwnd -eq [IntPtr]::Zero) { "[$Tag] 没找到相机窗口"; exit 1 }

Start-Sleep -Seconds 5
$root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
if (-not $root) { "[$Tag] 拿不到根元素"; exit 1 }

"[$Tag] === 控件树（只列有名字或可切换的）==="
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                     [System.Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) {
  try {
    $c = $e.Current
    $n = $c.Name
    $ct = $c.ControlType.ProgrammaticName -replace "ControlType\.", ""
    if (-not $n -and $ct -ne "ToggleButton") { continue }
    $extra = ""
    try {
      $tp = $e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
      $extra = " ToggleState=" + $tp.Current.ToggleState
    } catch {}
    try {
      $sp = $e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
      $extra += " Selected=" + $sp.Current.IsSelected
    } catch {}
    "{0,-18} name='{1}'{2}" -f $ct, $n, $extra
  } catch {}
}
Kill-Cam
