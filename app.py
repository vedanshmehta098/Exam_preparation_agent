"""Streamlit UI.  Run:  streamlit run app.py"""
import streamlit as st

from agent import ExamAgent, format_event
from llm import LLM, LLMError

st.set_page_config(page_title="ExamBuddy - Exam Preparation Agent", page_icon="🎓", layout="wide")
st.title("🎓 ExamBuddy — Exam Preparation Agent")
st.caption("Plans your revision, answers from YOUR notes, quizzes you, and tracks weak topics.")

ICON = {"node": "🔀", "plan": "🗺️", "step": "📌", "thought": "💭", "tool_call": "🔧",
        "observation": "👁️", "reflection": "🔍", "error": "⚠️"}

if "agent" not in st.session_state:
    try:
        st.session_state.agent = ExamAgent(LLM())
    except LLMError as e:
        st.error(str(e))
        st.stop()
    st.session_state.chat = []  # [(role, text, trace_lines)]

agent = st.session_state.agent

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("📚 Your notes")
    for f in sorted(agent.tools.notes_dir.glob("*")):
        st.write("•", f.name)
    up = st.file_uploader("Upload notes (.md / .txt)", type=["md", "txt"], accept_multiple_files=True)
    for f in up or []:
        (agent.tools.notes_dir / f.name).write_bytes(f.getvalue())
    st.subheader("📈 Progress (saved)")
    st.text(agent.tools.get_progress())
    if st.button("Reset conversation memory"):
        agent.history.clear()
        st.session_state.chat = []
        st.rerun()
    st.markdown("**Try:**\n- *I have a DBMS exam in 5 days, 2 hrs/day. Topics: normalization, transactions. Make me a plan.*\n"
                "- *Quiz me on normalization (3 questions)*\n- *(then answer the quiz)*\n- *What's my weakest topic?*")

# ---------------------------------------------------------------- chat history
for role, text, trace in st.session_state.chat:
    with st.chat_message(role):
        if trace:
            with st.expander("🧠 Agent trace"):
                st.code("\n".join(trace), language=None)
        st.markdown(text)

# ---------------------------------------------------------------- new message
if prompt := st.chat_input("Ask ExamBuddy..."):
    st.session_state.chat.append(("user", prompt, None))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        trace, final = [], ""
        with st.status("Agent is working...", expanded=True) as status:
            for e in agent.run(prompt):
                if e["type"] == "final":
                    final = e["text"]
                    continue
                line = format_event(e).strip()
                trace.append(line)
                if e["type"] == "node":
                    st.markdown(f"**{ICON['node']} {e['name'].upper()}**")
                elif e["type"] == "plan":
                    st.markdown(f"{ICON['plan']} **Plan**")
                    for i, s in enumerate(e["steps"]):
                        st.markdown(f"{i + 1}. {s['task']}")
                elif e["type"] == "observation" and not e["ok"]:
                    st.warning(line)
                else:
                    st.write(f"{ICON.get(e['type'], '')} {line}")
            status.update(label="Done", state="complete", expanded=False)
        st.markdown(final)
    st.session_state.chat.append(("assistant", final, trace))
