from __future__ import annotations

import json
import os

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore[assignment]


class GroqTaskRunner:
    """Real structured runner, replaced by a deterministic fake in pytest."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise ValueError("GROQ_API_KEY is required to call Groq.")
        if Groq is None:
            raise ImportError("Install groq before running the application.")
        self.client = Groq(api_key=key)

    def __call__(self, task):
        response = self.client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            messages=[{"role": "user", "content": task.description}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
