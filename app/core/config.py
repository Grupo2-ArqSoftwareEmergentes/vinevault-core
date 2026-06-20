import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Base de datos - Convertir a async si es necesario
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/auth_db")
    
    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "mi_clave_secreta_muy_segura")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
    
    # Servicio
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "vinevault-core")
    SERVICE_VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Kafka (opcional)
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_CONSUMER_GROUP_ID: str = os.getenv("KAFKA_CONSUMER_GROUP_ID", "vinevault-core")
    
    # Billing Service (opcional)
    BILLING_SERVICE_URL: str = os.getenv("BILLING_SERVICE_URL", "http://localhost:8001")
    
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Convertir DATABASE_URL a async (postgresql:// → postgresql+asyncpg://)"""
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        return self.DATABASE_URL
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()