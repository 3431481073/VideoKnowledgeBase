# 视频知识库 · 打包脚本
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -Mode onefile
#   powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -Mode onedir
#
# 注意：本文件必须以 UTF-8 **带 BOM** 保存。
#   Windows PowerShell 5.1 会按系统 ANSI(GBK) 解码没有 BOM 的脚本，
#   中文注释与消息会变乱码，并可能把脚本本身解析坏。
#
# ============================================================================
# 【重要】接进工作台时请用 onedir 版
# ============================================================================
# 本轮界面只用假数据、不 import 转写/清洗后端，所以 onefile 只有十几 MB，
# 启动几秒，单文件分发很方便。
#
# 但下一轮接入真实转写后，PyInstaller 会把整条引擎链一起打进去：
#     ctranslate2 + cublas64_12.dll(97.8MB) + cublasLt64_12.dll(637.7MB)
#     + cudart / nvrtc + onnxruntime + faster-whisper  ≈ 1.4 GB
# onefile 每次启动都要把这 1.4 GB 解压到临时目录，启动会慢到不可接受
# （而且反复写盘、占临时空间）。onedir 不需要解压，直接就地加载。
#
# 所以：本轮交付 onefile；接引擎那一轮改成 -Mode onedir。
# ============================================================================

param(
    [ValidateSet('onefile', 'onedir')]
    [string]$Mode = 'onefile',
    [switch]$NoClean,
    # 旁路构建用：改输出目录名（默认 build\dist_<Mode>）。
    # 为什么需要：exe 正在运行时 Windows **锁着它的文件**，往原路径重打必然失败。
    # 用 -DistName dist_probe 可以另打一份来验证，不动正在跑的那个实例。
    [string]$DistName = ''
)

$ErrorActionPreference = 'Stop'

# ---- 必须清掉外部 PYTHONPATH ----
# 本机有一个**用户级** PYTHONPATH 指向 D:\MyProject\html-video-stack\python_packages。
# 它会把**别的项目**的包塞进本项目的 sys.path。实测后果（不是推测）：
#   torch 从那边被拽进来 —— _internal\torch 4.07GB + torch_cuda.dll 774MB
#   + cudnn/cusparse/cufft/cusolver，包体从预期的 1.4GB 涨到 **7.98GB**。
# 本项目 venv 里根本没有 torch（site-packages\torch 不存在），也不该有。
# 清掉之后断言一次，免得将来又被悄悄污染。
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONPATH = $null
if ($env:PYTHONPATH) {
    throw "PYTHONPATH 没清干净，仍是：$env:PYTHONPATH —— 打包会被别的项目污染，中止。"
}
Write-Host "已清掉 PYTHONPATH（防止读到别的项目的包）" -ForegroundColor Yellow

$Root    = Split-Path -Parent $PSScriptRoot
$Entry   = Join-Path $Root 'src\app_web.py'
$WebUi   = Join-Path $Root 'webui'
if ($DistName) { $DistDir = Join-Path $Root "build\$DistName" }
else           { $DistDir = Join-Path $Root "build\dist_$Mode" }
$WorkDir = Join-Path $Root "build\work_$Mode"
$Python  = Join-Path $Root 'venv\Scripts\python.exe'
$Icon    = Join-Path $Root 'build\vkb.ico'

if (-not (Test-Path $Python)) { throw "找不到 venv python：$Python" }
if (-not (Test-Path $Entry))  { throw "找不到入口：$Entry" }
if (-not (Test-Path $WebUi))  { throw "找不到界面目录：$WebUi" }

# ---- exe 图标 ----
# 不给 --icon 的话 PyInstaller 会塞它自己的**默认 Python 图标**，
# 任务栏、窗口左上角、文件管理器里全是那个，很丑。
# vkb.ico 由 build\make_ico.py 从 build\vkb.svg 生成（多尺寸 16~256）。
if (-not (Test-Path $Icon)) {
    throw "找不到图标 $Icon`n先跑：venv\Scripts\python.exe build\make_ico.py"
}
Write-Host "exe 图标：$Icon" -ForegroundColor Cyan

# ---- 打包前必须清掉 webui\media 目录联接 ----
# 它是运行时由 media.ensure_link() 建的，指向 data\media。
# 如果留着，PyInstaller 的 --add-data webui;webui 会**跟着联接把整个媒体目录
# 打进 exe**，包体积会凭空涨上去。这里断言 + 自动清理。
$MediaLink = Join-Path $WebUi 'media'
if (Test-Path $MediaLink) {
    $item = Get-Item -LiteralPath $MediaLink -Force
    if ($item.LinkType -ne 'Junction') {
        throw "webui\media 存在但不是目录联接（LinkType=$($item.LinkType)），" +
              "拒绝删除。请手动确认后移除，否则会被打进 exe。"
    }
    [System.IO.Directory]::Delete($MediaLink, $false)
    if (Test-Path $MediaLink) { throw "移除 webui\media 联接失败，中止打包。" }
    Write-Host "已移除运行时媒体联接 webui\media（防止媒体被打进 exe）" -ForegroundColor Yellow
}
Write-Host "打包前检查：webui\media 不存在 OK" -ForegroundColor Green

