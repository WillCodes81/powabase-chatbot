from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    powabase_url: str
    powabase_anon_key: str
    powabase_service_key: str


settings = Settings()
