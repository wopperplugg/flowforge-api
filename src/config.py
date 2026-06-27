from functools import cached_property
from typing import Literal
from pydantic import Field, AnyUrl, PostgresDsn, RedisDsn, computed_field, model_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="FlowForge API", alias="APP_NAME")
    app_env: Literal["local", "test", "staging", "production"] = Field(default="local", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_secret_key: SecretStr = Field(default="local-development-secret-change-me-32-bytes", alias="APP_SECRET_KEY")
    webhook_secret_encryption_key: SecretStr | None = None
    app_cors_origins: list[AnyUrl] = Field(default_factory=list, alias="APP_CORS_ORIGINS")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT", ge=1, le=65535)
    postgres_db: str = Field(default="flowforge", alias="POSTGRES_DB")
    postgres_user: str = Field(default="flowforge", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(default="flowforge", alias="POSTGRES_PASSWORD")

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT", ge=1, le=65535)
    redis_db: int = Field(default=0, alias="REDIS_DB")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=30, gt=0)
    jwt_issuer: str = "flowforge-api"
    jwt_audience: str = "flowforge-clients"
    rate_limit_requests: int = Field(default=120, gt=0)
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    webhook_timeout_seconds: float = Field(default=5.0, gt=0)


    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env == "production":
            weak_secret = self.app_secret_key.get_secret_value() == "local-development-secret-change-me-32-bytes"
            weak_postgres_password = self.postgres_password.get_secret_value() == "flowforge"
            missing_webhook_key =  not self.webhook_secret_encryption_key
            if weak_secret or weak_postgres_password or missing_webhook_key:
                msg = (
                    "Production requires explicit APP_SECRET_KEY, POSTGRES_PASSWORD, "
                    "and WEBHOOK_SECRET_ENCRYPTION_KEY"
                )
                raise ValueError(msg)
            return self
        return self

    @computed_field
    @cached_property
    def postgres_dsn(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
    
    @computed_field
    @cached_property
    def redis_dsn(self) -> RedisDsn:
        return RedisDsn.build(
            scheme="redis",
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )

settings = Settings()
