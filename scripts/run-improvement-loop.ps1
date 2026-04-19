[CmdletBinding()]
param(
    [int]$Cycles = 1,
    [string]$Model = "gpt-5.4-mini",
    [string]$BranchPrefix = "autoloop",
    [string]$BranchName = "",
    [switch]$Push,
    [switch]$SkipEvaluation,
    [switch]$DryRun,
    [switch]$ReuseWorktree,
    [int]$SleepSeconds = 0,
    [string]$Goal = "Make FieldOps more autonomous, useful, novel, ambitious, and demo-ready."
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = (Get-Location).Path,
        [switch]$AllowFailure
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $quotedArgs = foreach ($arg in $ArgumentList) {
        if ($arg -match '[\s"]') {
            '"' + ($arg -replace '"', '\"') + '"'
        }
        else {
            $arg
        }
    }
    $psi.Arguments = [string]::Join(" ", $quotedArgs)

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    $output = ($stdout + $stderr).Trim()

    if (-not $AllowFailure -and $exitCode -ne 0) {
        $joined = if ($ArgumentList.Count -gt 0) { "$FilePath $($ArgumentList -join ' ')" } else { $FilePath }
        throw "Command failed ($exitCode): $joined`n$output"
    }
    return @{
        Output = ($output | Out-String).Trim()
        ExitCode = $exitCode
    }
}

function Get-RepoRoot {
    param([string]$Start)
    $result = Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $Start, "rev-parse", "--show-toplevel")
    return $result.Output.Trim()
}

function Get-CurrentBranch {
    param([string]$RepoPath)
    $result = Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "branch", "--show-current")
    return $result.Output.Trim()
}

function Get-HeadSha {
    param([string]$RepoPath)
    $result = Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "rev-parse", "HEAD")
    return $result.Output.Trim()
}

function Get-StatusShort {
    param([string]$RepoPath)
    $result = Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "status", "--short")
    if ([string]::IsNullOrWhiteSpace($result.Output)) {
        return ""
    }
    $lines = $result.Output -split "`r?`n" | Where-Object {
        $_.Trim() -and $_ -notmatch '^\?\?\s+\.codex-autoloop([\\/]|$)'
    }
    return ($lines -join "`n").Trim()
}

function Test-GitClean {
    param([string]$RepoPath)
    return [string]::IsNullOrWhiteSpace((Get-StatusShort -RepoPath $RepoPath))
}

function Get-RemoteRepoName {
    param([string]$RepoPath)
    $result = Invoke-CheckedCommand -FilePath "gh" -ArgumentList @("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner") -WorkingDirectory $RepoPath -AllowFailure
    if ($result.ExitCode -ne 0) {
        return ""
    }
    return $result.Output.Trim()
}

function Get-OpenIssueContext {
    param([string]$RepoPath)
    $result = Invoke-CheckedCommand -FilePath "gh" -ArgumentList @("issue", "list", "--limit", "8", "--json", "number,title,state") -WorkingDirectory $RepoPath -AllowFailure
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Output)) {
        return "No GitHub issue context available."
    }

    try {
        $issues = $result.Output | ConvertFrom-Json
        if (-not $issues -or $issues.Count -eq 0) {
            return "No open GitHub issues."
        }
        $lines = foreach ($issue in $issues) {
            "#$($issue.number) [$($issue.state)] $($issue.title)"
        }
        return ($lines -join "`n")
    }
    catch {
        return "GitHub issue context could not be parsed."
    }
}

function Get-RecentCommitContext {
    param([string]$RepoPath)
    $result = Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "log", "--oneline", "-5")
    if ([string]::IsNullOrWhiteSpace($result.Output)) {
        return "No recent commits found."
    }
    return $result.Output
}

function New-Worktree {
    param(
        [string]$RepoPath,
        [string]$BranchName,
        [string]$BaseSha
    )

    $storageRoot = Join-Path $env:TEMP "fieldops-autoloop"
    New-Item -ItemType Directory -Path $storageRoot -Force | Out-Null
    $safeBranch = ($BranchName -replace "[^A-Za-z0-9._-]", "-")
    $worktreePath = Join-Path $storageRoot $safeBranch

    if (Test-Path $worktreePath) {
        if (-not $ReuseWorktree) {
            throw "Worktree path already exists: $worktreePath. Use -ReuseWorktree or pick a different BranchPrefix."
        }
        return $worktreePath
    }

    $branchExistsResult = Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "branch", "--list", $BranchName)
    $branchExists = -not [string]::IsNullOrWhiteSpace($branchExistsResult.Output)

    if ($branchExists) {
        if (-not $ReuseWorktree) {
            throw "Branch already exists: $BranchName. Use -ReuseWorktree or choose a different BranchName."
        }
        Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "worktree", "add", $worktreePath, $BranchName) | Out-Null
    }
    else {
        Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $RepoPath, "worktree", "add", "-b", $BranchName, $worktreePath, $BaseSha) | Out-Null
    }
    return $worktreePath
}

