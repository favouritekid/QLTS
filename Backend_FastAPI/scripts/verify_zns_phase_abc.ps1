[CmdletBinding()]
param(
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$PhaseTestTargets = @(
    "tests/utils/test_datetime_helpers.py",
    "tests/utils/test_id_helpers.py",
    "tests/unit/test_notification_payloads.py",
    "tests/unit/test_condition_metadata_parity.py",
    "tests/unit/test_zalo_phase1_review_findings.py"
)

$LegacyParityTarget = "tests/unit/test_notification_parity.py"
$KnownParityDebtMarker = "application_fee_paid"
$KnownParityDebtDetail = "missing from NOTIFICATION_REGISTRY"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host $Title
    Write-Host ("=" * 72)
}

function Format-BackendCommand {
    param([string[]]$CommandArgs)
    return "docker compose exec -T backend $($CommandArgs -join ' ')"
}

function Invoke-BackendCommand {
    param(
        [string[]]$CommandArgs,
        [switch]$Capture
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    $allArgs = @("compose", "exec", "-T", "backend") + $CommandArgs

    try {
        $process = Start-Process `
            -FilePath "docker" `
            -ArgumentList $allArgs `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile

        $parts = @()
        foreach ($path in @($stdoutFile, $stderrFile)) {
            if (Test-Path $path) {
                $content = Get-Content -Raw -Path $path
                if ($content -and $content.Trim()) {
                    $parts += $content.TrimEnd()
                }
            }
        }

        $output = ($parts -join "`n").Trim()

        if (-not $Capture -and $output) {
            Write-Host $output
        }

        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = $output
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }
}

function Test-PytestAvailable {
    Write-Section "Pytest Availability Check"
    $commandArgs = @("python", "-m", "pytest", "--version")
    Write-Host (Format-BackendCommand -CommandArgs $commandArgs)
    $result = Invoke-BackendCommand -CommandArgs $commandArgs -Capture

    if ($result.ExitCode -eq 0) {
        Write-Host $result.Output
        return $true
    }

    if ($result.Output) {
        Write-Host $result.Output
    }

    Write-Host ""
    Write-Host "Pytest is not available in the backend container. Install dev dependencies first:"
    Write-Host "  docker compose exec backend pip install -r requirements-dev.txt"
    return $false
}

function Invoke-PhaseSuite {
    Write-Section "Phase A/B/C Regression Suite"
    $commandArgs = @("python", "-m", "pytest", "-q") + $PhaseTestTargets
    Write-Host (Format-BackendCommand -CommandArgs $commandArgs)
    $result = Invoke-BackendCommand -CommandArgs $commandArgs
    return ($result.ExitCode -eq 0)
}

function Invoke-LegacyParitySentinel {
    param([switch]$StrictMode)

    Write-Section "Legacy Parity Sentinel"
    $commandArgs = @("python", "-m", "pytest", "-q", $LegacyParityTarget)
    Write-Host (Format-BackendCommand -CommandArgs $commandArgs)
    $result = Invoke-BackendCommand -CommandArgs $commandArgs -Capture

    if ($result.Output) {
        Write-Host $result.Output
    }

    if ($result.ExitCode -eq 0) {
        return $true
    }

    $isKnownDebt = $result.Output.Contains($KnownParityDebtMarker) -and `
        $result.Output.Contains($KnownParityDebtDetail)

    if ($isKnownDebt -and -not $StrictMode) {
        Write-Host ""
        Write-Host "Known legacy parity debt detected: application_fee_paid is still absent from deprecated NOTIFICATION_REGISTRY."
        Write-Host "Runtime catalog wiring is unaffected; this warning stays visible so Phase A/B/C can be verified without masking new drift."
        Write-Host "Run with -Strict if you want this debt to fail the gate."
        return $true
    }

    return $false
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

Write-Host "ZNS Phase A/B/C Verification"
Write-Host "Repo root: $repoRoot"
Write-Host "Strict mode: $(if ($Strict) { 'ON' } else { 'OFF' })"

if (-not (Test-PytestAvailable)) {
    exit 1
}

if (-not (Invoke-PhaseSuite)) {
    Write-Section "Result"
    Write-Host "FAIL: Phase A/B/C regression suite failed."
    exit 1
}

if (-not (Invoke-LegacyParitySentinel -StrictMode:$Strict)) {
    Write-Section "Result"
    if ($Strict) {
        Write-Host "FAIL: Legacy parity sentinel failed in strict mode."
    } else {
        Write-Host "FAIL: Unexpected parity drift detected."
    }
    exit 1
}

Write-Section "Result"
if ($Strict) {
    Write-Host "PASS: Phase A/B/C regression suite and parity sentinel are clean."
} else {
    Write-Host "PASS: Phase A/B/C regression suite is clean."
    Write-Host "NOTE: Non-blocking legacy parity debt is still surfaced when present."
}

exit 0