# PyInstaller 是否就位（用 try/catch，避免原生命令的 stderr 触发 ErrorAction Stop）
$hasPI = $false
try {
    $null = & $Python -c "import PyInstaller"
    $hasPI = ($LASTEXITCODE -eq 0)
} catch {
    $hasPI = $false
}
if (-not $hasPI) {
    throw "PyInstaller 未安装。先跑：uv pip install --python `"$Python`" -r requirements-build.txt"
}

Write-Host "=== 打包模式：$Mode ===" -ForegroundColor Cyan
Write-Host "入口：$Entry"
Write-Host "界面：$WebUi"

# ---- 转写引擎链 ----
# faster_whisper / ctranslate2 / av / nvidia 是**静态分析扫不到**的：
#   · faster_whisper 在函数体里才 import av，VAD 才 import onnxruntime；
#   · nvidia 的 CUDA DLL 是靠 transcriber.py 注入 PATH 找的，根本没有 import 语句。
# 不显式收进来，打包版一调转写就 ModuleNotFoundError / DLL 找不到。
#
# 【onnxruntime 不整包收】--collect-all 会连 onnxruntime.transformers 一起收，
# 里面 torch_onnx_export_helper.py 顶层 `import torch` —— 一收就触发 torch hook，
# 把整套 torch+CUDA（4GB+）拖进包。实测就是这条把包从 1.4GB 撑到 7.98GB。
# onnxruntime 自带 hook（_pyinstaller_hooks_contrib\stdhooks\hook-onnxruntime.py）
# 会收它需要的 CAPI DLL，所以只留 --hidden-import 就够。
#
# 【torch 三件套显式排除】引擎链走 CTranslate2，src\ 下**没有任何 torch 导入**，
# 排除掉是安全的；再加一道闸，防止将来谁装了 torch 又重演 8GB。
$piArgs = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--name', 'VideoKnowledgeBase',
    '--windowed',
    '--icon', $Icon,
    '--collect-all', 'webview',
    '--collect-all', 'faster_whisper',
    '--collect-all', 'ctranslate2',
    '--collect-all', 'av',
    '--collect-all', 'nvidia',
    '--hidden-import', 'onnxruntime',
    '--exclude-module', 'torch',
    '--exclude-module', 'torchaudio',
    '--exclude-module', 'torchvision',
    '--add-data', "$WebUi;webui",
    '--add-data', "$Icon;.",
    '--distpath', $DistDir,
    '--workpath', $WorkDir,
    '--specpath', (Join-Path $Root 'build')
)
if ($Mode -eq 'onefile') { $piArgs += '--onefile' } else { $piArgs += '--onedir' }
if (-not $NoClean)       { $piArgs += '--clean' }
$piArgs += $Entry

# ---- 【必须】保护 exe 旁边的用户数据 ----
# PyInstaller 的 --noconfirm 会**整个删掉**输出目录 $DistDir\VideoKnowledgeBase，
# 而打包版的用户数据就在 exe 旁边（media.app_root() = dirname(sys.executable)），
# 也就是 $DistDir\VideoKnowledgeBase\data。
# 不保护的话：**重打一次包 = 删一次用户数据**。
# （实测踩过：4.9 GB 媒体库被清空，只剩刚生成的样片。）
# 这里先把它挪到输出目录之外的位置，打完再原样放回；用 try/finally 保证
# 即使 PyInstaller 失败也不会把数据留在临时位置。
$AppOut    = Join-Path $DistDir 'VideoKnowledgeBase'
$DataDir   = Join-Path $AppOut 'data'
$DataStash = Join-Path $DistDir '_data_stash'
$dataSaved = $false
# 上次异常退出可能留下 stash —— 那里面**就是用户数据**，绝不能当垃圾删。
if (Test-Path $DataStash) {
    if (Test-Path $DataDir) {
        throw "既有 $DataDir 又有上次遗留的 $DataStash，无法判断该用哪个。" +
              "请人工确认后删掉其中一个再重跑：$DataStash"
    }
    Write-Host "发现上次遗留的 $DataStash，先放回原位再继续" -ForegroundColor Yellow
    Move-Item -LiteralPath $DataStash -Destination $DataDir
}
if (Test-Path $DataDir) {
    Move-Item -LiteralPath $DataDir -Destination $DataStash
    $dataSaved = $true
    Write-Host "已把 exe 旁的 data\ 挪走保护（打完自动放回）" -ForegroundColor Yellow
}

try {
    & $Python @piArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }
} finally {
    if ($dataSaved) {
        Move-Item -LiteralPath $DataStash -Destination $DataDir
        Write-Host "已把 data\ 原样放回 $DataDir" -ForegroundColor Green
    }
}

# ---- 产物守门：不许有 torch ----
# 引擎链走 CTranslate2，产物里出现 torch = 又被外部包污染了，直接判失败。
if ($Mode -eq 'onedir') {
    $Internal = Join-Path $DistDir 'VideoKnowledgeBase\_internal'
    foreach ($bad in @('torch', 'torchaudio', 'torchvision', 'torch_cuda.dll')) {
        if (Test-Path (Join-Path $Internal $bad)) {
            throw "产物里出现 $bad —— PYTHONPATH 污染或 collect-all 又把 torch 收进来了，中止。"
        }
    }
    Write-Host "产物守门：无 torch OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Green
if ($Mode -eq 'onefile') {
    $exe = Join-Path $DistDir 'VideoKnowledgeBase.exe'
} else {
    $exe = Join-Path $DistDir 'VideoKnowledgeBase\VideoKnowledgeBase.exe'
}
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "产物：$exe  ($mb MB)"
} else {
    Write-Host "产物目录：$DistDir" -ForegroundColor Yellow
}