function New-CyclePrompt {
    param(
        [string]$WorktreePath,
        [string]$PromptSourcePath,
        [string]$BranchName,
        [int]$CycleNumber,
        [int]$CycleTotal,
        [string]$GoalText,
        [switch]$SkipEval
    )

    $masterPrompt = Get-Content $PromptSourcePath -Raw
    $status = Get-StatusShort -RepoPath $WorktreePath
    if ([string]::IsNullOrWhiteSpace($status)) {
        $status = "Working tree clean."
    }
    $recentCommits = Get-RecentCommitContext -RepoPath $WorktreePath
    $issues = Get-OpenIssueContext -RepoPath $WorktreePath
    $previousSummaryPath = Join-Path $WorktreePath ".codex-autoloop\last-summary.md"
    $previousSummary = if (Test-Path $previousSummaryPath) { Get-Content $previousSummaryPath -Raw } else { "No previous cycle summary yet." }

    $evalLine = if ($SkipEval) {
        "- You may skip `cd backend && python -m app.scripts.run_evaluations` only if the change is clearly unrelated or too expensive for the current cycle; if you skip it, explain why in the cycle summary."
    }
    else {
        "- Run `cd backend && python -m app.scripts.run_evaluations` before you finish unless it is impossible; explain any failure in the cycle summary."
    }

    return @"
$masterPrompt

Additional run instructions for this cycle:
- Repository root: $WorktreePath
- Improvement goal for this run: $GoalText
- Cycle: $CycleNumber of $CycleTotal
- Branch: $BranchName
- Stay tightly relevant to the current product state, recent commits, and any open repo issues.
- Pick exactly one high-value improvement that is meaningful, demoable, and shippable in one focused cycle.
- Do not commit or push; the outer workflow will handle git after validation.
- Before finishing, write `.codex-autoloop/commit-message.txt` with one short commit title under 72 characters.
- Before finishing, write `.codex-autoloop/cycle-summary.md` with:
  - current product state
  - chosen improvement
  - why it was high-value
  - tests and validation run
  - remaining weaknesses
  - next recommended loop
- Run the FieldOps validation commands after your changes:
  - `cd backend && pytest`
  - `cd frontend && npm run build`
  $evalLine

Current git status:
$status

Recent commits:
$recentCommits

Open issues / repo context:
$issues

Previous cycle summary:
$previousSummary
"@
}

function Run-Verification {
    param(
        [string]$WorktreePath,
        [switch]$SkipEval
    )

    $steps = @(
        @{ Name = "backend pytest"; Path = "python"; Args = @("-m", "pytest"); Cwd = (Join-Path $WorktreePath "backend") },
        @{ Name = "frontend build"; Path = "npm"; Args = @("run", "build"); Cwd = (Join-Path $WorktreePath "frontend") }
    )

    if (-not $SkipEval) {
        $steps += @{ Name = "backend evaluations"; Path = "python"; Args = @("-m", "app.scripts.run_evaluations"); Cwd = (Join-Path $WorktreePath "backend") }
    }

    foreach ($step in $steps) {
        Write-Host "==> Running $($step.Name)"
        Invoke-CheckedCommand -FilePath $step.Path -ArgumentList $step.Args -WorkingDirectory $step.Cwd | Out-Null
    }
}

function Save-LocalMetadata {
    param(
        [string]$WorktreePath,
        [int]$CycleNumber,
        [string]$BranchName,
        [string]$CommitSha,
        [string]$PushStatus
    )

    $metaDir = Join-Path $WorktreePath ".codex-autoloop"
    New-Item -ItemType Directory -Path $metaDir -Force | Out-Null
    $summaryPath = Join-Path $metaDir "cycle-summary.md"
    $lastSummaryPath = Join-Path $metaDir "last-summary.md"
    if (Test-Path $summaryPath) {
        Copy-Item -Path $summaryPath -Destination $lastSummaryPath -Force
    }

    $historyPath = Join-Path $metaDir "history.jsonl"
    $record = [ordered]@{
        cycle = $CycleNumber
        branch = $BranchName
        commit = $CommitSha
        push_status = $PushStatus
        timestamp = (Get-Date).ToString("o")
    } | ConvertTo-Json -Compress
    Add-Content -Path $historyPath -Value $record
}

