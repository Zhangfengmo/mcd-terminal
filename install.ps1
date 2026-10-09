# mcd-terminal installer for Windows PowerShell
#
#   irm https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.ps1 | iex
#
# No Python needed. Detects x64 / arm64, downloads the Windows release, verifies SHA-256
# (mandatory), installs to %LOCALAPPDATA%\mcd-terminal and adds it to the user PATH.
# Any failure in download, checksum or unzip stops the install; nothing unverified is installed.
# This file is ASCII-only on purpose: Windows PowerShell 5.1 may not decode `irm` output as UTF-8.
#
# Downloads from GitHub can be slow in mainland China, so the installer speed-tests GitHub and a
# few mirrors and downloads from the fastest. Release builds of this script carry the SHA-256 of
# every package (see $EmbeddedSums below), so no separate checksum download is needed; mirrors only
# serve the package, and a tampered package fails verification and the next source is tried.
#
# If even fetching this script from GitHub stalls, use a mirror:
#   irm https://gh-proxy.com/https://github.com/Zhangfengmo/mcd-terminal/releases/latest/download/install.ps1 | iex
#
# Optional env vars: MCD_VERSION (e.g. v0.3.1), MCD_MIRROR (none, or a mirror prefix such as
# https://gh-proxy.com/), MCD_REPO, MCD_DOWNLOAD_URL (testing: replaces GitHub)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Say($m)  { Write-Host "* $m" -ForegroundColor DarkYellow }
function Ok($m)   { Write-Host "  OK $m" -ForegroundColor Green }
function Fail($m) { Write-Host "  FAILED $m" -ForegroundColor Red; throw $m }

# ---- Filled in by CI at release time: this version and the SHA-256 of each package ----
# @@EMBEDDED_BEGIN@@
$EmbeddedVersion = ''
$EmbeddedSums = ''
# @@EMBEDDED_END@@

$Repo    = if ($env:MCD_REPO) { $env:MCD_REPO } else { 'Zhangfengmo/mcd-terminal' }
$Version = if ($env:MCD_VERSION) { $env:MCD_VERSION } else { 'latest' }

$cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
switch ($cpu) {
  'AMD64' { $Arch = 'x64' }
  'ARM64' { $Arch = 'arm64' }
  default { Fail "Unsupported CPU architecture: $cpu" }
}

$Asset = "mcd-windows-$Arch.zip"
$UseEmbedded = $false
if ($EmbeddedSums -and ($Version -eq 'latest' -or $Version -eq $EmbeddedVersion)) {
  $UseEmbedded = $true
  $Version = $EmbeddedVersion
}
if ($env:MCD_DOWNLOAD_URL) { $Base = $env:MCD_DOWNLOAD_URL.TrimEnd('/') }
elseif ($Version -eq 'latest') { $Base = "https://github.com/$Repo/releases/latest/download" }
else { $Base = "https://github.com/$Repo/releases/download/$Version" }

$Mirrors = @('https://gh-proxy.com/', 'https://ghfast.top/')
if ($env:MCD_MIRRORS) { $Mirrors = @($env:MCD_MIRRORS -split '\s+' | Where-Object { $_ }) }
if ($env:MCD_MIRROR -in @('none', 'off', '0')) { $Mirrors = @() }
elseif ($env:MCD_MIRROR) { $Mirrors = @($env:MCD_MIRROR) }

function Measure-Source($url) {
  # Bytes per second for the first 256 KB, or 0 if unreachable within a few seconds.
  try {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.AddRange(0, 262143); $req.Timeout = 5000; $req.ReadWriteTimeout = 5000
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = $req.GetResponse(); $stream = $resp.GetResponseStream()
    $buf = New-Object byte[] 65536; $total = 0
    while ($total -lt 262144 -and $sw.ElapsedMilliseconds -lt 6000) {
      $n = $stream.Read($buf, 0, $buf.Length); if ($n -le 0) { break }; $total += $n
    }
    $resp.Close()
    return [int]($total / [Math]::Max($sw.Elapsed.TotalSeconds, 0.001))
  } catch { return 0 }
}

