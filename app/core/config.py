import os

from pydantic_settings import BaseSettings 
from app.utils.ngrok_utils import get_server_domain

class Setting(BaseSettings):
    """Application settings"""
    
    # Deepgram configuration
    DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
    DEEPGRAM_WS_URL: str = os.getenv("DEEPGRAM_WS_URL", "wss://agent.deepgram.com/v1/agent/converse")
    
    #server configuration - dynamically get ngrok URL
    @property
    def SERVER_DOMAIN(self) -> str:
        return get_server_domain()
    
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))
    
    # Teler configuration
    TELER_API_KEY: str = os.getenv("TELER_API_KEY", "")
    
    # AI and Call Configuration 
    SYSTEM_MESSAGE: str = "Speak clearly, briefly and concise. Confirm understanding before taking actions."
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    
# settings instance
settings = Setting()