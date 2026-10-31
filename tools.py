"""Tools the agent can call. EVERY permission check lives here, in plain code.
The model can ask for anything - the code decides what actually happens."""
import datetime
import json
import re

import approvals
import audit
import config
import memory
import observability as obs
import rag
import records

CATEGORIES = {"fees", "scholarship", "course", "technical", "other"}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_student_record",
        "description": "Get the signed-in student's profile: programme, batch, email, phone, courses.",
        "parameters": {"type": "object", "properties": {"student_id": {"type": "string", "description": "Optional; defaults to the signed-in student."}}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_fee_status",
        "description": "Get fee status: total, paid, outstanding, next installment and due date.",
        "parameters": {"type": "object", "properties": {"student_id": {"type": "string", "description": "Optional; defaults to the signed-in student."}}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_scholarship_status",
        "description": "Get scholarship name, status and amount.",
        "parameters": {"type": "object", "properties": {"student_id": {"type": "string", "description": "Optional; defaults to the signed-in student."}}, "required": []}}},
    {"type": "function", "function": {
        "name": "search_policy",
        "description": "Search the student handbook for rules and policies (fees, late fee, portal failure, scholarships, course change, attendance, privacy).",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "create_support_request",
        "description": "Create a support ticket for the signed-in student.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string", "enum": sorted(CATEGORIES)},
            "description": {"type": "string"}}, "required": ["category", "description"]}}},
    {"type": "function", "function": {
        "name": "request_course_change",
        "description": "Request replacing one elective with another. Needs staff approval; does not change anything immediately.",
        "parameters": {"type": "object", "properties": {
            "current_course": {"type": "string"}, "new_course": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["current_course", "new_course", "reason"]}}},
    {"type": "function", "function": {
        "name": "request_contact_update",
        "description": "Request a change of registered email or phone. Needs staff approval; does not change anything immediately.",
        "parameters": {"type": "object", "properties": {
            "field": {"type": "string", "enum": ["email", "phone"]}, "new_value": {"type": "string"}},
            "required": ["field", "new_value"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Save a durable preference or fact for future sessions. Keys: programme, preferred_contact, preferred_language, preferred_name, study_interest. Never for temporary or sensitive information.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}}},
]


# ------------------------------------------------------------------ helpers
def _mask(value: str) -> str:
    return "*" * max(len(value) - 4, 0) + value[-4:]


def _target(session, args: dict, action: str):
    """Decide whose record a read applies to. Returns (student_id, error_dict)."""
    requested = str(args.get("student_id") or "").strip()
    if config.CONTROLS_ENABLED and session.role != "student":
        audit.log(session.user_id, session.role, action, "blocked", "role not allowed to use student tools")
        return None, {"error": "ACCESS_DENIED", "message": "This tool is for students only."}
    if not requested:
        return session.user_id, None
    ident = records.resolve(requested)
    if ident == session.user_id:
        return ident, None
    if not config.CONTROLS_ENABLED:  # Assignment-1 baseline: no privacy layer
        return (ident, None) if ident else (None, {"error": "NOT_FOUND", "message": "No such student."})
    # Same response whether or not the other student exists (no information leak).
    audit.log(session.user_id, session.role, action, "blocked",
              "ACCESS_DENIED: not the signed-in student's own record", {"requested_target": requested})
    return None, {"error": "ACCESS_DENIED", "message": "You can only access your own record."}


def _reader(action: str, build):
    def handler(session, args):
        tid, err = _target(session, args, action)
        if err:
            return err, {"decision": "blocked" if err["error"] == "ACCESS_DENIED" else "error"}
        rec = records.get(tid)
        audit.log(session.user_id, session.role, action, "allowed", "data returned", {"target": tid})
        return {"student_id": tid, **build(rec)}, {"decision": "allowed"}
    return handler


_get_record = _reader("read_student_record", lambda r: {
    "name": r["name"], "programme": r["programme"], "batch": r["batch"],
    "email": r["email"], "phone": r["phone"], "courses": r["courses"]})
_get_fees = _reader("read_fee_status", lambda r: {"fees": r["fees"]})
_get_scholarship = _reader("read_scholarship_status", lambda r: {"scholarship": r["scholarship"]})


# ------------------------------------------------------------------ tools
def _search_policy(session, args):
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "MISSING_INFO", "message": "Provide a search query."}, {"decision": "error"}
    hits = rag.search(query)
    if not hits:
        return ({"results": [], "message": "No relevant policy text found."},
                {"decision": "allowed", "evidence": []})
    return (
        {"results": [{"id": h["id"], "title": h["title"], "text": h["text"]} for h in hits]},
        {"decision": "allowed", "evidence": [{"id": h["id"], "score": round(h["score"], 3)} for h in hits]},
    )


def _tickets_path():
    return config.runtime_path("tickets.json")


def _create_support_request(session, args):
    category = str(args.get("category", "other")).lower()
    category = category if category in CATEGORIES else "other"
    description = memory.redact(str(args.get("description", "")).strip())
    if len(description) < 5:
        return {"error": "MISSING_INFO", "message": "Ask the student to describe the problem."}, {"decision": "error"}
    p = _tickets_path()
    tickets = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    tid = f"TKT-{len(tickets) + 1:04d}"
    tickets.append({"ticket_id": tid, "student": session.user_id, "category": category,
                    "description": description, "status": "open",
                    "created": datetime.datetime.now().isoformat(timespec="seconds")})
    p.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")
    audit.log(session.user_id, session.role, "create_support_request", "allowed",
              f"ticket {tid} created", {"category": category})
    return ({"ticket_id": tid, "status": "open", "expected_response": "2 working days"},
            {"decision": "allowed"})


