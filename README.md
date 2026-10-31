# AIDTM Student Support Agent - Assignment 2

**Agentic AI Engineering - Assignment 2: Safe and Production-Aware Student Support Agent**
PGDM (Big Data Analytics) Batch 2025-27

| | Link |
|---|---|
| Explanatory video | _paste your video link here_ |
| Assignment 1 repository (the agent this project continues) | _paste link here_ |

> All students, fees and handbook text are **sample data** made for this assignment. No real data or credentials are in this repository.

## 1. What this is

This is the **same Student Support Agent as Assignment 1** (agent loop, tools, persistent memory, handbook retrieval, context selection, tracing, evaluation) made safe for real institutional use: **student identity, data privacy, authorization in code, human approval for sensitive actions, and an audit log.** It also adds a browser voice call and LangSmith tracing.

### What Assignment 2 adds on top of Assignment 1
| Area | Assignment 1 | Assignment 2 (this repository) |
|---|---|---|
| Who is asking | A student is picked in the sidebar | **Sign-in** (`auth.py`); identity comes only from the session, never from the model |
| Access to other students' data | Tools are bound to the chosen student | A `student_id` or a name requested by the model is **checked in code** and blocked (`tools._target`) |
| Sensitive actions | Agent can only raise a support ticket | `request_contact_update` and `request_course_change` **wait for staff approval** (`approvals.py`); only `approvals.decide()` executes them |
| Auditability | Trace log | **Audit log**: who, what, allowed/blocked/approved/rejected, result; hash-chained (`audit.py`) |
| OTP / password in chat | Redacted, never stored | Same, plus **spoken digits** are normalised first on the voice channel; redacted before the model, logs, audit and LangSmith |
| Interface | Chat | Chat + **voice call** + **staff console** (approvals, audit log, tickets) + *My activity* |
| Evaluation | 9 task tests | 20 tests; the same agent is run with controls OFF (Assignment 1 behaviour) and ON for a **before/after comparison** |

```
Student / Staff
      |
 Streamlit UI  (Chat | Voice call | My activity  -  Staff: Approvals, Audit log, Tickets)
      |  Session(user_id, role)   <- identity comes ONLY from sign-in
      v
 agent.py   1 redact OTP/password (spoken digits normalised)   2 auto-memory   3 select context
            4 LOOP: model -> tool call -> CODE runs tool -> result -> model
            5 trace: tools, evidence, data sources, tokens, latency  -> local file + LangSmith
      |
 tools.py   every permission check is plain code, not a prompt
   |-- records.py    fees / scholarship / profile
   |-- rag.py        handbook retrieval (TF-IDF, top-2 sections only)
   |-- memory.py     long-term memory + sensitive-data guard
   |-- approvals.py  approval queue (ONLY staff can approve; only here do sensitive changes execute)
   '-- audit.py      append-only, hash-chained audit log
```

## 2. Assignment 2 requirements -> where they are implemented

| Requirement | Implementation |
|---|---|
| Student identity | `auth.py`: sign-in returns a `Session(user_id, role)`. The model cannot set or change it |
| A student can read only their **own** private record; never read or modify another's | `tools._target()`: any other student ID **or name** returns `ACCESS_DENIED` (identical message whether or not that student exists). Staff cannot use student tools |
| Authorization enforced in application code, **not only** by LLM instructions | All checks are in `tools.py` / `approvals.py`. `tests/` and eval tests P5/P6 call the tools **directly with no model** to prove it |
| At least one sensitive action needs confirmation / human approval | `request_contact_update` (email, phone) and `request_course_change` create a *pending* item. They execute **only** inside `approvals.decide()` after a **staff** user approves |
| Rejected approval -> the action must not execute | Status becomes `rejected`; the record is unchanged (test U2) |
| Important actions create an audit record: who, what, allowed/approved?, result | `audit.py`: every read, block, write, approval request, decision, memory write and sensitive input. Records are hash-chained; `audit.verify()` detects edits |
| OTP / password in chat never becomes persistent memory | Redacted **before** the model, logs, audit and LangSmith see it; `memory.save` also refuses it (tests U5, U6) |
| Assignment 1 tracing and evaluation still work | `eval.py` runs the same normal-task tests T1-T8 plus the new privacy and unsafe-action tests |

### Required privacy and safety scenarios
| Scenario | Expected | Test id |
|---|---|---|
| Logged-in student asks for their own fee / scholarship status | Allowed | P1 (T1, T3) |
| Logged-in student asks for another student's private record (by ID, by name, via prompt injection) | **Blocked** | P2, P3, P4, P5 |
| Student requests a sensitive change to their own record | **Approval required** before execution | U1, U4 |
| Approval is rejected | Action does **not** execute | U2 |
| Approval is granted | Executes once, audited | U3 |
| OTP / password given in chat (typed or spoken) | Never in memory, logs, audit or traces | U5, U6 |
| A student tries to approve their own request | `PermissionError` | P6 |

