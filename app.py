"""AIDTM Student Support Agent - Streamlit UI.
   streamlit run app.py          (tick "Demo mode" on the login page to try it without an API key)"""
import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import approvals
import audit
import auth
import config
import memory
import observability as obs
import tickets_view
from agent import SupportAgent
from voice_logic import friendly_error, handle_event

st.set_page_config(page_title="AIDTM Student Support", page_icon="🎓", layout="wide",
                   initial_sidebar_state="auto")
ss = st.session_state
for key, default in {"session": None, "agent": None, "chat": [], "demo": False, "quick": None,
                     "voice_active": False, "voice_last_event": None, "voice_answer": "",
                     "voice_answer_id": 0, "voice_error": ""}.items():
    ss.setdefault(key, default)

voice_widget = components.declare_component("aidtm_voice", path=str(Path(__file__).parent / "voice_component"))
scroll_widget = components.declare_component("aidtm_scroll", path=str(Path(__file__).parent / "scroll_component"))

STUDENT_PAGES = ["💬 Chat", "🎙️ Voice call", "📋 My activity"]
STAFF_PAGES = ["✅ Approvals", "🧾 Audit log", "🎫 Tickets"]

# ============================================================ look & feel
st.markdown("""
<style>
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stAppDeployButton"],
[data-testid="stMainMenu"], [data-testid="stToolbarActions"] { display: none !important; }
/* The "open sidebar" button lives in the toolbar: keep it visible and easy to find. */
[data-testid="stExpandSidebarButton"] { background: #4F46E5 !important; border-radius: 10px !important; opacity: 1 !important; }
[data-testid="stExpandSidebarButton"] *, [data-testid="stExpandSidebarButton"] svg { color: #fff !important; fill: #fff !important; }
[data-testid="stAppViewContainer"] { background: linear-gradient(rgba(244,246,251,.93), rgba(244,246,251,.97)),
        url(app/static/campus.jpg) center / cover no-repeat fixed; }
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; max-width: 1180px; }
[data-testid="stSidebar"] { border-right: 1px solid #E5E7EB; }
[data-testid="stBottom"], [data-testid="stBottom"] > div { background: transparent !important; }
[data-testid="stBottomBlockContainer"] { max-width: 1180px; margin: 0 auto; }
[data-testid="stSidebar"] .block-container { padding-top: 1rem !important; }

.hero { background: linear-gradient(105deg, rgba(49,46,129,.93) 0%, rgba(91,33,182,.80) 55%, rgba(124,58,237,.45) 100%),
        url(app/static/campus.jpg) center 42% / cover; color: #fff; border-radius: 18px;
        padding: 12px 22px; margin-bottom: 10px; box-shadow: 0 6px 18px rgba(79,70,229,.22); }
.hero h2 { margin: 0; padding: 0; font-size: 1.3rem; line-height: 1.3; color: #fff; }
.hero p { margin: 2px 0 0; opacity: .92; font-size: .88rem; }
/* The scrolling chat/transcript box always fits the window, so the page itself never scrolls. */
[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .chat-anchor),
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .chat-anchor) {
    height: calc(100vh - 330px) !important; flex: 0 0 calc(100vh - 330px) !important; min-height: 260px !important; max-height: none !important; }
.chat-anchor { display: none; }
.brandimg { height: 86px; border-radius: 14px; color: #fff; padding: 14px 16px; display: flex; flex-direction: column; justify-content: flex-end;
        background: linear-gradient(120deg, rgba(49,46,129,.90), rgba(109,40,217,.55)), url(app/static/campus.jpg) center / cover;
        box-shadow: 0 4px 12px rgba(79,70,229,.25); }
.brandimg b { font-size: 1.1rem; } .brandimg small { opacity: .9; font-size: .78rem; }
.usercard { background: #F4F6FB; border: 1px solid #E5E7EB; border-radius: 14px; padding: 12px 14px; margin: 10px 0 6px; }
.usercard b { font-size: 1rem; }
.usercard span { color: #6B7280; font-size: .82rem; }
.chip { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.74rem; font-weight:600; margin:2px 4px 2px 0; }
.chip.ok { background:#DCFCE7; color:#166534; } .chip.warn { background:#FEF3C7; color:#92400E; }
.chip.info { background:#E0E7FF; color:#3730A3; } .chip.bad { background:#FEE2E2; color:#991B1B; }

[data-testid="stChatMessage"] { background:#fff; border:1px solid #E5E7EB; border-radius:14px; padding:.65rem .9rem;
        margin-bottom:.45rem; box-shadow:0 1px 2px rgba(16,24,40,.04); }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background:#EEF2FF; border-color:#E0E7FF; }
[data-testid="stMetric"] { background:#fff; border:1px solid #E5E7EB; border-radius:14px; padding:12px 16px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px; }
.stButton > button { border-radius: 10px; font-weight: 600; }
.login-card { max-width: 440px; margin: 0 auto; }
</style>
""", unsafe_allow_html=True)


