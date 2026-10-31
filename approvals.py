"""Human-in-the-loop approval queue for sensitive actions.
Execution happens ONLY inside decide(), after a staff member approves."""
import datetime
import json

import audit
import config
import observability as obs
import records


def _path():
    return config.runtime_path("approvals.json")


def _load() -> list:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(items: list) -> None:
    _path().write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def create(requester: str, action: str, params: dict, summary: str) -> dict:
    items = _load()
    item = {
        "action_id": f"APR-{len(items) + 1:04d}", "requester": requester, "action": action,
        "params": params, "summary": summary, "status": "pending", "created": _now(),
        "decided_by": None, "decided_at": None, "note": "", "result": "",
    }
    items.append(item)
    _save(items)
    return item


def get(action_id: str):
    return next((i for i in _load() if i["action_id"] == action_id), None)


def list_all() -> list:
    return _load()


def list_pending() -> list:
    return [i for i in _load() if i["status"] == "pending"]


def list_for(user_id: str) -> list:
    return [i for i in _load() if i["requester"] == user_id]


# ---- executors (only called from decide(), or by the A1 baseline mode)
def _exec_course_change(item: dict) -> str:
    p = item["params"]
    rec = records.get(item["requester"])
    courses = list(rec["courses"])
    lowered = [c.lower() for c in courses]
    idx = lowered.index(p["current_course"].lower())
    old = courses[idx]
    courses[idx] = p["new_course"]
    records.update(item["requester"], {"courses": courses})
    return f"Course changed: {old} -> {p['new_course']}"


def _exec_contact_update(item: dict) -> str:
    p = item["params"]
    records.update(item["requester"], {p["field"]: p["new_value"]})
    return f"{p['field']} updated"


EXECUTORS = {"course_change": _exec_course_change, "contact_update": _exec_contact_update}


def decide(staff, action_id: str, approve: bool, note: str = "") -> dict:
    with obs.span("staff_approval_decision", "chain",
                  inputs={"action_id": action_id, "decision": "approve" if approve else "reject", "staff": staff.user_id,
                          "role": staff.role}, tags=["approval", "assignment-2"],
                  metadata={"controls_enabled": config.CONTROLS_ENABLED}) as sp:
        item = _decide(staff, action_id, approve, note)
        sp.end(outputs={"status": item["status"], "result": item["result"], "requested_by": item["requester"]},
               metadata={"final_status": item["status"]})
    return item


def _decide(staff, action_id: str, approve: bool, note: str = "") -> dict:
    # Authorization in code: only staff may decide.
    if staff.role != "staff":
        audit.log(staff.user_id, staff.role, "approval_decision", "blocked",
                  "only staff can approve or reject", {"action_id": action_id})
        raise PermissionError("Only staff can approve or reject actions.")
    items = _load()
    item = next((i for i in items if i["action_id"] == action_id), None)
    if item is None:
        raise KeyError(f"No such approval: {action_id}")
    if item["status"] != "pending":
        raise ValueError(f"{action_id} is already {item['status']}")

    item["decided_by"], item["decided_at"], item["note"] = staff.user_id, _now(), note
    if approve:
        try:
            item["result"] = EXECUTORS[item["action"]](item)
            item["status"], decision = "approved", "approved"
        except Exception as exc:  # execution failed -> never half-applied silently
            item["result"], item["status"], decision = f"execution failed: {exc}", "failed", "approved_but_failed"
    else:
        item["result"], item["status"], decision = "Rejected by staff. Action was NOT executed.", "rejected", "rejected"
    _save(items)
    audit.log(staff.user_id, "staff", f"approval:{item['action']}", decision, item["result"],
              {"action_id": action_id, "requested_by": item["requester"], "note": note})
    return item
