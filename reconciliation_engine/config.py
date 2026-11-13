from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "Phystech Trace — Reconciliation Engine"
    result_store_dir: str = "./data/results"
    llm_enabled: bool = False
    llm_trusted_local: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 45
    llm_max_candidates: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
