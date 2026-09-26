import os
from pathlib import Path

from dotenv import load_dotenv

from .schema import Limits


def load_config():
    load_dotenv(override=False)


def data_root() -> Path:
    return Path(os.getenv("PAPER_AGENT_DATA", "data")).resolve()


def model_name() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def reasoning_effort():
    return os.getenv("OPENAI_REASONING_EFFORT") or None


def default_limits() -> Limits:
    mapping = {"candidates": "MAX_CANDIDATES", "fulltexts": "MAX_FULLTEXTS", "target": "TARGET_PAPERS",
               "searches": "MAX_SEARCHES", "model_calls": "MAX_MODEL_CALLS", "finalization_calls": "MAX_FINALIZATION_CALLS", "tool_calls": "MAX_TOOL_CALLS", "stalled_turns": "MAX_STALLED_TURNS",
               "seconds": "MAX_SECONDS", "tokens": "MAX_TOKENS", "output_tokens": "MAX_OUTPUT_TOKENS",
               "network_timeout": "NETWORK_TIMEOUT", "retries": "NETWORK_RETRIES"}
    values = {}
    for key, env in mapping.items():
        value = os.getenv(env, "").strip()
        if value:
            values[key] = (None if key in {"model_calls", "finalization_calls"}
                           and value.lower() == "auto" else int(value))
    return Limits(**values)