# ============================================================ small helpers
def table(rows, empty="Nothing here yet."):
    if not rows:
        st.caption(empty)
        return
    try:
        st.dataframe(rows, hide_index=True, width="stretch")
    except Exception:
        st.dataframe(rows, hide_index=True, use_container_width=True)


def button(label, container=st, **kw):
    try:
        return container.button(label, width="stretch", **kw)
    except Exception:
        return container.button(label, use_container_width=True, **kw)


def hero(title, subtitle):
    st.markdown(f'<div class="hero"><h2>{title}</h2><p>{subtitle}</p></div>', unsafe_allow_html=True)


def autoscroll():
    """Keep the newest message visible inside the chat box (custom component; never breaks the app)."""
    try:
        ss["_runs"] = ss.get("_runs", 0) + 1
        scroll_widget(nonce=ss["_runs"], key="chat_scroll", default=None)
    except Exception:
        pass


def make_agent(session):
    if ss.demo or os.getenv("USE_MOCK") == "1":
        from mock_llm import MockClient
        return SupportAgent(session, MockClient())
    return SupportAgent(session)


def reset_user_state():
    ss.update(session=None, agent=None, chat=[], quick=None, voice_active=False, voice_last_event=None,
              voice_answer="", voice_answer_id=0, voice_error="")
    ss.pop("nav", None)


def render_message(m):
    with st.chat_message(m["role"], avatar="🧑‍🎓" if m["role"] == "user" else "🎓"):
        tag = "🎙️ " if m.get("channel") == "voice" else ""
        st.markdown(tag + m["content"])
        t = m.get("trace")
        if t:
            bits = [("🎙️ voice" if t.get("channel") == "voice" else "⌨️ text")]
            if t["tools_used"]:
                bits.append("🔧 " + ", ".join(dict.fromkeys(t["tools_used"])))
            if t["evidence"]["policy"]:
                bits.append("📄 " + ", ".join(dict.fromkeys(t["evidence"]["policy"])))
            if t["evidence"]["memory"]:
                bits.append("🧠 " + ", ".join(t["evidence"]["memory"]))
            srcs = t.get("sources") or []
            if srcs:
                bits.append("📍 " + " · ".join(srcs[:2]) + (f" +{len(srcs) - 2}" if len(srcs) > 2 else ""))
            bits.append(f"⏱ {t['latency_s']}s")
            bits.append(f"🔢 {t['tokens']['input']}→{t['tokens']['output']} tokens")
            if t["flags"]:
                bits.append("⚠️ " + ", ".join(t["flags"]))
            st.caption("  ·  ".join(bits))
            with st.expander("Trace details"):
                st.markdown("**Where this answer came from:** " + ", ".join(f"`{x}`" for x in (t.get("sources") or ["-"])))
                rows = [{"model call": b["call"], "purpose": b["purpose"], "input tokens": b["input"], "output tokens": b["output"],
                         "input tokens went to (estimate)": ", ".join(f"{k} {v}" for k, v in b["input_split_estimate"].items())}
                        for b in t.get("token_breakdown", [])]
                table(rows, "No model calls.")
                if t.get("langsmith_run_id"):
                    st.caption(f"LangSmith run id: {t['langsmith_run_id']}")
                st.json(t["steps"] or [{"info": "answered directly, no tool call"}], expanded=False)