$repoRoot = Get-RepoRoot -Start $PSScriptRoot
$baseBranch = Get-CurrentBranch -RepoPath $repoRoot
$headSha = Get-HeadSha -RepoPath $repoRoot
$repoName = Get-RemoteRepoName -RepoPath $repoRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($BranchName)) {
    $branchName = "$BranchPrefix/$timestamp"
}
else {
    $branchName = $BranchName
}
$worktreePath = New-Worktree -RepoPath $repoRoot -BranchName $branchName -BaseSha $headSha

Write-Host "Repo root: $repoRoot"
Write-Host "Base branch: $baseBranch"
Write-Host "Remote repo: $(if ($repoName) { $repoName } else { 'unknown' })"
Write-Host "Autoloop branch: $branchName"
Write-Host "Worktree: $worktreePath"

for ($cycle = 1; $cycle -le $Cycles; $cycle++) {
    Write-Host ""
    Write-Host "=== Improvement Cycle $cycle / $Cycles ==="

    if (-not (Test-GitClean -RepoPath $worktreePath)) {
        throw "Worktree is not clean before cycle $cycle. Resolve or recreate the worktree before continuing."
    }

    $stateDir = Join-Path $worktreePath ".codex-autoloop"
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $promptPath = Join-Path $stateDir "cycle-prompt.txt"
    $codexLastMessagePath = Join-Path $stateDir "codex-last-message.txt"
    $promptSourcePath = Join-Path $repoRoot "docs\autonomous_improvement_prompt.md"
    $promptText = New-CyclePrompt -WorktreePath $worktreePath -PromptSourcePath $promptSourcePath -BranchName $branchName -CycleNumber $cycle -CycleTotal $Cycles -GoalText $Goal -SkipEval:$SkipEvaluation
    Set-Content -Path $promptPath -Value $promptText -Encoding UTF8

    if ($DryRun) {
        Write-Host "Dry run enabled. Prompt written to $promptPath"
        continue
    }

    Get-Content $promptPath -Raw | & codex exec -C $worktreePath --full-auto -m $Model -o $codexLastMessagePath -
    if ($LASTEXITCODE -ne 0) {
        throw "Codex exec failed during cycle $cycle."
    }

    Run-Verification -WorktreePath $worktreePath -SkipEval:$SkipEvaluation

    $statusAfter = Get-StatusShort -RepoPath $worktreePath
    if ([string]::IsNullOrWhiteSpace($statusAfter)) {
        Write-Host "No changes produced in cycle $cycle."
        Save-LocalMetadata -WorktreePath $worktreePath -CycleNumber $cycle -BranchName $branchName -CommitSha "" -PushStatus "skipped_no_changes"
    }
    else {
        $commitMessagePath = Join-Path $stateDir "commit-message.txt"
        $commitMessage = if (Test-Path $commitMessagePath) {
            (Get-Content $commitMessagePath -Raw).Trim()
        }
        else {
            "autoloop: improvement cycle $cycle"
        }

        if ([string]::IsNullOrWhiteSpace($commitMessage)) {
            $commitMessage = "autoloop: improvement cycle $cycle"
        }

        Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $worktreePath, "add", "-A") | Out-Null
        Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $worktreePath, "commit", "-m", $commitMessage) | Out-Null
        $commitSha = (Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $worktreePath, "rev-parse", "HEAD")).Output.Trim()

        $pushStatus = "not_requested"
        if ($Push) {
            Invoke-CheckedCommand -FilePath "git" -ArgumentList @("-C", $worktreePath, "push", "-u", "origin", $branchName) | Out-Null
            $pushStatus = "pushed"
        }

        Save-LocalMetadata -WorktreePath $worktreePath -CycleNumber $cycle -BranchName $branchName -CommitSha $commitSha -PushStatus $pushStatus
        Write-Host "Committed cycle $cycle at $commitSha"
        Write-Host "Push status: $pushStatus"
    }

    if ($cycle -lt $Cycles -and $SleepSeconds -gt 0) {
        Write-Host "Sleeping for $SleepSeconds seconds before next cycle..."
        Start-Sleep -Seconds $SleepSeconds
    }
}

Write-Host ""
Write-Host "Improvement loop complete."
Write-Host "Branch: $branchName"
Write-Host "Worktree: $worktreePath"
