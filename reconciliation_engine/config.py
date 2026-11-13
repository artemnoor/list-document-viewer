from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    llm_trusted_hosts: list[str] = Field(default_factory=list)
    environment: Literal["local", "production"] = "local"
    api_auth_enabled: bool = False
    api_project_tokens: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_production_authentication(self) -> "Settings":
        if self.environment == "production" and (not self.api_auth_enabled or not self.api_project_tokens):
            raise ValueError("production requires API_AUTH_ENABLED=true and API_PROJECT_TOKENS")
        if self.api_auth_enabled and not self.api_project_tokens:
            raise ValueError("API_AUTH_ENABLED=true requires API_PROJECT_TOKENS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
