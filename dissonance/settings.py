from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    database_url: str = "postgresql://dissonance:dissonance@localhost:5432/dissonance"
    dissonance_env: str = "dev"


settings = Settings()
