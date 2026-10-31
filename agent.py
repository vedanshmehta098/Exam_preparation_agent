"""Exam Preparation Agent - the brain.

A small state graph written by hand (no framework needed):

    PLAN  ->  EXECUTE (ReAct loop, one plan step at a time)  ->  REFLECT  ->  FINALIZE
                  ^                                                |
                  +---------------- missing something? ------------+

Every node is a generator that yields trace events (so the UI can show the agent's
thinking live) and returns the name of the next node.
"""
import json

from llm import LLMError
from tools import SCHEMAS, ToolBox

MAX_TOOL_ROUNDS = 6   # per plan step
MAX_REPLANS = 1       # how many times reflection may add extra steps

SYSTEM = """You are ExamBuddy, an exam-preparation agent for a university student.
- For subject content, call search_notes FIRST. Use wiki_lookup only if the notes do not cover it.
- To make a study schedule, call make_study_plan (check get_progress first to find weak topics).
- To quiz the student: write the questions from the notes. To grade their answers, re-check the notes,
  give a score, then call record_score.
- For calculations use run_python.
- If a tool returns ERROR, read the message, fix your arguments or switch tools. Never repeat the same failing call.
- Before each tool call, write ONE short sentence saying why. Be concise and student-friendly."""


def ev(kind, **kw):
    return {"type": kind, **kw}


def format_event(e):
    """One-line text version of a trace event (used by the terminal UI)."""
    t = e["type"]
    if t == "node":      return f"\n=== NODE: {e['name'].upper()} ==="
    if t == "plan":      return "PLAN:\n" + "\n".join(f"  {i + 1}. {s['task']}" for i, s in enumerate(e["steps"]))
    if t == "step":      return f"-- Step {e['n']}: {e['task']}"
    if t == "thought":   return f"THOUGHT: {e['text']}"
    if t == "tool_call": return f"TOOL CALL: {e['name']}({json.dumps(e['args'])})"
    if t == "observation":
        return f"OBSERVATION [{'ok' if e['ok'] else 'ERROR'}]: {e['text'][:300]}"
    if t == "reflection": return f"REFLECTION: {e['text']}"
    if t == "error":     return f"!! {e['text']}"
    if t == "final":     return "\nFINAL ANSWER:\n" + e["text"]
    return str(e)


def parse_json(text):
    """Models sometimes wrap JSON in ```fences``` or add chatter; pull out the first {...} block."""
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("no JSON object found")
    return json.loads(text[s:e + 1])


