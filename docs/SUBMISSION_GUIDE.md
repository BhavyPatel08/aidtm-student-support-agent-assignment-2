# Submission guide - Assignment 2

Required: **public GitHub repository + explanatory video**. No API keys in the repository.
Assignment 2 continues the Assignment 1 agent. It is a separate repository so each assignment can be submitted on its own, and this README lists what was added.

## Step 1 - Run everything once (30 min)
```bash
pip install -r requirements.txt
cp .env.example .env            # add your free Groq key (never commit this file)
pytest -q                       # expect: all tests pass, no key needed
python eval.py                  # real model; compares Assignment 1 behaviour with Assignment 2 -> results/eval_report.md
```
Open `results/eval_report.md`. The summary table has two columns: *Assignment 1 behaviour (controls OFF)* and *Assignment 2 (controls ON)*. These are your real numbers for the final comparison. Honest failures are fine - explain them. Paste the table into the "Final evaluation" section of `README.md`.
(If you also ran Assignment 1's own `eval.py`, you can quote its accuracy and latency as the Assignment 1 reference.)
Optional but recommended: set up LangSmith first (docs/LANGSMITH.md) so the evaluation traces, including blocked access and approvals, appear in your project.

## Step 2 - Put the code on GitHub
1. Create a new repository (suggested name `aidtm-student-support-agent-assignment-2`) -> **Public** -> do NOT tick "Add a README".
2. In the project folder:
```bash
git init
git add .
git status                      # CHECK: .env and data/runtime/ must NOT be listed
git commit -m "Assignment 2 - Safe and production-aware Student Support Agent"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```
3. Open the link in a **private/incognito window**; if you can see the code it is public.
4. Search the repository for your keys (`gsk_`, `lsv2_`): nothing should be found. If a key was ever committed, **delete it on the provider's website and create a new one**.

## Step 3 - Record the video (11-12 minutes)
Follow `docs/VIDEO_SCRIPT.md`. It must clearly demonstrate: student-data privacy, authorization, restricted access, approval for sensitive actions, and auditability, plus architecture, agent flow, tools, memory/retrieval/context, tracing, accuracy, latency and token usage. Use two browser windows (student and staff). Do not show `.env`. Upload as YouTube **Unlisted** or Google Drive "Anyone with the link"; test the link in incognito.

## Step 4 - Final checklist
- [ ] Repository is public and opens in incognito
- [ ] `.env` and `data/runtime/` are not in the repository; no key anywhere
- [ ] README has setup + run steps, the privacy/approval rules and your own final evaluation table
- [ ] `results/eval_report.md` is committed (your real run)
- [ ] Video link works in incognito, audio is clear
- [ ] Video shows: own data allowed, other student blocked (ID, name, injection), approval required, rejection does not execute, approval executes, OTP/password never stored, audit log, evaluation vs Assignment 1, code walkthrough
