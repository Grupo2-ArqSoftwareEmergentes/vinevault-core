from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    DATABASE_URL: str = ""
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "vinevault_core_db"
    DATABASE_USER: str = "postgres"
    DATABASE_PASSWORD: str = "postgres"
    DATABASE_SSL: bool = False

    SECRET_KEY: str = "mi_clave_secreta_muy_segura"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    SERVICE_NAME: str = "vinevault-core"
    SERVICE_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:4200,http://127.0.0.1:4200"

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_CONSUMER_GROUP_ID: str = "vinevault-core"

    BILLING_SERVICE_URL: str = "http://localhost:8001"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Return an async PostgreSQL URL from DATABASE_URL or component parts."""
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self.DATABASE_URL

        password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