$Root = Join-Path $env:LOCALAPPDATA 'mcd-terminal'
$App  = Join-Path $Root 'mcd'
$Tmp  = Join-Path ([IO.Path]::GetTempPath()) ("mcd-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

try {
  Say "Installing mcd-terminal (windows-$Arch)"
  $zip  = Join-Path $Tmp $Asset
  $sums = Join-Path $Tmp 'SHA256SUMS'

  # 1) Checksums: built into release copies of this script; otherwise fetched from GitHub
  if ($UseEmbedded) {
    Set-Content -Path $sums -Value $EmbeddedSums -Encoding ASCII
    Ok "Version $Version (checksums built into this installer)"
  } else {
    try { Invoke-WebRequest -UseBasicParsing -Uri "$Base/SHA256SUMS" -OutFile $sums -TimeoutSec 30 }
    catch { Fail "Cannot fetch checksums from GitHub: $Base/SHA256SUMS (try the mirror command at the top of this script)" }
  }
  $expected = $null
  foreach ($line in Get-Content $sums) {
    $parts = $line.Trim() -split '\s+', 2
    if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq $Asset) { $expected = $parts[0].ToLower() }
  }
  if (-not $expected) { Fail "No checksum for $Asset in SHA256SUMS (this platform may not be released yet)" }

  # 2) Package sources: GitHub + mirrors, fastest first
  $sources = @([pscustomobject]@{ Label = 'GitHub'; Url = "$Base/$Asset"; Speed = 0 })
  foreach ($m in $Mirrors) {
    $label = ($m -replace '^https?://', '') -replace '/.*$', ''
    $sources += [pscustomobject]@{ Label = $label; Url = ($m.TrimEnd('/') + "/$Base/$Asset"); Speed = 0 }
  }
  if ($sources.Count -gt 1) {
    foreach ($src in $sources) { $src.Speed = Measure-Source $src.Url }
    $sources = @($sources | Sort-Object -Property Speed -Descending)
    $summary = ($sources | Where-Object { $_.Speed -gt 0 } | ForEach-Object {
      if ($_.Speed -ge 1MB) { '{0} {1:N1} MB/s' -f $_.Label, ($_.Speed / 1MB) } else { '{0} {1} KB/s' -f $_.Label, [int]($_.Speed / 1KB) }
    }) -join ' | '
    if ($summary) { Ok "Speed test: $summary" }
  }

  $from = $null
  foreach ($src in $sources) {
    Write-Host "  Downloading $Asset from $($src.Label) ..." -ForegroundColor DarkGray
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    try { Invoke-WebRequest -UseBasicParsing -Uri $src.Url -OutFile $zip -TimeoutSec 300 }
    catch { Write-Host "    $($src.Label) failed, trying the next source" -ForegroundColor DarkGray; continue }
    $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
    if ($actual -eq $expected) { $from = $src.Label; break }
    Write-Host "    $($src.Label) served a file that failed SHA-256 verification; discarded" -ForegroundColor Red
  }
  if (-not $from) { Fail "No source provided a verified $Asset. Install aborted." }
  Ok "Downloaded and verified SHA-256 (source: $from)"

  $unpack = Join-Path $Tmp 'unpack'
  try { Expand-Archive -Path $zip -DestinationPath $unpack -Force } catch { Fail 'Unzip failed' }
  if (-not (Test-Path (Join-Path $unpack 'mcd\mcd.exe'))) { Fail 'Archive is incomplete' }

  New-Item -ItemType Directory -Force -Path $Root | Out-Null
  if (Test-Path $App) { Remove-Item -Recurse -Force $App }
  Move-Item -Path (Join-Path $unpack 'mcd') -Destination $App
  $exe = Join-Path $App 'mcd.exe'
  $installed = & $exe --version
  if ($LASTEXITCODE -ne 0) { Fail "Installed, but $exe does not run" }
  Ok "Installed $installed -> $exe"

  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  $parts = @()
  if ($userPath) { $parts = $userPath -split ';' | Where-Object { $_ } }
  if ($parts -notcontains $App) {
    [Environment]::SetEnvironmentVariable('Path', (($parts + $App) -join ';'), 'User')
    Ok "Added $App to your user PATH"
    Write-Host '  Reopen PowerShell or Windows Terminal so the new PATH takes effect.' -ForegroundColor DarkGray
  }
  $env:Path = "$App;$env:Path"

  Write-Host ''
  Say 'Done! Next:'
  Write-Host '    mcd login     # paste your McDonald''s MCP token once'
  Write-Host '    mcd           # today''s brief'
  Write-Host '    mcd --demo    # no token yet? try the demo'
}
finally {
  Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}
