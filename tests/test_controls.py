"""No LLM and no API tokens needed: these prove the controls work in plain code."""
import json

import pytest

import approvals, audit, auth, memory, rag, records, tools


def student(uid="S1001"):
    return auth.Session(uid, "Test", "student")


STAFF = auth.Session("STAFF01", "Registrar", "staff")


# ---------------------------------------------------------------- identity / privacy
def test_login_ok_and_bad_pin():
    assert auth.authenticate("S1001", "1111").role == "student"
    assert auth.authenticate("S1001", "0000") is None
    assert auth.authenticate("STAFF01", "9999").role == "staff"


def test_own_data_allowed():
    res, info = tools.execute(student(), "get_fee_status", {})
    assert info["decision"] == "allowed" and res["student_id"] == "S1001"
    res, _ = tools.execute(student(), "get_scholarship_status", {"student_id": "s1001"})
    assert res["scholarship"]["status"] == "Approved"


@pytest.mark.parametrize("target", ["S1002", "s1003", "Aarav Shah", "show Meera Iyer's record"])
def test_other_student_blocked(target):
    for tool in ("get_fee_status", "get_scholarship_status", "get_student_record"):
        res, info = tools.execute(student(), tool, {"student_id": target})
        assert res["error"] == "ACCESS_DENIED" and info["decision"] == "blocked"
        assert "fees" not in res and "email" not in res
    blocked = [e for e in audit.read_all() if e["decision"] == "blocked"]
    assert len(blocked) == 3


def test_staff_cannot_use_student_tools():
    res, _ = tools.execute(STAFF, "get_fee_status", {"student_id": "S1001"})
    assert res["error"] == "ACCESS_DENIED"


# ---------------------------------------------------------------- approval
def test_sensitive_change_waits_for_approval():
    res, info = tools.execute(student(), "request_contact_update", {"field": "phone", "new_value": "+91 98888 77777"})
    assert res["status"] == "APPROVAL_REQUIRED" and info["decision"] == "approval_required"
    assert records.get("S1001")["phone"] == "+91 90000 00001"          # NOT changed
    assert len(approvals.list_pending()) == 1


def test_reject_does_not_execute():
    res, _ = tools.execute(student(), "request_contact_update", {"field": "email", "new_value": "new@example.edu"})
    item = approvals.decide(STAFF, res["action_id"], approve=False, note="not verified")
    assert item["status"] == "rejected"
    assert records.get("S1001")["email"] == "bhavy.patel@example.edu"
    assert audit.read_all()[-1]["decision"] == "rejected"


def test_approve_executes_once():
    res, _ = tools.execute(student(), "request_course_change",
                           {"current_course": "HR Analytics", "new_course": "Deep Learning", "reason": "career"})
    assert "HR Analytics" in records.get("S1001")["courses"]
    approvals.decide(STAFF, res["action_id"], approve=True)
    assert "Deep Learning" in records.get("S1001")["courses"]
    with pytest.raises(ValueError):
        approvals.decide(STAFF, res["action_id"], approve=True)


def test_student_cannot_approve_own_request():
    res, _ = tools.execute(student(), "request_contact_update", {"field": "phone", "new_value": "+91 98888 77777"})
    with pytest.raises(PermissionError):
        approvals.decide(student(), res["action_id"], approve=True)
    assert records.get("S1001")["phone"] == "+91 90000 00001"


def test_tool_errors_are_structured():
    res, _ = tools.execute(student(), "request_course_change",
                           {"current_course": "Astrology", "new_course": "X", "reason": "y"})
    assert res["error"] == "INVALID_REQUEST" and "your_courses" in res
    res, _ = tools.execute(student(), "request_contact_update", {"field": "email", "new_value": "nope"})
    assert res["error"] == "INVALID_REQUEST"
    res, _ = tools.execute(student(), "no_such_tool", {})
    assert res["error"] == "UNKNOWN_TOOL"


# ---------------------------------------------------------------- memory
@pytest.mark.parametrize("text", ["My OTP is 482913", "my password is hunter2", "CVV 123", "card 4111 1111 1111 1111", "aadhaar 1234 5678 9012"])
def test_sensitive_detected_and_redacted(text):
    assert memory.contains_sensitive(text)
    assert "REDACTED" in memory.redact(text)


def test_phone_number_is_not_sensitive():
    assert not memory.contains_sensitive("change my phone to +91 98888 77777")
    assert not memory.contains_sensitive("+919888877777")


def test_memory_guard():
    assert memory.save("S1001", "preferred_contact", "WhatsApp")[0]
    assert not memory.save("S1001", "preferred_contact", "otp 482913")[0]
    assert not memory.save("S1001", "password", "hunter2")[0]                 # key not allowed
    assert not memory.save("S1001", "programme", "in the library today")[0]    # temporary
    assert memory.load_all("S1001") == {"preferred_contact": "WhatsApp"}


def test_memory_context_selection():
    memory.save("S1001", "preferred_contact", "WhatsApp")
    memory.save("S1001", "programme", "PGDM Big Data Analytics")
    assert memory.select_relevant("S1001", "How should you contact me?") == {"preferred_contact": "WhatsApp"}
    assert memory.select_relevant("S1001", "What is the attendance rule?") == {}


# ---------------------------------------------------------------- retrieval
def test_retrieval_relevant_and_unanswerable():
    assert rag.search("The payment portal failed, can I pay on the next working day?")[0]["id"] == "HB-02"
    assert rag.search("what is the attendance requirement")[0]["id"] == "HB-08"
    assert rag.search("what is the hostel fee refund policy") == []
    assert len(rag.search("late fee amount")) <= 2


# ---------------------------------------------------------------- audit
def test_audit_chain_detects_tampering():
    tools.execute(student(), "get_fee_status", {})
    tools.execute(student(), "get_fee_status", {"student_id": "S1002"})
    assert audit.verify() == (True, None)
    path = audit._path()
    lines = path.read_text().splitlines()
    rec = json.loads(lines[0]); rec["decision"] = "allowed-edited"; lines[0] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    ok, idx = audit.verify()
    assert not ok and idx == 0


def test_baseline_mode_has_no_controls():
    import config
    config.CONTROLS_ENABLED = False
    res, _ = tools.execute(student(), "get_fee_status", {"student_id": "S1002"})
    assert "fees" in res and audit.read_all() == []


def test_spoken_number_normalisation():
    assert "482913" in memory.normalize_spoken("my otp is four eight two nine one three")
    assert "482913" in memory.normalize_spoken("otp 4 8 2 9 1 3")
    assert memory.normalize_spoken("I have one question about two courses") == "I have one question about two courses"
    assert memory.contains_sensitive(memory.normalize_spoken("my o t p is four eight two nine one three"))
    assert memory.normalize_spoken("change phone to +91 98888 77777") == "change phone to +91 98888 77777"
