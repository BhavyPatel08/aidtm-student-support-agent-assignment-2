"""Agent loop: the model decides which tool to call, code executes it (with permission
checks), the result goes back to the model, and a final answer is produced.
Every run produces a trace (tools, evidence, data sources, tokens, latency) that is saved
locally and - if LangSmith is on - sent there as one nested trace per question."""
import datetime
import json
import time
import uuid

import audit
import config
import memory
import observability as obs
import tools

SYSTEM_PROMPT = """You are the AIDTM Student Support Agent. Signed-in student: {name} ({sid}). Today: {today}.
Rules:
- For any student-specific data or policy question, call a tool. Never guess fees, scholarship status or policy.
- For rules/policy questions call search_policy and answer ONLY from the returned text. If nothing relevant is returned, say you do not have that information and offer a support request.
- You can only access the signed-in student's own data.
- Course or contact-detail changes need staff approval: call the request tool, then say it is PENDING approval and give the action id. Never say it is done.
- Never ask for or repeat OTPs, passwords or PINs. Use remember only for durable preferences.
- Be concise and use simple English."""

VOICE_STYLE = ("This is a live VOICE call. Reply in at most 2 short spoken sentences. No markdown, no lists, "
               "no symbols. Say amounts as 'rupees' in words. Never read out ID numbers digit by digit unless asked.")


