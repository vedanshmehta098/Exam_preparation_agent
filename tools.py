"""The agent's 6 tools. Each one is a plain Python function.

Every tool either returns a string or raises ToolError with a helpful message.
The agent loop catches ToolError and feeds the message back to the model so it can
self-correct (fix its arguments, or switch to a different tool).
"""
import json
import math
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests


class ToolError(Exception):
    pass


STOP = set("a an the of to in on for and or is are was were be by with as at from that this it its what which how why do does "
           "explain define describe difference between about into".split())


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


class ToolBox:
    def __init__(self, notes_dir="notes", progress_file="progress.json"):
        self.notes_dir = Path(notes_dir)
        self.progress_file = Path(progress_file)

    # ------------------------------------------------------------------ 1. notes search (RAG-lite)
    def search_notes(self, query: str, top_k: int = 3) -> str:
        files = sorted(list(self.notes_dir.glob("*.md")) + list(self.notes_dir.glob("*.txt")))
        if not files:
            raise ToolError("No notes uploaded yet. Use wiki_lookup instead, or ask the student to upload notes.")
        q = _words(query)
        if not q:
            raise ToolError("Query is empty. Give a topic or keywords to search for.")
        scored = []
        for f in files:
            for chunk in re.split(r"\n\s*\n", f.read_text(encoding="utf-8", errors="ignore")):
                chunk = chunk.strip()
                if len(chunk) < 30:
                    continue
                tf = Counter(_words(chunk))
                hits = sum(1 for w in set(q) if tf[w])  # how many query words appear
                score = hits * 10 + sum(tf[w] for w in set(q))
                if hits:
                    scored.append((score, f.name, chunk))
        if not scored:
            return f"No relevant passage found in the notes for '{query}'. Try other keywords or wiki_lookup."
        scored.sort(reverse=True)
        return "\n\n".join(f"[{name}] {chunk[:500]}" for _, name, chunk in scored[:int(top_k)])

    # ------------------------------------------------------------------ 2. Wikipedia (external API)
    def wiki_lookup(self, topic: str) -> str:
        hdr = {"User-Agent": "ExamPrepAgent/1.0 (student project)"}
        try:
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(topic.replace(" ", "_"))
            r = requests.get(url, headers=hdr, timeout=8)
            if r.status_code == 404:  # exact title not found -> ask Wikipedia's search for the closest one
                s = requests.get("https://en.wikipedia.org/w/api.php", headers=hdr, timeout=8,
                                 params={"action": "opensearch", "search": topic, "limit": 1, "format": "json"}).json()
                if not s[1]:
                    raise ToolError(f"Wikipedia has no page for '{topic}'. Try a more standard term or use search_notes.")
                r = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(s[1][0].replace(" ", "_")),
                                 headers=hdr, timeout=8)
            r.raise_for_status()
            d = r.json()
            return f"{d.get('title')}: {d.get('extract', '')[:1200]}"
        except ToolError:
            raise
        except requests.RequestException as e:
            raise ToolError(f"Wikipedia is unreachable ({type(e).__name__}). Fall back to search_notes.")

    # ------------------------------------------------------------------ 3. study planner
    def make_study_plan(self, topics: list, days: int, hours_per_day: float, weak_topics: list = None) -> str:
        if not isinstance(topics, list) or not topics:
            raise ToolError("'topics' must be a non-empty list of strings.")
        days, hours_per_day = int(days), float(hours_per_day)
        if not 1 <= days <= 60:
            raise ToolError("'days' must be between 1 and 60.")
        if not 0.5 <= hours_per_day <= 16:
            raise ToolError("'hours_per_day' must be between 0.5 and 16.")
        weak = {w.lower() for w in (weak_topics or [])}

        revision_day = days >= 3                       # keep the last day for revision + mock test
        study_days = days - 1 if revision_day else days
        per_day = int(hours_per_day * 2)               # work in 30-minute slots
        total = study_days * per_day
        if len(topics) > total:
            need = math.ceil(len(topics) / 2)
            raise ToolError(f"{len(topics)} topics do not fit in {total} half-hour slots. "
                            f"Need at least {need}h of study time: raise days/hours or cut topics.")

        weights = [1.5 if t.lower() in weak else 1.0 for t in topics]   # weak topics get 50% more time
        slots = [max(1, round(total * w / sum(weights))) for w in weights]
        while sum(slots) != total:                     # fix rounding so we use exactly the time available
            i = slots.index(max(slots)) if sum(slots) > total else slots.index(min(slots))
            slots[i] += -1 if sum(slots) > total else 1

        queue = [t for t, n in zip(topics, slots) for _ in range(n)]
        lines = []
        for d in range(study_days):
            chunk = queue[d * per_day:(d + 1) * per_day]
            parts = [f"{t} ({c / 2:g}h)" for t, c in Counter(chunk).items()]
            lines.append(f"Day {d + 1}: " + ", ".join(parts))
        if revision_day:
            lines.append(f"Day {days}: Revise all topics + 1 mock test ({hours_per_day:g}h)")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 4. Python sandbox
    def run_python(self, code: str) -> str:
        try:
            p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            raise ToolError("Code ran longer than 5 seconds and was stopped. Simplify it.")
        if p.returncode != 0:
            raise ToolError("Python error: " + p.stderr.strip().splitlines()[-1])
        return (p.stdout.strip() or "(code ran but printed nothing - use print())")[:1500]

    # ------------------------------------------------------------------ 5 + 6. progress memory (long-term)
    def _load(self):
        return json.loads(self.progress_file.read_text()) if self.progress_file.exists() else {}

    def record_score(self, topic: str, score_percent: float) -> str:
        score = float(score_percent)
        if not 0 <= score <= 100:
            raise ToolError("score_percent must be between 0 and 100.")
        data = self._load()
        data.setdefault(topic.strip().title(), []).append({"score": score, "date": str(date.today())})
        self.progress_file.write_text(json.dumps(data, indent=2))
        return f"Saved {score:g}% for {topic}."

    def get_progress(self) -> str:
        data = self._load()
        if not data:
            return "No quiz scores recorded yet."
        out = []
        for topic, rows in data.items():
            last = rows[-1]["score"]
            out.append(f"{topic}: latest {last:g}% over {len(rows)} attempt(s) -> {'WEAK' if last < 60 else 'ok'}")
        return "\n".join(out)

    # ------------------------------------------------------------------ dispatcher used by the agent
    def run(self, name: str, args: dict):
        """Returns (ok, text). Never raises: errors become observations the model can react to."""
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        if fn is None:
            return False, f"ERROR: unknown tool '{name}'. Available tools: {', '.join(sorted(TOOL_NAMES))}."
        try:
            return True, fn(**args)
        except ToolError as e:
            return False, f"ERROR: {e}"
        except TypeError as e:
            return False, f"ERROR: bad arguments for {name}: {e}"
        except (ValueError, KeyError) as e:
            return False, f"ERROR: invalid value for {name}: {e}"


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


