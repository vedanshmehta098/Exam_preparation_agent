# 🎓 ExamBuddy — Exam Preparation Agent

An agent that turns "I have an exam in 5 days" into a plan, answers from **your own notes**,
quizzes you, grades you, and remembers which topics are weak.

## Run it
```bash
pip install -r requirements.txt
cp .env.example .env        # paste your free Groq/Gemini key
streamlit run app.py        # or: python cli.py
python -m pytest -q         # offline tests (no key needed)
```

## How it works (30-second explanation)
```
 PLAN ──► EXECUTE ──► REFLECT ──► FINALIZE
            ▲  (ReAct loop:       │
            │   think → tool →    │ "something missing?"
            │   observe → repeat) │
            └─────────────────────┘
```
1. **PLAN** – the LLM splits the request into 1–5 steps (task decomposition).
2. **EXECUTE** – for each step, a ReAct loop: *Thought → Tool call → Observation*, repeated until the step is done.
3. **REFLECT** – the LLM checks the work against the request; if incomplete it adds steps (max once).
4. **FINALIZE** – writes the final answer, saved to short-term memory.

The "state" is one Python dict (`goal`, `plan` with each step's status/result, `replans`), passed between nodes.

## Tools (all in `tools.py`)
| Tool | What it does |
|---|---|
| `search_notes` | keyword search over uploaded notes (mini-RAG) |
| `wiki_lookup` | Wikipedia API – external fallback when notes lack a topic |
| `make_study_plan` | deterministic scheduler; weak topics get +50% time; last day = revision + mock test |
| `run_python` | sandboxed (subprocess, 5s timeout) for numeric problems |
| `record_score` / `get_progress` | long-term memory in `progress.json`; flags topics < 60% as WEAK |

## Memory
- **Short-term**: last 3 turns (`agent.history`) – lets you answer a quiz in the next message.
- **Long-term**: quiz scores in `progress.json` – survive restarts.

## Self-correction (where to point the evaluator)
- Tool raises an error → returned as `ERROR: …` observation → model fixes arguments or switches tool
  (try: *"plan my exam in 0 days"* or *"plan 20 topics in 1 day"*).
- Same failing tool twice → agent is told to stop using it (loop guard + hint).
- Wikipedia offline → falls back to notes.
- Invalid JSON from the model → plan step retries, then falls back to a single step.
- Tool budget exhausted (6 rounds) → forced partial answer, stating what is missing.
- LLM rate-limit/network error → exponential back-off retry; final fallback shows raw results.

## Live demo script (10 min)
1. *"I have a DBMS exam in 5 days, 2 hrs/day. Topics: normalization, transactions, indexing. Make a plan."*
   → show trace: plan → `get_progress` → `make_study_plan`.
2. *"Quiz me on normalization, 3 questions."* → `search_notes` grounds the questions.
3. Answer them (get one wrong on purpose) → `record_score` → sidebar shows progress.
4. *"What are my weak topics? Re-plan with 3 days left."* → memory + tool chaining.
5. Edge cases: *"plan my exam in 0 days"*, *"What is quantum entanglement?"* (not in notes → `wiki_lookup`), disconnect Wi-Fi.

## Files
`agent.py` brain · `tools.py` tools · `llm.py` model client · `app.py` Streamlit UI · `cli.py` terminal UI · `notes/` sample notes · `tests/` offline tests