class ExamAgent:
    def __init__(self, llm, notes_dir="notes", progress_file="progress.json"):
        self.llm = llm
        self.tools = ToolBox(notes_dir, progress_file)
        self.history = []  # SHORT-TERM MEMORY: (student message, agent answer) of this session

    # ================================================================== public entry point
    def run(self, goal):
        state = {"goal": goal, "plan": [], "replans": 0}
        node = "plan"
        try:
            while node != "end":
                yield ev("node", name=node)
                node = yield from getattr(self, "node_" + node)(state)
        except LLMError as e:
            yield ev("error", text=f"The language model is unavailable: {e}")
            yield ev("final", text="Sorry, I couldn't reach the AI model. Check your API key / internet and try again.")

    # ================================================================== NODE 1: plan
    def node_plan(self, state):
        prompt = (f"Student request: {state['goal']}\n\nRecent conversation:\n{self._history_text()}\n\n"
                  "Break the request into 1-5 small, ordered steps. A simple question needs only 1 step.\n"
                  'Reply as JSON: {"steps": [{"task": "..."}]}')
        steps = None
        for _ in range(2):  # SELF-CORRECTION: if the JSON is broken, ask once more
            try:
                reply = self.llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                                      json_mode=True)
                steps = [{"task": s["task"], "status": "pending", "result": ""} for s in parse_json(reply.content)["steps"]]
                if steps:
                    break
            except (ValueError, KeyError, TypeError):
                prompt += "\nYour last reply was not valid JSON in the required shape. Try again."
        if not steps:  # FALLBACK: treat the whole request as a single step
            steps = [{"task": state["goal"], "status": "pending", "result": ""}]
        state["plan"] = steps
        yield ev("plan", steps=steps)
        return "execute"

    # ================================================================== NODE 2: execute one step (ReAct loop)
    def node_execute(self, state):
        idx = next(i for i, s in enumerate(state["plan"]) if s["status"] == "pending")
        step = state["plan"][idx]
        yield ev("step", n=idx + 1, task=step["task"])

        done = "\n".join(f"- {s['task']} => {s['result'][:600]}" for s in state["plan"] if s["status"] == "done") or "(nothing yet)"
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Overall request: {state['goal']}\n\nConversation so far:\n{self._history_text()}\n\n"
                                            f"Finished steps:\n{done}\n\nDo ONLY this step now: {step['task']}\n"
                                            "When finished, reply with the result of this step (no tool call)."}]
        seen, fails, result = set(), {}, None

        for _ in range(MAX_TOOL_ROUNDS):
            reply = self.llm.chat(msgs, tools=SCHEMAS)
            if reply.content.strip() and reply.tool_calls:
                yield ev("thought", text=reply.content.strip())
            if not reply.tool_calls:
                result = reply.content.strip()
                break

            msgs.append({"role": "assistant", "content": reply.content or None,
                         "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                                        for c in reply.tool_calls]})
            for c in reply.tool_calls:
                try:
                    args = json.loads(c.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                yield ev("tool_call", name=c.name, args=args if args is not None else c.arguments)

                key = (c.name, c.arguments)
                if args is None:
                    ok, out = False, "ERROR: your arguments were not valid JSON. Send a valid JSON object."
                elif key in seen:  # LOOP GUARD: same call twice is pointless
                    ok, out = False, "ERROR: you already made this exact call. Use its result or try a different approach."
                else:
                    seen.add(key)
                    ok, out = self.tools.run(c.name, args)

                if not ok:  # REFLECTION on failure: nudge the model toward a fallback
                    fails[c.name] = fails.get(c.name, 0) + 1
                    if fails[c.name] >= 2:
                        out += f"\nHINT: {c.name} failed {fails[c.name]} times. Stop using it; use another tool or answer with what you have."
                yield ev("observation", ok=ok, text=out)
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": out})
        else:
            # BUDGET EXHAUSTED: force a partial answer rather than looping forever
            msgs.append({"role": "user", "content": "Tool budget used up. Give the best result you can from what you have, "
                                                    "and clearly say what is missing."})
            result = self.llm.chat(msgs).content.strip()

        step["status"], step["result"] = "done", result
        yield ev("observation", ok=True, text=f"Step {idx + 1} result: {result[:300]}")
        return "execute" if any(s["status"] == "pending" for s in state["plan"]) else "reflect"

    # ================================================================== NODE 3: reflect (self-check)
    def node_reflect(self, state):
        results = "\n".join(f"{i + 1}. {s['task']} => {s['result'][:500]}" for i, s in enumerate(state["plan"]))
        prompt = (f"Student request: {state['goal']}\n\nWork done:\n{results}\n\n"
                  "Does this fully satisfy the request? Look for ERROR results, missing parts, or invented facts.\n"
                  'Reply as JSON: {"complete": true/false, "issue": "short reason", "extra_steps": ["..."]}')
        try:
            verdict = parse_json(self.llm.chat([{"role": "user", "content": prompt}], json_mode=True).content)
        except (ValueError, KeyError):
            verdict = {"complete": True}  # if the checker itself fails, don't block the answer

        if not verdict.get("complete", True) and verdict.get("extra_steps") and state["replans"] < MAX_REPLANS:
            state["replans"] += 1
            state["plan"] += [{"task": t, "status": "pending", "result": ""} for t in verdict["extra_steps"][:3]]
            yield ev("reflection", text=f"Not complete: {verdict.get('issue', '')}. Adding {len(verdict['extra_steps'][:3])} step(s).")
            return "execute"
        yield ev("reflection", text="Looks complete." if verdict.get("complete", True)
                 else f"Still imperfect ({verdict.get('issue', '')}); answering with what I have.")
        return "finalize"

    # ================================================================== NODE 4: final answer
    def node_finalize(self, state):
        if len(state["plan"]) == 1 and state["plan"][0]["result"]:
            # One-step plan: the step result is already the student-facing reply, so save an LLM call (and tokens).
            text = state["plan"][0]["result"]
            self.history.append((state["goal"], text))
            yield ev("final", text=text)
            return "end"
        results = "\n\n".join(f"Step {i + 1} ({s['task']}):\n{s['result']}" for i, s in enumerate(state["plan"]))
        prompt = (f"Student request: {state['goal']}\n\nResults of my work:\n{results}\n\n"
                  "Write the final reply for the student: clear, friendly, well formatted (short headings / bullets). "
                  "Use only facts from the results above. If something could not be done, say so honestly.")
        try:
            text = self.llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]).content.strip()
        except LLMError:
            text = results  # FALLBACK: at least show the raw results
        self.history.append((state["goal"], text))
        yield ev("final", text=text)
        return "end"

    def _history_text(self):
        return "\n".join(f"Student: {u}\nExamBuddy: {a[:500]}" for u, a in self.history[-3:]) or "(first message)"