SCHEMAS = [
    _fn("search_notes", "Search the student's uploaded notes. ALWAYS try this first for any subject content.",
        {"query": {"type": "string"}, "top_k": {"type": "integer"}}, ["query"]),
    _fn("wiki_lookup", "Get a short Wikipedia summary. Use when the notes do not cover a topic.",
        {"topic": {"type": "string"}}, ["topic"]),
    _fn("make_study_plan", "Build a day-by-day study schedule. Weak topics get extra time; last day is revision + mock test.",
        {"topics": {"type": "array", "items": {"type": "string"}}, "days": {"type": "integer"},
         "hours_per_day": {"type": "number"}, "weak_topics": {"type": "array", "items": {"type": "string"}}},
        ["topics", "days", "hours_per_day"]),
    _fn("run_python", "Run a short Python snippet (5s limit) for numeric / worked problems. Must print() the result.",
        {"code": {"type": "string"}}, ["code"]),
    _fn("record_score", "Save a quiz score (0-100) for a topic so progress is tracked across sessions.",
        {"topic": {"type": "string"}, "score_percent": {"type": "number"}}, ["topic", "score_percent"]),
    _fn("get_progress", "Show saved quiz scores per topic and which topics are WEAK (<60%).", {}, []),
]
TOOL_NAMES = {s["function"]["name"] for s in SCHEMAS}