def _submit_sensitive(session, action, params, summary, audit_params):
    if not config.CONTROLS_ENABLED:  # baseline: executes immediately (unsafe, for comparison only)
        msg = approvals.EXECUTORS[action]({"requester": session.user_id, "params": params})
        return {"status": "DONE", "message": msg}, {"decision": "executed_without_approval"}
    item = approvals.create(session.user_id, action, params, summary)
    audit.log(session.user_id, session.role, f"request:{action}", "approval_required",
              f"pending {item['action_id']}", audit_params)
    return (
        {"status": "APPROVAL_REQUIRED", "action_id": item["action_id"],
         "message": "Sent to staff for approval. NOTHING has been changed yet."},
        {"decision": "approval_required", "approval_id": item["action_id"]},
    )


def _request_course_change(session, args):
    cur = str(args.get("current_course", "")).strip()
    new = str(args.get("new_course", "")).strip()
    reason = str(args.get("reason", "")).strip()
    if not (cur and new and reason):
        return {"error": "MISSING_INFO", "message": "Need current course, new course and a reason."}, {"decision": "error"}
    rec = records.get(session.user_id)
    if cur.lower() not in [c.lower() for c in rec["courses"]]:
        return ({"error": "INVALID_REQUEST", "message": "Current course not found.", "your_courses": rec["courses"]},
                {"decision": "error"})
    return _submit_sensitive(session, "course_change",
                             {"current_course": cur, "new_course": new, "reason": reason},
                             f"Replace {cur} with {new}", {"from": cur, "to": new})


def _request_contact_update(session, args):
    field = str(args.get("field", "")).lower().strip()
    value = str(args.get("new_value", "")).strip()
    if field not in ("email", "phone") or not value:
        return {"error": "MISSING_INFO", "message": "Need field (email/phone) and the new value."}, {"decision": "error"}
    if field == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return {"error": "INVALID_REQUEST", "message": "That email address looks invalid."}, {"decision": "error"}
    if field == "phone" and not 10 <= len(re.sub(r"\D", "", value)) <= 13:
        return {"error": "INVALID_REQUEST", "message": "That phone number looks invalid."}, {"decision": "error"}
    return _submit_sensitive(session, "contact_update", {"field": field, "new_value": value},
                             f"Change {field}", {"field": field, "new_value": _mask(value)})


def _remember(session, args):
    key, value = str(args.get("key", "")), str(args.get("value", ""))
    ok, reason = memory.save(session.user_id, key, value)
    audit.log(session.user_id, session.role, "memory_write", "allowed" if ok else "blocked", reason, {"key": key})
    result = {"saved": True} if ok else {"saved": False, "reason": reason}
    return result, {"decision": "allowed" if ok else "blocked"}


_HANDLERS = {
    "get_student_record": _get_record,
    "get_fee_status": _get_fees,
    "get_scholarship_status": _get_scholarship,
    "search_policy": _search_policy,
    "create_support_request": _create_support_request,
    "request_course_change": _request_course_change,
    "request_contact_update": _request_contact_update,
    "remember": _remember,
}


TOOL_SOURCES = {
    "get_student_record": "students.json#profile", "get_fee_status": "students.json#fees",
    "get_scholarship_status": "students.json#scholarship", "search_policy": "student_handbook.md",
    "create_support_request": "tickets.json (write)", "request_course_change": "approvals.json (needs staff approval)",
    "request_contact_update": "approvals.json (needs staff approval)", "remember": "memory.json (write)",
}


def execute(session, name: str, args):
    """Run one tool call inside a LangSmith span (a no-op when tracing is off)."""
    run_type = "retriever" if name == "search_policy" else "tool"
    shown = {k: v for k, v in (args if isinstance(args, dict) else {}).items() if not (name == "remember" and k == "value")}
    with obs.span(f"tool:{name}", run_type,
                  inputs={"args": shown, "signed_in_user": session.user_id, "role": session.role},
                  tags=["tool", name],
                  metadata={"data_source": TOOL_SOURCES.get(name, "unknown"), "controls_enabled": config.CONTROLS_ENABLED}) as sp:
        result, info = _execute(session, name, args)
        if name == "search_policy":
            docs = [{"page_content": r["text"], "metadata": {"source": "student_handbook.md", "section": r["id"],
                                                             "title": r["title"], "score": s}}
                    for r, s in zip(result.get("results", []),
                                    [e["score"] for e in info.get("evidence", [])] or [None] * 9)]
            sp.end(outputs={"documents": docs, "decision": info["decision"]}, metadata={"decision": info["decision"]})
        else:
            sp.end(outputs={"decision": info["decision"], "result": result}, metadata={"decision": info["decision"]})
    return result, info


def _execute(session, name: str, args):
    """Run one tool call. Never raises: errors become structured results the model can explain."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": "UNKNOWN_TOOL", "message": f"No tool named {name}."}, {"decision": "error"}
    try:
        return handler(session, args if isinstance(args, dict) else {})
    except Exception as exc:  # tool failure handling
        audit.log(session.user_id, session.role, name, "error", f"tool crashed: {type(exc).__name__}")
        return ({"error": "TOOL_ERROR", "message": "The tool failed. Tell the student and offer a support request."},
                {"decision": "error"})
