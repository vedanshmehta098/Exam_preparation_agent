"""Tiny client for any OpenAI-compatible chat API (Groq, Gemini, OpenAI, Ollama...).

Uses plain `requests`, so there is no SDK to install.
Configure with environment variables (or a .env file):
    LLM_API_KEY   your key
    LLM_BASE_URL  default: Groq  (https://api.groq.com/openai/v1)
    LLM_MODEL     default: llama-3.3-70b-versatile
"""
import os
import re
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model wrote it


@dataclass
class Reply:
    content: str = ""
    tool_calls: list = field(default_factory=list)


class LLMError(Exception):
    pass


class LLM:
    def __init__(self):
        self.key = os.getenv("LLM_API_KEY")
        if not self.key:
            raise LLMError("LLM_API_KEY is not set. Copy .env.example to .env and add your key.")
        # Pick sensible defaults from the key prefix: xAI Grok keys start with "xai-", Groq keys with "gsk_"
        default_base = "https://api.x.ai/v1" if self.key.startswith("xai-") else "https://api.groq.com/openai/v1"
        self.base = os.getenv("LLM_BASE_URL", default_base).rstrip("/")
        if self.key.startswith("gsk_") and "x.ai" in self.base:
            raise LLMError("Your key starts with gsk_ (a Groq key) but LLM_BASE_URL points to x.ai. "
                           "Delete the LLM_BASE_URL line from .env (or set https://api.groq.com/openai/v1).")
        if self.key.startswith("xai-") and "groq" in self.base:
            raise LLMError("Your key starts with xai- (an xAI Grok key) but LLM_BASE_URL points to Groq. "
                           "Set LLM_BASE_URL=https://api.x.ai/v1.")
        self.model = os.getenv("LLM_MODEL") or self._pick_model()

    def _available_models(self):
        r = requests.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"}, timeout=20)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    # Chat models known to support tool calling, best first. Anything else is only a last resort.
    PREFERRED = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant",
                 "meta-llama/llama-4-scout", "qwen/qwen3-32b", "grok"]
    NOT_CHAT = ("image", "vision", "imagine", "whisper", "tts", "orpheus", "playai", "embed", "guard", "safeguard",
                "speech", "audio", "transcribe", "prompt-guard")

    def _pick_model(self, skip=()):
        """Ask the provider which models this key can use and pick the best chat model (not in `skip`)."""
        try:
            ids = self._available_models()
        except Exception as e:
            raise LLMError(f"Could not list models ({e}). Set LLM_MODEL in .env.")
        chat = [i for i in ids if i not in skip and not any(b in i.lower() for b in self.NOT_CHAT)]
        for pref in self.PREFERRED:
            for i in chat:
                if pref in i:
                    return i
        if not chat:
            raise LLMError("No usable chat models found for this key. Set LLM_MODEL in .env.")
        return chat[0]

    @staticmethod
    def _retry_after(r):
        """Seconds to wait after a 429: Retry-After header, or 'try again in 12.3s / 450ms' in the message."""
        try:
            if r.headers.get("retry-after"):
                return min(float(r.headers["retry-after"]) + 0.5, 60)
        except ValueError:
            pass
        m = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)(ms|s)", r.text)
        if m:
            secs = int(m.group(1) or 0) * 60 + float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
            return min(secs + 0.5, 60)
        return 10

    def chat(self, messages, tools=None, json_mode=False, temperature=0.2) -> Reply:
        """One model call. Retries on rate limits / network errors / malformed tool calls."""
        body = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last = None
        for attempt in range(8):
            try:
                r = requests.post(
                    f"{self.base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json=body,
                    timeout=60,
                )
                if r.status_code in (400, 404) and "model" in r.text and (
                        r.status_code == 404 or "terms" in r.text or "decommission" in r.text):
                    # This model isn't usable with this key: switch to the next best one automatically.
                    tried = self.__dict__.setdefault("_tried", set())
                    tried.add(self.model)
                    bad = self.model
                    self.model = body["model"] = self._pick_model(skip=tried)
                    print(f"[llm] model '{bad}' unusable, switched to '{self.model}'")
                    continue
                if r.status_code == 429:  # per-minute token limit: wait as long as the server asks, then retry
                    wait = self._retry_after(r)
                    print(f"[llm] rate limit hit, waiting {wait:.0f}s ...")
                    last = LLMError("rate limit (free-tier tokens per minute)")
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                msg = r.json()["choices"][0]["message"]
                calls = [ToolCall(c["id"], c["function"]["name"], c["function"].get("arguments") or "{}")
                         for c in (msg.get("tool_calls") or [])]
                return Reply(content=msg.get("content") or "", tool_calls=calls)
            except LLMError as e:
                last = e
                time.sleep(min(2 ** attempt, 8))
            except Exception as e:
                last = e
                time.sleep(min(2 ** attempt, 8))  # back-off: 1s, 2s, 4s, 8s
        raise LLMError(f"LLM call failed after retries: {last}")
