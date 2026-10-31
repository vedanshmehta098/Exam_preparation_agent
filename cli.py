"""Terminal version.  Run:  python cli.py   (or: python cli.py "your question")"""
import sys

from agent import ExamAgent, format_event
from llm import LLM, LLMError

try:
    agent = ExamAgent(LLM())
except LLMError as e:
    sys.exit(str(e))


def ask(q):
    for e in agent.run(q):
        print(format_event(e))


if len(sys.argv) > 1:
    ask(" ".join(sys.argv[1:]))
else:
    print("ExamBuddy ready. Type 'exit' to quit.")
    while (q := input("\nYou> ").strip()) and q.lower() != "exit":
        ask(q)
