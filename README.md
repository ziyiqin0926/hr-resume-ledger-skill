# HR Resume Ledger 1:1 App + Codex Skill

This repository now contains the **complete HR resume ledger app** plus the Codex Skill workflow.

It is intended for 1:1 deployment on another Windows computer: same page, same local app logic, same export workflow.

Current UI includes a recruitment platform switcher: 智联招聘 / BOSS直聘 / 猎聘 / 通用页面.

For Zhilian candidates, matched resumes are traced to the platform's own **存至本地** PDF flow and saved per candidate under local runtime data; the ledger previews the candidate's PDF first and falls back to text only when PDF generation fails.

## Contents

```text
hr_resume_ledger/                         # complete runnable app
  app.py                                  # local Python server + scraping/matching/export logic
  static/index.html                       # exact browser UI
  tests/                                  # regression tests
skills/hr-resume-ledger-workflow/         # Codex Skill
  SKILL.md
  scripts/bootstrap_hr_resume_ledger.ps1
```

## Requirements on another Windows computer

- Windows + PowerShell
- Google Chrome
- Python available as `python` if running from source
- Codex if you want to use the Skill workflow
- Manual login to recruiting websites is still required
- Platform sessions, cookies and anti-bot checks are handled by the user's own browser login state; the app does not bypass verification.

The local app itself mainly uses Python standard library. Tests require `pytest`.

## Run from source \(recommended; this is the 1:1 page\)

```powershell
git clone https://github.com/ziyiqin0926/hr-resume-ledger-skill.git
cd hr-resume-ledger-skill\hr_resume_ledger
python app.py
```

Open:

```text
http://127.0.0.1:8765/
```

## Run with Skill bootstrap

After installing the skill, point `-ProjectDir` to this repository root:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow\scripts\bootstrap_hr_resume_ledger.ps1" -ProjectDir "C:\path\to\hr-resume-ledger-skill"
```

## Install Codex Skill manually

```powershell
Copy-Item -Recurse .\skills\hr-resume-ledger-workflow "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow" -Force
```

GitHub Skill path:

```text
skills/hr-resume-ledger-workflow
```

## Runtime data intentionally not included

For privacy/security, this repository does not include:

- browser login profiles
- local SQLite ledger data
- cookies/session state
- candidate exports generated locally

These are regenerated on each computer under `hr_resume_ledger/data/`.

## Validation

```powershell
cd hr_resume_ledger
python -m py_compile app.py
python -m pytest -q
```

