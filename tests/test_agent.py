"""Offline tests: a scripted FakeLLM replaces the real model, so no API key or internet is needed.
Run:  python -m pytest -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import ExamAgent
from llm import Reply, ToolCall
from tools import ToolBox

NOTES = Path(__file__).resolve().parent.parent / "notes"


class FakeLLM:
    """Returns pre-written replies in order."""
    def __init__(self, replies): self.replies, self.calls = list(replies), []
    def chat(self, messages, tools=None, json_mode=False, temperature=0.2):
        self.calls.append(messages)
        return self.replies.pop(0)


def call(name, **args): return ToolCall("c1", name, json.dumps(args))
def J(**kw): return Reply(content=json.dumps(kw))


def test_study_plan_tool():
    t = ToolBox(NOTES)
    plan = t.make_study_plan(["A", "B", "C"], days=4, hours_per_day=2, weak_topics=["B"])
    assert plan.count("Day") == 4 and "Revise all topics" in plan.splitlines()[-1]
    ok, msg = t.run("make_study_plan", {"topics": ["A"] * 20, "days": 1, "hours_per_day": 1})
    assert not ok and "do not fit" in msg
    ok, msg = t.run("make_study_plan", {"topics": ["A"], "days": 0, "hours_per_day": 1})
    assert not ok and "between 1 and 60" in msg


def test_notes_search_and_sandbox(tmp_path):
    t = ToolBox(NOTES, tmp_path / "p.json")
    assert "3NF" in t.search_notes("what is third normal form 3NF transitive")
    assert t.run_python("print(2**10)") == "1024"
    ok, msg = t.run("run_python", {"code": "1/0"})
    assert not ok and "ZeroDivisionError" in msg
    t.record_score("normalization", 40)
    assert "WEAK" in t.get_progress()
    ok, _ = t.run("no_such_tool", {})
    assert not ok


def test_full_loop_with_self_correction(tmp_path):
    llm = FakeLLM([
        J(steps=[{"task": "Find weak topics and plan 3 days"}]),                              # PLAN
        Reply("Plan with 0 days first.", [call("make_study_plan", topics=["DBMS"], days=0, hours_per_day=2)]),  # bad args
        Reply("Fixing days.", [call("make_study_plan", topics=["DBMS"], days=3, hours_per_day=2)]),             # corrected
        Reply("Here is your plan!"),                                                          # step result
        J(complete=True),                                                                     # REFLECT (1-step plan: result = final)
    ])
    agent = ExamAgent(llm, NOTES, tmp_path / "p.json")
    events = list(agent.run("plan my DBMS exam"))
    obs = [e for e in events if e["type"] == "observation"]
    assert obs[0]["ok"] is False and "ERROR" in obs[0]["text"]      # failure seen
    assert obs[1]["ok"] is True and "Day 1" in obs[1]["text"]        # recovered
    assert events[-1] == {"type": "final", "text": "Here is your plan!"}
    assert len(agent.history) == 1                                  # short-term memory saved


def test_reflection_adds_step(tmp_path):
    llm = FakeLLM([
        J(steps=[{"task": "Explain BCNF"}]),
        Reply("BCNF is stricter."),
        J(complete=False, issue="no example", extra_steps=["Add an example"]),
        Reply("Example: ..."),
        J(complete=True),
        Reply("final"),
    ])
    events = list(ExamAgent(llm, NOTES, tmp_path / "p.json").run("explain BCNF"))
    assert sum(e["type"] == "step" for e in events) == 2


def test_bad_plan_json_falls_back(tmp_path):
    llm = FakeLLM([Reply("not json"), Reply("still not json"), Reply("answer"), J(complete=True), Reply("done")])
    events = list(ExamAgent(llm, NOTES, tmp_path / "p.json").run("hi"))
    assert events[-1]["text"] == "answer"   # single-step plan: step result is the final answer