# ------------------------------------------------------------------ token / source helpers
def _est(text: str) -> int:
    return max(1, len(text or "") // 4)


def input_token_split(messages: list, prompt_tokens: int) -> dict:
    """ESTIMATE where the input tokens of one model call went (chars/4, scaled to the real total)."""
    sizes = {"system_prompt": 0, "memory": 0, "chat_history": 0, "current_question": 0,
             "tool_calls": 0, "tool_results": 0, "tool_schemas": _est(json.dumps(tools.TOOL_SCHEMAS))}
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    for i, m in enumerate(messages):
        text = m.get("content") or ""
        if m["role"] == "system":
            key = "memory" if text.startswith("Remembered") else "system_prompt"
        elif m["role"] == "user":
            key = "current_question" if i == last_user else "chat_history"
        elif m["role"] == "assistant":
            key = "tool_calls" if i > last_user else "chat_history"
            text += json.dumps(m.get("tool_calls") or "")
        else:
            key = "tool_results"
        sizes[key] += _est(text)
    total = sum(sizes.values()) or 1
    scale = (prompt_tokens / total) if prompt_tokens else 1
    return {k: round(v * scale) for k, v in sizes.items() if v}


def data_sources(steps: list, policy_ids: list, memory_keys: list) -> list:
    """Human-readable list of WHERE the answer's facts came from."""
    out = []
    for st in steps:
        src = tools.TOOL_SOURCES.get(st["tool"], st["tool"])
        if st["tool"] == "search_policy":
            src = ("student_handbook.md#" + ",".join(dict.fromkeys(policy_ids))) if policy_ids \
                else "student_handbook.md (no relevant section found)"
        if st["decision"] == "blocked":
            src += " [BLOCKED]"
        if src not in out:
            out.append(src)
    out += [f"memory.json#{k}" for k in memory_keys]
    return out or ["model_only (no tool, document or memory used)"]


def _llm_outputs(resp) -> dict:
    """OpenAI-style output + usage_metadata, which LangSmith turns into its token counters."""
    msg = resp.choices[0].message
    calls = getattr(msg, "tool_calls", None) or []
    out = {"choices": [{"message": {"role": "assistant", "content": msg.content or "", "tool_calls": [
        {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
        for c in calls]}}], "model": config.MODEL}
    usage = getattr(resp, "usage", None)
    if usage:
        out["usage_metadata"] = {"input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                                 "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                                 "total_tokens": getattr(usage, "total_tokens", 0) or 0}
    return out


class SupportAgent:
    def __init__(self, session, client=None):
        self.session = session
        self.history = []  # only final user/assistant text is kept (compact context)
        self.thread_id = str(uuid.uuid4())  # groups all turns of one conversation in LangSmith "Threads"
        if client is None:
            if not config.GROQ_API_KEY:
                raise RuntimeError("GROQ_API_KEY missing. Copy .env.example to .env and add your free Groq key.")
            from groq import Groq
            client = Groq(api_key=config.GROQ_API_KEY)
        self.client = client

    # ---------------------------------------------------------------- LLM call
    def _call_llm(self, messages, call_no=1):
        kwargs = dict(model=config.MODEL, messages=messages, tools=tools.TOOL_SCHEMAS,
                      tool_choice="auto", temperature=0, max_tokens=900)
        if config.MODEL.startswith("openai/gpt-oss"):
            kwargs["extra_body"] = {"reasoning_effort": "low"}  # fewer tokens on the free tier
        with obs.span("groq_chat_completion", "llm",
                      inputs={"messages": messages, "available_tools": [t["function"]["name"] for t in tools.TOOL_SCHEMAS]},
                      tags=["llm", "groq"],
                      metadata={"ls_provider": "groq", "ls_model_name": config.MODEL, "call_no": call_no,
                                "temperature": 0}) as sp:
            last = None
            for attempt in range(4):
                try:
                    resp = self.client.chat.completions.create(**kwargs)
                    break
                except Exception as exc:
                    last, text = exc, str(exc).lower()
                    if "429" in text or "rate" in text:
                        time.sleep(min(3 * 2 ** attempt, 30))
                        continue
                    if "tool_use_failed" in text or "failed to call a function" in text:
                        continue  # malformed tool call from the model: simply retry
                    raise
            else:
                raise RuntimeError(f"LLM call failed after retries: {last}")
            out = _llm_outputs(resp)
            usage = out.get("usage_metadata", {})
            sp.end(outputs=out, metadata={"input_token_split_estimate": input_token_split(messages, usage.get("input_tokens", 0))})
        return resp

    # ---------------------------------------------------------------- main entry
    def chat(self, user_text: str, channel: str = "text", tags=None, metadata=None) -> dict:
        t0 = time.perf_counter()
        s = self.session
        flags = []

        # 1. Spoken digits -> digits, then sensitive input is redacted BEFORE anything is stored,
        #    traced or sent to the model.
        if channel == "voice":
            user_text = memory.normalize_spoken(user_text)
        clean = user_text.strip()
        sensitive = memory.contains_sensitive(clean)
        note = None
        if sensitive and config.CONTROLS_ENABLED:
            clean = memory.redact(clean)
            flags.append("sensitive_input_redacted")
            audit.log(s.user_id, s.role, "sensitive_input", "redacted",
                      "credential-like text removed; not stored, not sent to the model", {"types": sensitive, "channel": channel})
            note = ("The student shared a credential (OTP/password/PIN/card). It was removed. "
                    "Do not store or repeat it. Tell them never to share such details with anyone.")

        run_tags = ["student-support", f"channel:{channel}", f"controls:{'on' if config.CONTROLS_ENABLED else 'off'}"] + list(tags or [])
        run_meta = {"user_id": s.user_id, "role": s.role, "channel": channel, "thread_id": self.thread_id,
                    "controls_enabled": config.CONTROLS_ENABLED, "model": config.MODEL,
                    "sensitive_input_redacted": bool(sensitive and config.CONTROLS_ENABLED), **(metadata or {})}

        with obs.span("support_agent_turn", "chain", inputs={"question": clean, "channel": channel},
                      tags=run_tags, metadata=run_meta) as root:
            trace = self._run_turn(clean, channel, flags, note, t0)
            trace["langsmith_run_id"] = root.run_id
            root.end(outputs={
                "answer": trace["answer"], "data_sources": trace["sources"], "tools_used": trace["tools_used"],
                "policy_sections": trace["evidence"]["policy"], "memory_used": trace["evidence"]["memory"],
                "tokens": trace["tokens"], "token_breakdown": trace["token_breakdown"],
                "llm_calls": trace["llm_calls"], "latency_s": trace["latency_s"],
                "flags": trace["flags"], "approvals_pending": trace["approvals_pending"],
            }, metadata={"total_tokens": trace["tokens"]["total"], "sources": trace["sources"]})

        with config.runtime_path("traces.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
        return trace

    # ---------------------------------------------------------------- one turn
    def _run_turn(self, clean, channel, flags, note, t0) -> dict:
        s = self.session
        steps, token_breakdown = [], []
        tokens = {"input": 0, "output": 0, "total": 0}
        evidence = {"policy": [], "memory": []}
        tools_used, approvals_pending = [], []

        # 2. Deterministic memory capture (same guard as the remember tool).
        for key, value in memory.extract_candidates(clean):
            result, info = tools.execute(s, "remember", {"key": key, "value": value})
            steps.append({"tool": "remember", "auto": True, "args": {"key": key}, "decision": info["decision"],
                          "result": json.dumps(result)[:200]})

        # 3. Context selection: only memory relevant to THIS question goes to the model.
        with obs.span("memory_lookup", "retriever", inputs={"query": clean}, tags=["memory"],
                      metadata={"data_source": "memory.json"}) as ms:
            relevant = memory.select_relevant(s.user_id, clean)
            ms.end(outputs={"documents": [{"page_content": f"{k} = {v}", "metadata": {"source": "memory.json", "key": k}}
                                          for k, v in relevant.items()]})
        evidence["memory"] = sorted(relevant)

        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(
            name=s.name, sid=s.user_id, today=datetime.date.today().isoformat())}]
        if channel == "voice":
            messages.append({"role": "system", "content": VOICE_STYLE})
        if relevant:
            messages.append({"role": "system", "content": "Remembered about this student: "
                             + "; ".join(f"{k}={v}" for k, v in relevant.items())})
        if note:
            messages.append({"role": "system", "content": note})
        messages += self.history[-config.HISTORY_MESSAGES:]
        messages.append({"role": "user", "content": clean})

        # 4. Agent loop.
        answer, llm_calls = "", 0
        for _ in range(config.MAX_TOOL_STEPS):
            resp = self._call_llm(messages, call_no=llm_calls + 1)
            llm_calls += 1
            usage = getattr(resp, "usage", None)
            call_in = (getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
            call_out = (getattr(usage, "completion_tokens", 0) or 0) if usage else 0
            if usage:
                tokens["input"] += call_in
                tokens["output"] += call_out
                tokens["total"] += getattr(usage, "total_tokens", 0) or 0
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            token_breakdown.append({
                "call": llm_calls, "input": call_in, "output": call_out,
                "purpose": ("asked for tool: " + ", ".join(c.function.name for c in calls)) if calls else "final answer",
                "input_split_estimate": input_token_split(messages, call_in)})
            if not calls:
                answer = (msg.content or "").strip()
                break
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                t1 = time.perf_counter()
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                if args is None:
                    result, info = {"error": "INVALID_ARGUMENTS", "message": "Arguments were not valid JSON."}, {"decision": "error"}
                else:
                    result, info = tools.execute(s, c.function.name, args)
                tools_used.append(c.function.name)
                for ev in info.get("evidence", []):
                    evidence["policy"].append(ev["id"])
                if info.get("approval_id"):
                    approvals_pending.append(info["approval_id"])
                logged_args = {k: v for k, v in args.items() if not (c.function.name == "remember" and k == "value")} if isinstance(args, dict) else args
                steps.append({"tool": c.function.name, "args": logged_args, "decision": info["decision"],
                              "ms": round((time.perf_counter() - t1) * 1000),
                              "result": json.dumps(result, ensure_ascii=False)[:240]})
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": json.dumps(result, ensure_ascii=False)})
        else:
            flags.append("step_limit_reached")
            answer = "Sorry, I could not finish this request. Please try again or raise a support request."

        # 5. Deterministic safety net: a pending approval must always be visible to the student.
        for aid in approvals_pending:
            if aid not in answer:
                answer += f"\n\nYour request {aid} is pending staff approval. Nothing has been changed yet."

        self.history += [{"role": "user", "content": clean}, {"role": "assistant", "content": answer}]

        return {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"), "user": s.user_id,
            "question": clean, "answer": answer, "tools_used": tools_used, "steps": steps,
            "evidence": evidence, "sources": data_sources(steps, evidence["policy"], evidence["memory"]),
            "approvals_pending": approvals_pending, "flags": flags,
            "llm_calls": llm_calls, "tokens": tokens, "token_breakdown": token_breakdown, "model": config.MODEL,
            "controls": config.CONTROLS_ENABLED, "channel": channel, "thread_id": self.thread_id,
            "latency_s": round(time.perf_counter() - t0, 2),
        }
