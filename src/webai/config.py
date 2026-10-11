import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    base_url: str
    model: str
    api_key: str
    timeout: float
    max_steps: int
    headless: bool
    vision_enabled: bool
    memory_path: str
    artifact_dir: str
    provider: str = "openrouter"


def _ollama_base_url() -> str:
    # Prefer provider-specific settings so an existing OpenRouter URL in .env
    # cannot accidentally override a switch to Ollama.
    value = (
        os.getenv("WEBAI_OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_BASE_URL")
        or "http://localhost:11434/v1"
    ).rstrip("/")
    # Ollama's OpenAI-compatible API is mounted under /v1.
    if value.endswith(":11434"):
        value += "/v1"
    return value


def get_settings():
    load_dotenv()
    provider = os.getenv(
        "WEBAI_LLM_PROVIDER",
        os.getenv("ACTIVE_LLM_PROVIDER", "openrouter"),
    ).strip().lower()
    if provider in {"local", "ollama-local"}:
        provider = "ollama"

    if provider == "ollama":
        base_url = _ollama_base_url()
        configured_model = os.getenv("WEBAI_OLLAMA_MODEL") or os.getenv("OLLAMA_MODEL")
        # Do not accidentally send the OpenRouter default model name to Ollama.
        generic_model = os.getenv("WEBAI_LLM_MODEL", "")
        model = configured_model or (
            generic_model if generic_model and generic_model != "openrouter/free"
            else "qwen3:4b"
        )
    else:
        base_url = os.getenv(
            "WEBAI_LLM_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        model = os.getenv("WEBAI_LLM_MODEL", "openrouter/free")

    return Settings(
        base_url=base_url,
        model=model,
        api_key=os.getenv("WEBAI_LLM_API_KEY", ""),
        timeout=float(os.getenv("WEBAI_LLM_TIMEOUT", "30")),
        max_steps=max(1, min(int(os.getenv("WEBAI_MAX_STEPS", "12")), 40)),
        headless=os.getenv("WEBAI_HEADLESS", "false").lower() in {"1", "true", "yes"},
        vision_enabled=os.getenv("WEBAI_VISION_ENABLED", "false").lower() in {"1", "true", "yes"},
        memory_path=os.getenv("WEBAI_MEMORY_PATH", "webai_memory.sqlite3"),
        artifact_dir=os.getenv("WEBAI_ARTIFACT_DIR", "artifacts"),
        provider=provider,
    )
