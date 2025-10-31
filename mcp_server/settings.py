"""Configuration settings for the on-prem MCP server."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pydantic settings loaded from environment variables or .env."""

    # HTTP server configuration
    host: str = Field(default="0.0.0.0", description="Bind address for the MCP HTTP server.")
    port: int = Field(default=8088, description="Port for the MCP HTTP server.")

    # LM Studio connectivity
    lmstudio_base_url: str = Field(default="http://127.0.0.1:1234", description="Base URL for LM Studio API.")
    lmstudio_api_key: Optional[str] = Field(default=None, description="Optional API key if LM Studio requires one.")
    lmstudio_model: Optional[str] = Field(default=None, description="Default model identifier served by LM Studio.")

    # Timeouts and limits
    request_timeout_secs: float = Field(default=30.0, description="Timeout for outbound HTTP requests.")
    max_completion_tokens: int = Field(default=1024, description="Max completion tokens for LM Studio completions.")

    # Observability
    enable_access_log: bool = Field(default=True, description="Whether to log each incoming MCP request.")

    class Config:
        env_prefix = "MCP_"
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()


settings = get_settings()
