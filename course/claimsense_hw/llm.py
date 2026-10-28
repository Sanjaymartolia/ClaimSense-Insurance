"""Talking to models through OpenRouter.

    chat_model()   a LangChain chat model; has .bind_tools() for TODO 4
    chat_json()    one prompt in, one parsed JSON object out

Every call is cached in .cache/llm.sqlite: the same request twice costs nothing.
Delete .cache/ when you want fresh answers.
"""

import json
import os

from dotenv import load_dotenv
from langchain_community.cache import SQLiteCache
from langchain_core.globals import set_llm_cache
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from . import config

load_dotenv(config.REPO / ".env")  # the key lives there; never print it, never commit it
if config.LLM_CACHE:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(config.CACHE_DIR / "llm.sqlite")))


def chat_model(model=None, **kw):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. At the repo root: "
            "cp .env.example .env, then paste your key into .env"
        )
    return ChatOpenAI(
        model=model or config.TOOL_MODEL,
        base_url="https://openrouter.ai/api/v1",
        api_key=key,
        temperature=config.TEMPERATURE,
        max_tokens=config.MAX_TOKENS,
        **kw,
    )


def as_text(value):
    """Message content may be a string OR a list of parts like [{"type": "text", ...}]."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or "")
    if isinstance(value, (list, tuple)):
        return " ".join(as_text(v) for v in value).strip()
    return str(value)


def parse_json(text):
    """Models wrap JSON in ``` fences or chat around it; take the outermost {...}."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def chat_json(user, system, model=None):
    reply = chat_model(model).invoke([SystemMessage(system), HumanMessage(user)])
    return parse_json(as_text(reply.content))
