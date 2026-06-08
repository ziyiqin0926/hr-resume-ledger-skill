---
name: hr-resume-ledger-workflow
description: Use when building, deploying, or operating the HR resume ledger workflow for recruiting pages, semantic candidate matching, resume detail scraping, export table formatting, or one-click setup across Windows devices.
---

# HR Resume Ledger Workflow

Use this skill for the `hr_resume_ledger` app: recruiting recommendation pages, full resume detail collection, cross-industry semantic screening, and export table optimization.

## Default workflow

1. Locate the project folder containing `hr_resume_ledger/app.py`.
2. Start the local app on `http://127.0.0.1:8765/`.
3. Open Chrome to the app.
4. Select the recruitment platform in the app (智联招聘 / BOSS直聘 / 猎聘 / 通用页面), open the controlled recruiting browser, log in manually if needed, then navigate to the recommendation/candidate page.
5. Treat user input as **job requirements and related career-experience scope**, not literal keywords.
6. Evaluate candidates by:
   - full recommendation pool total `N` (default sample limit: 500);
   - opening each plausible candidate detail page;
   - extracting phone, email, WeChat, age, gender, education, status, basic info, related experience;
   - prioritizing related role / career-experience matching;
   - treating age, phone, and education as profile data unless the user explicitly says they are required;
   - reporting matched count `M` and match rate `M/N`.
7. Export table priority columns:
   - name, phone, work-experience match score, match explanation, related experience, then contact/basic fields.

## Matching rules

- This workflow is industry-agnostic. For any industry, interpret the user's input as role requirements plus related career-experience scope, then map it to common real-world job-description language for that industry.
- Do not count a candidate as matched only because a literal keyword appears.
- Main purpose: find candidates with related role / career experience and summarize them into a readable ledger.
- Age, phone, and education should not exclude candidates unless the user explicitly says "must".
- Export wording should be concise: age is just age; basic profile should show personal facts, not page noise such as recent delivery time.
- Related-experience matching must be cross-industry, not limited to one sector. Match against common public job-description language, not a few literal words. Map role requirements to equivalent work experience, e.g. sales may include BD/customer development/signing, backend may include API/REST/database work, operations may include user/content/community/data work.
- Unknown or missing hard data should be marked as missing, not silently accepted.

## One-click Windows start

Run:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\hr-resume-ledger-workflow\scripts\bootstrap_hr_resume_ledger.ps1" -ProjectDir "C:\path\to\project"
```

The script checks `hr_resume_ledger/app.py`, starts the local app, and opens Chrome.

## Validation

Before saying done:

```powershell
cd hr_resume_ledger
python -m py_compile app.py
python -m pytest -q
```