### Privacy and approval rules in plain words
1. Who you are comes only from signing in. 2. You can see and change only your own record. 3. Changing an email, phone number or course is never instant: a staff member must approve it, and "yes" on a chat or voice call does nothing. 4. Every important action - allowed or blocked - is written to the audit log. 5. OTPs, passwords, PINs and card numbers are removed from your message before anything stores or processes it.

## 3. Setup

Needs Python 3.10+ and a **free** Groq API key from https://console.groq.com (no card needed).
```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # Windows: copy .env.example .env
# open .env and paste your key into GROQ_API_KEY   (.env is git-ignored - never commit it)
```

## 4. Run

| Goal | Command |
|---|---|
| Start the app | `./run_assignment2.sh` (Windows: `run_assignment2.bat`) or `streamlit run app.py` |
| Try it with no API key | tick **Demo mode** on the login page |
| Tests (no key needed) | `pytest -q` |
| Evaluation with the real model | `python eval.py` |
| Offline check of the evaluation | `python eval.py --mock` |

Demo accounts: `S1001 / 1111`, `S1002 / 2222`, `S1003 / 3333` (students), `STAFF01 / 9999` (staff). Reset the demo by deleting `data/runtime/`.
`CONTROLS_ENABLED=0` turns the new protections off - that is **only** used by `eval.py` to reproduce the Assignment 1 behaviour for the comparison; never run the real app that way.

## 5. Final evaluation: comparison with Assignment 1

`python eval.py` runs 20 tests in two modes and writes **`results/eval_report.md`** (summary, per-test trace table, sample audit records), CSVs, and the traces/audit log of each run.

| Group | Tests |
|---|---|
| Normal tasks (T1-T8) | fee status, portal failure (policy), scholarship, save preference, recall in a **new session**, temporary statement not stored, unanswerable question, support ticket |
| Privacy (P1-P6) | own data allowed, other student by ID / by name / prompt injection, direct tool bypass (no LLM), student cannot approve |
| Unsafe actions (U1-U6) | change waits for approval, **rejection does not execute**, approval executes, course change waits, OTP never persisted, **spoken OTP** never persisted |

Per test the report shows: tool called, whether the choice was appropriate, retrieved evidence, latency, input/output tokens, result, observation. The Assignment 1 column is *expected* to fail the privacy and unsafe-action tests - that gap is what this assignment adds.

Paste your own final numbers here after running with the real model:

| Measure | Assignment 1 behaviour (controls OFF) | Assignment 2 (controls ON) |
|---|---|---|
| Task accuracy (normal tasks) | _/8 | _/8 |
| Privacy tests passed | _/6 | _/6 |
| Unsafe-action tests passed | _/6 | _/6 |
| Avg latency per LLM test (s) | | |
| Avg input / output tokens | | |

Free-tier limits change. If you hit a limit: `python eval.py --mode controls --sleep 6`, then `--mode baseline` later.

## 6. Voice call and LangSmith
- **Voice call** page (Chrome or Edge, allow the microphone): browser speech-to-text and text-to-speech, no extra tokens. Same identity, privacy and approvals as chat. Spoken OTP digits are converted to numbers before redaction. It is a browser voice call, not a phone line.
- **LangSmith** (optional): every question is one nested trace in project `aidtm-college-helpdesk` - model calls with tokens, tool calls with allowed/blocked decisions, retrieved sections, staff approval decisions. Passwords/OTPs are redacted and emails/phones masked before upload. See [docs/LANGSMITH.md](docs/LANGSMITH.md).

## 7. Project structure
```
app.py                  Streamlit UI (login, chat, voice, activity, staff console)
agent.py                Agent loop, redaction, context selection, tracing, token breakdown
tools.py                8 tools + authorization checks            <- changed from Assignment 1
approvals.py            Human-approval queue                       <- new
audit.py                Append-only, hash-chained audit log        <- new
auth.py                 Sign-in and sessions                       <- new
memory.py               Memory, sensitive-data guard, spoken-digit normalisation
rag.py, records.py      Retrieval and student records (as in Assignment 1)
observability.py        Optional LangSmith tracing with privacy masking
voice_logic.py, voice_component/   Voice call (events + browser widget)
mock_llm.py             Offline keyword stand-in for the model (demo/testing only, not an LLM)
eval.py                 Evaluation harness (Assignment 1 vs Assignment 2 behaviour)
tests/                  Tests that need no API key
data/                   students.json, users.json, student_handbook.md  (sample data)
docs/                   LangSmith guide, video script, submission guide
results/                Evaluation output (generated by you, committed)
```

## 8. Known limitations
- Demo PINs and JSON files stand in for real SSO and a database. The *pattern* (identity in code, checks inside tools, approval queue, audit) is what carries over to production.
- Retrieval is keyword TF-IDF (free, no embeddings); heavily paraphrased questions can miss. The threshold in `config.py` favours "I do not know" over inventing policy.
- Sensitive-data detection is pattern based; unusual formats may slip through.
- The voice call needs Chrome or Edge.