def chat_box():
    """Fixed-height, internally scrolling container. Height is set by CSS (.chat-anchor rule)."""
    box = st.container(height=420, border=True)
    with box:
        st.markdown('<span class="chat-anchor"></span>', unsafe_allow_html=True)
    return box


def render_history(empty_hint=None):
    if not ss.chat and empty_hint:
        st.caption(empty_hint)
    for m in ss.chat:
        render_message(m)


def ask_agent(text, box):
    shown = memory.redact(text) if config.CONTROLS_ENABLED else text
    with box:
        with st.chat_message("user", avatar="🧑‍🎓"):
            st.markdown(shown)
        with st.chat_message("assistant", avatar="🎓"):
            with st.spinner("Thinking..."):
                try:
                    t = ss.agent.chat(text, channel="text")
                except Exception as exc:
                    st.error(friendly_error(exc))
                    return
    ss.chat += [{"role": "user", "content": t["question"], "channel": "text"},
                {"role": "assistant", "content": t["answer"], "trace": t}]
    st.rerun()


# ============================================================ login
def login_form():
    try:
        return st.form("login", border=False)
    except TypeError:  # older Streamlit without the border option
        return st.form("login")


LOGIN_CSS = """<style>
[data-testid="stAppViewContainer"] { background: linear-gradient(rgba(15,23,42,.58), rgba(49,46,129,.74)),
        url(app/static/campus.jpg) center / cover no-repeat fixed !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.login-anchor),
[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .login-anchor) {
        background: rgba(255,255,255,.97) !important; border-radius: 18px; box-shadow: 0 14px 44px rgba(0,0,0,.38); }
[data-testid="stExpander"] { background: rgba(255,255,255,.95); border-radius: 12px; }
.login-anchor { display: none; }
.login-title { text-align: center; color: #fff; margin: 5vh 0 20px; text-shadow: 0 2px 12px rgba(0,0,0,.5); }
.login-title h1 { color: #fff; font-size: 2.2rem; margin: 0; padding: 0; }
.login-title p { margin: 6px 0 0; opacity: .95; }
</style>"""
LOGIN_TITLE = ('<div class="login-title"><h1>🎓 AIDTM Student Support</h1>'
               '<p>Ask about fees, scholarships, courses and policies - by chat or voice call.</p></div>')


