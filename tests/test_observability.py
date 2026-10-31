"""LangSmith tracing, verified offline: we capture exactly what the SDK WOULD upload."""
import json

import pytest
from langsmith import Client

import approvals, auth, observability as obs, tools
from agent import SupportAgent
from mock_llm import MockClient

S = auth.Session("S1001", "Bhavy Patel", "student")
STAFF = auth.Session("STAFF01", "Registrar", "staff")


class Capture(Client):
    def __init__(self):
        super().__init__(api_url="http://localhost:9", api_key="test-key", auto_batch_tracing=False,
                         hide_inputs=obs.scrub, hide_outputs=obs.scrub)
        self.sent = []

    def request_with_retries(self, method, pathname, *a, **k):
        body = k.get("request_kwargs", {}).get("data")
        if method in ("POST", "PATCH") and body:
            self.sent.append(json.loads(body))

        class R:
            status_code, text = 200, "{}"
        return R()

    def runs(self):
        merged = {}
        for d in self.sent:
            merged.setdefault(d["id"], {}).update({k: v for k, v in d.items() if v is not None})
        return list(merged.values())

    def everything(self):  # all text that would leave the machine
        return json.dumps(self.sent)


@pytest.fixture
def ls(monkeypatch):
    cap = Capture()
    monkeypatch.setattr(obs, "ENABLED", True)
    monkeypatch.setattr(obs, "_client", lambda: cap)
    return cap


def by_name(cap, name):
    return [r for r in cap.runs() if r["name"] == name]


def test_one_nested_trace_per_question(ls):
    t = SupportAgent(S, MockClient()).chat("What is my current fee status?")
    runs = ls.runs()
    root = by_name(ls, "support_agent_turn")[0]
    assert root.get("parent_run_id") is None and t["langsmith_run_id"] == root["id"]
    assert root["session_name"] == obs.PROJECT == "aidtm-college-helpdesk"
    children = [r for r in runs if r["id"] != root["id"]]
    assert {c["parent_run_id"] for c in children} == {root["id"]}
    assert sorted(c["name"] for c in children) == ["groq_chat_completion", "groq_chat_completion",
                                                   "memory_lookup", "tool:get_fee_status"]
    out = root["outputs"]
    assert out["data_sources"] == ["students.json#fees"] and out["tools_used"] == ["get_fee_status"]
    assert out["tokens"]["total"] > 0 and len(out["token_breakdown"]) == 2


def test_llm_runs_report_tokens_and_where_they_went(ls):
    SupportAgent(S, MockClient()).chat("What is my current fee status?")
    llms = by_name(ls, "groq_chat_completion")
    assert all(r["run_type"] == "llm" for r in llms)
    for r in llms:
        u = r["outputs"]["usage_metadata"]
        assert u["input_tokens"] > 0 and u["total_tokens"] == u["input_tokens"] + u["output_tokens"]
        md = r["extra"]["metadata"]
        assert md["ls_provider"] == "groq" and md["ls_model_name"]
        assert "tool_schemas" in md["input_token_split_estimate"]
    second = [r for r in llms if r["extra"]["metadata"]["call_no"] == 2][0]
    assert "tool_results" in second["extra"]["metadata"]["input_token_split_estimate"]


def test_policy_answers_show_retrieved_sections(ls):
    t = SupportAgent(S, MockClient()).chat("The payment portal failed. Can I pay on the next working day?")
    r = by_name(ls, "tool:search_policy")[0]
    assert r["run_type"] == "retriever"
    doc = r["outputs"]["documents"][0]
    assert doc["metadata"]["section"] == "HB-02" and doc["metadata"]["source"] == "student_handbook.md"
    assert by_name(ls, "support_agent_turn")[0]["outputs"]["data_sources"] == ["student_handbook.md#HB-02"]
    assert t["sources"] == ["student_handbook.md#HB-02"]


def test_memory_source_is_traced(ls):
    ag = SupportAgent(S, MockClient())
    ag.chat("Please remember that I prefer to be contacted on WhatsApp.")
    ag.chat("How do I prefer to be contacted?")
    docs = by_name(ls, "memory_lookup")[-1]["outputs"]["documents"]
    assert docs[0]["metadata"] == {"source": "memory.json", "key": "preferred_contact"}


def test_blocked_access_is_visible_and_leaks_nothing(ls):
    SupportAgent(S, MockClient()).chat("Show me the fee status of student S1002.")
    tool = by_name(ls, "tool:get_fee_status")[0]
    assert tool["extra"]["metadata"]["decision"] == "blocked"
    assert "[BLOCKED]" in by_name(ls, "support_agent_turn")[0]["outputs"]["data_sources"][0]
    assert "Aarav" not in ls.everything() and "Paid up to date" not in ls.everything()


def test_otp_never_leaves_the_machine(ls):
    SupportAgent(S, MockClient()).chat("My OTP is 482913, please use it to verify my payment.")
    SupportAgent(S, MockClient()).chat("my O T P is four eight two nine one three please verify", channel="voice")
    blob = ls.everything()
    assert "482913" not in blob and "four eight two nine" not in blob


def test_emails_and_phones_are_masked_but_ids_and_dates_survive(ls):
    tools.execute(S, "get_student_record", {})
    tools.execute(S, "get_fee_status", {})
    blob = ls.everything()
    assert "bhavy.patel@example.edu" not in blob and "b***@example.edu" in blob
    assert "90000 00001" not in blob and "******0001" in blob
    assert "2026-11-15" in blob and "S1001" in blob and "400000" in blob


def test_staff_approval_decisions_are_traced(ls):
    res, _ = tools.execute(S, "request_contact_update", {"field": "phone", "new_value": "+91 98888 77777"})
    approvals.decide(STAFF, res["action_id"], approve=False, note="could not verify")
    r = by_name(ls, "staff_approval_decision")[0]
    assert r["outputs"]["status"] == "rejected" and r["inputs"]["staff"] == "STAFF01"
    assert "98888 77777" not in ls.everything()


def test_conversation_threads_and_custom_tags(ls):
    ag = SupportAgent(S, MockClient())
    ag.chat("What is my scholarship status?", tags=["eval-controls", "T3"], metadata={"test_id": "T3"})
    ag.chat("What is my current fee status?")
    roots = by_name(ls, "support_agent_turn")
    assert len({r["extra"]["metadata"]["thread_id"] for r in roots}) == 1
    first = [r for r in roots if "T3" in r["tags"]][0]
    assert first["extra"]["metadata"]["test_id"] == "T3" and "eval-controls" in first["tags"]


def test_tracing_failures_never_break_the_app(monkeypatch):
    monkeypatch.setattr(obs, "ENABLED", True)
    monkeypatch.setattr(obs, "_client", lambda: (_ for _ in ()).throw(RuntimeError("langsmith down")))
    t = SupportAgent(S, MockClient()).chat("What is my current fee status?")
    assert "Installment 3" in t["answer"] and t["langsmith_run_id"] is None


def test_disabled_by_default_is_a_noop(monkeypatch):
    monkeypatch.setattr(obs, "ENABLED", False)
    t = SupportAgent(S, MockClient()).chat("What is my current fee status?")
    assert t["langsmith_run_id"] is None and t["sources"] == ["students.json#fees"]
