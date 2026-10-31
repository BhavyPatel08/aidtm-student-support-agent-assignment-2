"""Offline stand-in for the model (keyword rules, NOT an LLM).
Used only by `python eval.py --mock` to verify the pipeline without spending API tokens."""
import json
import re
from types import SimpleNamespace as NS


def _resp(content=None, calls=None, prompt_text=""):
    tcs = [NS(id=f"m{i}", function=NS(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls or [])]
    pt = max(len(prompt_text) // 4, 1)
    return NS(choices=[NS(message=NS(content=content, tool_calls=tcs or None))],
              usage=NS(prompt_tokens=pt, completion_tokens=30, total_tokens=pt + 30))


def _final(tool_json: dict) -> str:
    if tool_json.get("error") == "ACCESS_DENIED":
        return "Sorry, I can only show your own record."
    if tool_json.get("error"):
        return "I could not complete that: " + tool_json.get("message", "error")
    if tool_json.get("status") == "APPROVAL_REQUIRED":
        return f"Your request {tool_json['action_id']} is pending staff approval. Nothing has changed yet."
    if "ticket_id" in tool_json:
        return f"I raised support request {tool_json['ticket_id']}. Expect a reply in 2 working days."
    if "fees" in tool_json:
        f = tool_json["fees"]
        return (f"Status: {f['status']}. Outstanding Rs. {f['outstanding']}. "
                f"Installment {f['next_installment']['number']} of Rs. {f['next_installment']['amount']} is due {f['next_installment']['due_date']}.")
    if "scholarship" in tool_json:
        s = tool_json["scholarship"]
        return f"{s['name']}: {s['status']}."
    if "results" in tool_json:
        if not tool_json["results"]:
            return "I don't have that information in the handbook. I can raise a support request for you."
        return tool_json["results"][0]["text"]
    return "Done."


class MockClient:
    def __init__(self):
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        msgs = kw["messages"]
        prompt = json.dumps(msgs)
        last = msgs[-1]
        if last["role"] == "tool":
            return _resp(_final(json.loads(last["content"])), prompt_text=prompt)
        q = last["content"]
        ql = q.lower()
        memo = next((m["content"] for m in msgs if m["role"] == "system" and m["content"].startswith("Remembered")), "")
        if memo and "contact" in ql:
            return _resp("You prefer: " + memo.split(": ", 1)[1], prompt_text=prompt)
        if "remember" in ql:
            return _resp("Noted.", prompt_text=prompt)
        if "[redacted" in ql:
            return _resp("Please never share OTPs or passwords with anyone.", prompt_text=prompt)
        target = re.search(r"\bS\d{4}\b", q)
        if "scholarship" in ql:
            args = {"student_id": "Aarav Shah"} if "aarav" in ql else {}
            return _resp(calls=[("get_scholarship_status", args)], prompt_text=prompt)
        if "fee status" in ql or ("fee" in ql and target) or "record" in ql:
            return _resp(calls=[("get_fee_status", {"student_id": target.group(0)} if target else {})], prompt_text=prompt)
        if "phone" in ql:
            return _resp(calls=[("request_contact_update", {"field": "phone", "new_value": "+91 98888 77777"})], prompt_text=prompt)
        if "email" in ql:
            return _resp(calls=[("request_contact_update", {"field": "email", "new_value": "bhavy.new@example.edu"})], prompt_text=prompt)
        if "replace" in ql or "elective" in ql:
            return _resp(calls=[("request_course_change", {"current_course": "HR Analytics", "new_course": "Deep Learning", "reason": "career goals"})], prompt_text=prompt)
        if "support request" in ql and "raise" in ql:
            return _resp(calls=[("create_support_request", {"category": "fees", "description": q})], prompt_text=prompt)
        focus = [p.strip() for p in re.split(r"(?<=[.?!])\s+", q) if p.strip()][-1]
        return _resp(calls=[("search_policy", {"query": focus})], prompt_text=prompt)
