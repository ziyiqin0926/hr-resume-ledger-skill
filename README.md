# HR Resume Ledger Workflow Skill

Codex Skill for HR resume recommendation-page scraping, full-resume detail reading, cross-industry career-experience matching, and ledger export.

## Important: what this repo contains

This repository contains the **Codex Skill workflow**, not the full HR ledger application source.

The one-click script expects the target computer already has a project folder containing:

```text
hr_resume_ledger/app.py
hr_resume_ledger/static/index.html
```

If the other computer does not have that app project, this skill can guide Codex, but the bootstrap script cannot start the app.

## Requirements on another Windows computer

- Windows + PowerShell
- Python available as `python`
- Google Chrome installed, or `chrome.exe` available in PATH
- Codex installed and able to load local skills
- The HR ledger app project copied/cloned to that computer
- Recruiting website login must be done manually in the browser

The current app uses Python standard library only for the local server. Tests require `pytest` if you want to run them.

## Install manually

Copy this folder to Codex skills:

```powershell
Copy-Item -Recurse .\skills\hr-resume-ledger-workflow "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow" -Force
```

## One-click start after install

Point `-ProjectDir` to the folder that contains `hr_resume_ledger`:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow\scripts\bootstrap_hr_resume_ledger.ps1" -ProjectDir "C:\path\to\project"
```

## GitHub Skill path

```text
skills/hr-resume-ledger-workflow
```

## Known limits

- This skill does not bypass login, verification, anti-bot, or website permissions.
- It relies on the local HR ledger app implementation being present.
- Cross-site page structure may change; if scraping breaks, use Codex with this skill to inspect and patch the app.
