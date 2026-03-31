from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "jpop"
    db_user: str = "postgres"
    db_password: str

    # KOPIS
    kopis_api_key: str
    kopis_base_url: str = "http://www.kopis.or.kr/openApi/restful"

    # MusicBrainz
    musicbrainz_app_name: str = "jpop-data-collector"
    musicbrainz_app_version: str = "0.1.0"
    musicbrainz_contact: str
    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
