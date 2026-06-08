# HR Resume Ledger Workflow Skill

Codex Skill for HR resume recommendation-page scraping, full-resume detail reading, cross-industry career-experience matching, and ledger export.

## Skill link

Use this repository path as the GitHub Skill source:

```text
skills/hr-resume-ledger-workflow
```

## Install manually

Copy the skill folder to your Codex skills directory:

```powershell
Copy-Item -Recurse .\skills\hr-resume-ledger-workflow "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow" -Force
```

## One-click start after install

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow\scripts\bootstrap_hr_resume_ledger.ps1" -ProjectDir "C:\path\to\project"
```
