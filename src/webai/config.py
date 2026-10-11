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

def get_settings():
    load_dotenv()
    return Settings(
        base_url=os.getenv('WEBAI_LLM_BASE_URL','https://openrouter.ai/api/v1').rstrip('/'),
        model=os.getenv('WEBAI_LLM_MODEL','openrouter/free'),
        api_key=os.getenv('WEBAI_LLM_API_KEY',''),
        timeout=float(os.getenv('WEBAI_LLM_TIMEOUT','30')),
        max_steps=max(1,min(int(os.getenv('WEBAI_MAX_STEPS','12')),40)),
        headless=os.getenv('WEBAI_HEADLESS','false').lower() in {'1','true','yes'},
        vision_enabled=os.getenv('WEBAI_VISION_ENABLED','false').lower() in {'1','true','yes'},
        memory_path=os.getenv('WEBAI_MEMORY_PATH','webai_memory.sqlite3'),
        artifact_dir=os.getenv('WEBAI_ARTIFACT_DIR','artifacts'))