def login_page():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(LOGIN_TITLE, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        with st.container(border=True):
            st.markdown('<span class="login-anchor"></span>', unsafe_allow_html=True)
            with login_form():
                st.subheader("Sign in")
                uid = st.text_input("User ID", placeholder="e.g. S1001")
                pin = st.text_input("PIN", type="password", placeholder="••••")
                no_key = not config.GROQ_API_KEY and os.getenv("USE_MOCK") != "1"
                demo = st.checkbox("Demo mode (offline, no API key)", value=no_key,
                                   help="Uses a simple keyword model instead of the Groq LLM.")
                go = st.form_submit_button("Sign in", type="primary")
            if no_key:
                st.caption("No GROQ_API_KEY found, so demo mode is pre-selected. Add a free key in `.env` for the real model.")
        with st.expander("Demo accounts"):
            table([{"User ID": "S1001", "PIN": "1111", "Role": "Student"},
                   {"User ID": "S1002", "PIN": "2222", "Role": "Student"},
                   {"User ID": "S1003", "PIN": "3333", "Role": "Student"},
                   {"User ID": "STAFF01", "PIN": "9999", "Role": "Staff (approvals)"}])
    if go:
        s = auth.authenticate(uid, pin)
        audit.log((uid or "?").strip().upper(), "unknown", "login", "allowed" if s else "blocked",
                  "signed in" if s else "bad credentials")
        if not s:
            with mid:
                st.error("Wrong ID or PIN.")
            return
        ss.demo = bool(demo) or os.getenv("USE_MOCK") == "1"
        try:
            agent = make_agent(s) if s.role == "student" else None
        except RuntimeError as exc:
            with mid:
                st.error(str(exc))
            return
        reset_user_state()
        ss.session, ss.agent = s, agent
        st.rerun()


# ============================================================ sidebar
def sidebar(session):
    with st.sidebar:
        st.markdown('<div class="brandimg"><b>🎓 AIDTM</b><small>Student Support Agent</small></div>', unsafe_allow_html=True)
        role = "Student" if session.role == "student" else "Staff"
        st.markdown(f'<div class="usercard"><b>{session.name}</b><br><span>{session.user_id} · {role}</span></div>',
                    unsafe_allow_html=True)
        pages = STUDENT_PAGES if session.role == "student" else STAFF_PAGES
        page = st.radio("Menu", pages, key="nav", label_visibility="collapsed")
        st.divider()
        ctrl = ('<span class="chip ok">Controls ON</span>' if config.CONTROLS_ENABLED
                else '<span class="chip warn">Controls OFF (baseline)</span>')
        model = "demo (keyword mock)" if (ss.demo or os.getenv("USE_MOCK") == "1") else config.MODEL
        ls = obs.status()
        ls_chip = ('<span class="chip ok">LangSmith ON</span>' if ls["enabled"] else '<span class="chip warn">LangSmith off</span>')
        st.markdown(ctrl + f'<span class="chip info">{model}</span>' + ls_chip, unsafe_allow_html=True)
        st.caption(f"Tracing to project: {ls['project']}" if ls["enabled"] else f"LangSmith: {ls['reason']}")
        if session.role == "student":
            traces = [m["trace"] for m in ss.chat if m.get("trace")]
            tin = sum(t["tokens"]["input"] for t in traces)
            tout = sum(t["tokens"]["output"] for t in traces)
            st.caption(f"🔢 Session tokens: {tin:,} in · {tout:,} out")
        st.write("")
        if button("Sign out"):
            audit.log(session.user_id, session.role, "logout", "allowed", "signed out")
            reset_user_state()
            st.rerun()
    return page


# ============================================================ student pages
QUICK = ["What is my current fee status?", "The payment portal failed. Can I pay on the next working day?",
         "What is my scholarship status?", "Change my phone number to +91 98888 77777"]


def page_chat(session):
    hero("💬 Chat with your support agent", "Answers use your own records and the student handbook. Sensitive changes go to staff for approval.")
    pending = [a for a in approvals.list_for(session.user_id) if a["status"] == "pending"]
    box = chat_box()
    with box:
        if pending:
            st.info("⏳ Waiting for staff approval: " + "; ".join(f"**{a['action_id']}** {a['summary']}" for a in pending))
        if not ss.chat:
            st.markdown("#### 👋 Hi! Try one of these")
            c1, c2 = st.columns(2)
            for i, q in enumerate(QUICK):
                if button(q, container=(c1 if i % 2 == 0 else c2), key=f"quick_{i}"):
                    ss.quick = q
                    st.rerun()
        render_history()
    typed = st.chat_input("Ask about fees, scholarships, courses or policies...")
    question = typed or ss.pop("quick", None)
    if question:
        ask_agent(question, box)
    autoscroll()


def page_voice(session):
    hero("🎙️ Voice call", "Talk hands-free. Same sign-in, same privacy rules and the same staff approvals as chat.")
    left, right = st.columns([1, 1.7], gap="large")
    with left:
        ev = voice_widget(active=ss.voice_active, answer=ss.voice_answer, answer_id=ss.voice_answer_id,
                          key="aidtm_voice", default=None)
        with st.spinner("Thinking..."):
            rerun = handle_event(ss, ev, ss.agent)
        if rerun:
            st.rerun()
        if ss.voice_error:
            st.warning(ss.voice_error)
        st.caption("Use Chrome or Edge and allow the microphone. Saying \"yes\" on a call never approves a change - only staff can.")
    with right:
        st.markdown("**Conversation** (shared with the Chat tab)")
        box = chat_box()
        with box:
            render_history("Your call transcript appears here once you start talking.")
    autoscroll()


def page_activity(session):
    hero("📋 My activity", "Your requests, tickets and the audit trail of actions taken on your account.")
    mine = approvals.list_for(session.user_id)
    my_tickets = [t for t in tickets_view.load() if t["student"] == session.user_id]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pending approvals", sum(a["status"] == "pending" for a in mine))
    c2.metric("Approved", sum(a["status"] == "approved" for a in mine))
    c3.metric("Rejected", sum(a["status"] == "rejected" for a in mine))
    c4.metric("Support tickets", len(my_tickets))
    st.subheader("Approval requests")
    table([{k: a[k] for k in ("action_id", "summary", "status", "decided_by", "result")} for a in mine],
          "You have not requested any changes yet.")
    st.subheader("Support tickets")
    table([{k: t[k] for k in ("ticket_id", "category", "status", "description")} for t in my_tickets],
          "No support tickets yet.")
    st.subheader("Audit trail")
    rows = [e for e in audit.read_all() if e["actor"] == session.user_id]
    table([{k: e[k] for k in ("audit_id", "ts", "action", "decision", "result")} for e in reversed(rows)],
          "No audited actions yet.")


# ============================================================ staff pages
def page_approvals(session):
    hero("✅ Approvals", "Sensitive changes requested by students wait here. Nothing is applied until you approve.")
    allx = approvals.list_all()
    pending = [a for a in allx if a["status"] == "pending"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Pending", len(pending))
    c2.metric("Approved", sum(a["status"] == "approved" for a in allx))
    c3.metric("Rejected", sum(a["status"] == "rejected" for a in allx))
    st.subheader("Waiting for decision")
    if not pending:
        st.success("Nothing waiting for approval.")
    for a in pending:
        with st.container(border=True):
            st.markdown(f"**{a['action_id']}** · requested by **{a['requester']}** · {a['created']}")
            st.markdown(f"##### {a['summary']}")
            st.markdown("  \n".join(f"**{k.replace('_', ' ')}:** `{v}`" for k, v in a["params"].items()))
            note = st.text_input("Note (optional)", key=f"note_{a['action_id']}")
            b1, b2 = st.columns(2)
            with b1:
                if button("✅ Approve", key=f"ok_{a['action_id']}", type="primary"):
                    approvals.decide(session, a["action_id"], True, note)
                    st.rerun()
            with b2:
                if button("❌ Reject", key=f"no_{a['action_id']}"):
                    approvals.decide(session, a["action_id"], False, note)
                    st.rerun()
    st.subheader("Decision history")
    table([{k: a[k] for k in ("action_id", "requester", "summary", "status", "decided_by", "result")}
           for a in allx if a["status"] != "pending"], "No decisions yet.")


def page_audit(session):
    hero("🧾 Audit log", "Every read, block, request and decision. Records are hash-chained, so edits are detected.")
    ok, bad = audit.verify()
    if ok:
        st.success("Audit chain intact ✅")
    else:
        st.error(f"Audit chain TAMPERED at record {bad} ❌")
    entries = audit.read_all()
    decisions = sorted({e["decision"] for e in entries})
    pick = st.multiselect("Filter by decision", decisions, default=[])
    rows = [e for e in reversed(entries) if not pick or e["decision"] in pick]
    table([{k: e[k] for k in ("audit_id", "ts", "actor", "action", "decision", "result")} for e in rows],
          "No audit records yet.")


def page_tickets(session):
    hero("🎫 Support tickets", "Tickets raised by students through the agent.")
    table(tickets_view.load(), "No tickets yet.")


# ============================================================ router
def main():
    session = ss.session
    if session is None:
        login_page()
        return
    page = sidebar(session)
    if page != STUDENT_PAGES[1]:
        ss.voice_active = False  # leaving the voice page ends the call
    if session.role == "student":
        {STUDENT_PAGES[0]: page_chat, STUDENT_PAGES[1]: page_voice, STUDENT_PAGES[2]: page_activity}[page](session)
    else:
        {STAFF_PAGES[0]: page_approvals, STAFF_PAGES[1]: page_audit, STAFF_PAGES[2]: page_tickets}[page](session)


main()
