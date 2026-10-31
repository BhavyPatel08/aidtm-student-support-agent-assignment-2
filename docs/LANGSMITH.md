# LangSmith tracing - setup and how to read it

Project name used everywhere: **`aidtm-college-helpdesk`** (created automatically on the first trace).

## 1. Turn it on (2 minutes)
1. Sign in at https://smith.langchain.com -> **Settings -> API Keys -> Create API Key**. Copy it.
2. Open your `.env` (never commit it) and set:
```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<paste your key>
LANGSMITH_PROJECT=aidtm-college-helpdesk
LANGSMITH_ENDPOINT=https://api.smith.langchain.com      # EU accounts: https://eu.api.smith.langchain.com
LANGSMITH_MASK_PII=1
```
(The older `LANGCHAIN_API_KEY / LANGCHAIN_PROJECT / LANGCHAIN_TRACING_V2` names from the College desk project also work.)
3. `pip install -r requirements.txt`, run the app, and look at the sidebar: it must say **LangSmith ON** and `Tracing to project: aidtm-college-helpdesk`. If it says *LangSmith off*, the line below it tells you why (missing key, tracing not `true`).
4. Ask a question, then open LangSmith -> **Tracing -> aidtm-college-helpdesk**. A run appears within a few seconds.

## 2. What one question looks like (1 question = 1 trace)
```
support_agent_turn              question, final answer, DATA SOURCES, total tokens, latency, flags
 |- memory_lookup               retriever  -> which saved memory items were used (memory.json#key)
 |- groq_chat_completion  #1    llm        -> exact messages sent, tool the model asked for, input/output tokens
 |- tool:get_fee_status         tool       -> arguments, allowed/BLOCKED, data returned, source students.json#fees
 |- tool:search_policy          retriever  -> handbook sections returned, with score (e.g. HB-02)
 '- groq_chat_completion  #2    llm        -> final answer, input/output tokens
```
Staff decisions appear as separate traces named `staff_approval_decision` (who approved/rejected, final status).

## 3. "Where did this answer come from?"
- Root run -> **Outputs -> `data_sources`**, e.g. `students.json#fees`, `student_handbook.md#HB-02`, `memory.json#preferred_contact`.
  `model_only (no tool, document or memory used)` means the model answered without any data - a red flag for fee/policy questions.
  `[BLOCKED]` means a tool tried to read data it was not allowed to.
- Open `tool:search_policy` -> the retrieved documents with `section`, `title`, `score`.
- Open `tool:get_*` -> metadata `data_source` and `decision` (allowed / blocked).
- Open the first `groq_chat_completion` -> **Input** shows the exact context the model received (system prompt, only-relevant memory, last 2 turns, your question).

## 4. "Where were my tokens used?"
- Runs table: the **Tokens** column per trace (and per child run). Each `groq_chat_completion` run reports input/output tokens from Groq's own `usage` numbers.
- Root run -> Outputs -> **`token_breakdown`**: one row per model call (purpose: "asked for tool: ..." / "final answer"), input, output.
- Each model call -> Metadata -> **`input_token_split_estimate`**: *estimated* split of the input tokens into `system_prompt`, `tool_schemas`, `memory`, `chat_history`, `current_question`, `tool_calls`, `tool_results`. (Estimate = characters / 4, scaled to the real total. Totals are exact; the split is approximate.)
- Typical finding to mention in your video: most input tokens are the fixed system prompt + tool definitions, and the second model call is larger because it also carries the tool result.
- The same table is shown in the app: **Trace details** under every answer.

## 5. Filtering and grouping
| Want | Do |
|---|---|
| One whole conversation | **Threads** view (metadata `thread_id`) |
| Only voice calls | Filter tag `channel:voice` |
| Assignment 1 vs 2 behaviour | Tag `controls:off` / `controls:on` |
| Blocked data access | Metadata `decision` = `blocked` |
| One student | Metadata `user_id` = `S1001` |
| Evaluation runs | Tags `eval-baseline` / `eval-controls` plus the test id (`T1`..`U6`) after `python eval.py` |
| Approval decisions | Run name `staff_approval_decision` |

## 6. Privacy (matters for Assignment 2)
Before anything is uploaded: OTP / password / PIN / CVV / card / Aadhaar patterns are **always redacted**; emails become `b***@example.edu` and phone numbers `**********0001` (set `LANGSMITH_MASK_PII=0` to disable the last two). Spoken OTPs are converted to digits and redacted first. Tests in `tests/test_observability.py` capture exactly what would be uploaded and prove none of this leaks.
The sample data is fictional, but this is the habit to follow with real student data.

## 7. Safe by design
- Tracing is off unless `LANGSMITH_TRACING=true` **and** a key is set.
- If LangSmith is down, blocked, or the key is wrong, the app keeps working at normal speed (verified with an unreachable endpoint).
- Traces are uploaded in the background. For short scripts (`eval.py`) the code flushes at the end.

## 8. Troubleshooting
| Symptom | Fix |
|---|---|
| Sidebar says "LangSmith off" | Read the reason line; set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`, restart the app |
| No runs in LangSmith | Check the project name (top of the Tracing page) and workspace; EU users need the EU endpoint; wait ~10 s |
| Console shows `Failed to multipart ingest runs` | Network blocked or wrong endpoint/key; the app still works |
| `401/403` | Create a new API key |
| Hitting trace limits | The free plan has a monthly trace limit (check your plan). One question = one trace; set `LANGSMITH_TRACING=false` when not demoing |

## 9. Add this to your videos (1 minute)
**Assignment 1 - Tracing section:** run the eval or ask 2-3 questions, switch to LangSmith -> project `aidtm-college-helpdesk`. Open one trace: show the tree, click `tool:search_policy` (retrieved HB-02 + score), click a `groq_chat_completion` (messages in, tokens out), show `data_sources` and `token_breakdown`. Say: "this is how I can prove where each answer came from and where every token went."
**Assignment 2 - Safety section:** open the blocked trace (`decision = blocked`, `[BLOCKED]` in data sources, no other student's data in it), show the masked email/phone, show that the OTP trace only contains `[REDACTED:otp]`, and open a `staff_approval_decision` trace.
