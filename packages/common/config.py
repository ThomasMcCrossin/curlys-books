"""
Application configuration using Pydantic Settings
Reads from environment variables and .env file
"""
from functools import lru_cache
from typing import Optional
from datetime import date

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Database
    db_user: str = Field(default="curlys_admin", alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")
    db_name: str = Field(default="curlys_books", alias="DB_NAME")
    db_host: str = Field(default="postgres", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    
    @property
    def database_url(self) -> str:
        """Construct database URL"""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    # Redis / Celery
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")
    
    # Application
    environment: str = Field(default="production", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(..., alias="SECRET_KEY")
    
    # Cloudflare Access (SSO)
    cloudflare_access_aud: str = Field(..., alias="CLOUDFLARE_ACCESS_AUD")
    cloudflare_team_domain: str = Field(..., alias="CLOUDFLARE_TEAM_DOMAIN")
    cloudflare_tunnel_id: str = Field(..., alias="CLOUDFLARE_TUNNEL_ID")
    
    # Gmail Integration
    gmail_service_account_json: Optional[str] = Field(default=None, alias="GMAIL_SERVICE_ACCOUNT_JSON")
    gmail_impersonate_email: Optional[str] = Field(default=None, alias="GMAIL_IMPERSONATE_EMAIL")
    gmail_corp_address: str = Field(default="receipts+corp@curlys.ca", alias="GMAIL_CORP_ADDRESS")
    gmail_soleprop_address: str = Field(default="receipts+sp@curlys.ca", alias="GMAIL_SOLEPROP_ADDRESS")
    
    # Shopify Integration
    shopify_canteen_store: Optional[str] = Field(default=None, alias="SHOPIFY_CANTEEN_STORE")
    shopify_canteen_access_token: Optional[str] = Field(default=None, alias="SHOPIFY_CANTEEN_ACCESS_TOKEN")
    shopify_sports_store: Optional[str] = Field(default=None, alias="SHOPIFY_SPORTS_STORE")
    shopify_sports_access_token: Optional[str] = Field(default=None, alias="SHOPIFY_SPORTS_ACCESS_TOKEN")
    
    # OCR / Parsing
    tesseract_path: str = Field(default="/usr/bin/tesseract", alias="TESSERACT_PATH")
    tesseract_confidence_threshold: int = Field(default=90, alias="TESSERACT_CONFIDENCE_THRESHOLD")
    
    # AWS Textract (fallback when confidence < threshold)
    textract_fallback_enabled: bool = Field(default=True, alias="TEXTRACT_FALLBACK_ENABLED")
    aws_access_key_id: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    aws_textract_region: str = Field(default="us-east-1", alias="AWS_TEXTRACT_REGION")
    
    # Tax Rates (Nova Scotia)
    hst_rate_current: float = Field(default=0.14, alias="HST_RATE_CURRENT")
    hst_rate_previous: float = Field(default=0.15, alias="HST_RATE_PREVIOUS")
    hst_rate_change_date: str = Field(default="2025-04-01", alias="HST_RATE_CHANGE_DATE")
    
    @property
    def hst_rate_change_date_parsed(self) -> date:
        """Parse HST rate change date"""
        year, month, day = self.hst_rate_change_date.split("-")
        return date(int(year), int(month), int(day))
    
    # Business Configuration
    corp_fiscal_year_end: str = Field(default="05-31", alias="CORP_FISCAL_YEAR_END")
    soleprop_fiscal_year_end: str = Field(default="12-31", alias="SOLEPROP_FISCAL_YEAR_END")
    capitalization_threshold: int = Field(default=2500, alias="CAPITALIZATION_THRESHOLD")
    
    # Matching Rules
    match_amount_tolerance_percent: float = Field(default=0.5, alias="MATCH_AMOUNT_TOLERANCE_PERCENT")
    match_amount_tolerance_dollars: float = Field(default=0.02, alias="MATCH_AMOUNT_TOLERANCE_DOLLARS")
    match_date_window_before_days: int = Field(default=3, alias="MATCH_DATE_WINDOW_BEFORE_DAYS")
    match_date_window_after_days: int = Field(default=5, alias="MATCH_DATE_WINDOW_AFTER_DAYS")
    
    # PAD Matching
    pad_date_window_before_days: int = Field(default=2, alias="PAD_DATE_WINDOW_BEFORE_DAYS")
    pad_date_window_after_days: int = Field(default=5, alias="PAD_DATE_WINDOW_AFTER_DAYS")
    pad_amount_tolerance_percent: float = Field(default=0.5, alias="PAD_AMOUNT_TOLERANCE_PERCENT")
    pad_amount_tolerance_dollars: float = Field(default=0.02, alias="PAD_AMOUNT_TOLERANCE_DOLLARS")
    
    # Reimbursements
    reimbursement_batch_day: int = Field(default=0, alias="REIMBURSEMENT_BATCH_DAY")  # Monday
    reimbursement_batch_time: str = Field(default="09:00", alias="REIMBURSEMENT_BATCH_TIME")
    
    # Storage
    receipt_storage_path: str = Field(default="/srv/curlys-books/objects", alias="RECEIPT_STORAGE_PATH")
    receipt_library_path: str = Field(default="/library", alias="RECEIPT_LIBRARY_PATH")
    
    # Google Drive Backup
    gdrive_backup_enabled: bool = Field(default=True, alias="GDRIVE_BACKUP_ENABLED")
    gdrive_backup_folder_id: Optional[str] = Field(default=None, alias="GDRIVE_BACKUP_FOLDER_ID")
    gdrive_service_account_json: Optional[str] = Field(default=None, alias="GDRIVE_SERVICE_ACCOUNT_JSON")
    backup_retention_days: int = Field(default=2555, alias="BACKUP_RETENTION_DAYS")  # 7 years
    
    # Monitoring
    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")
    
    # Development
    debug: bool = Field(default=False, alias="DEBUG")
    skip_auth_validation: bool = Field(default=False, alias="SKIP_AUTH_VALIDATION")
    use_mock_data: bool = Field(default=False, alias="USE_MOCK_DATA")
    
    @validator("log_level")
    def validate_log_level(cls, v):
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()
    
    @validator("environment")
    def validate_environment(cls, v):
        """Validate environment"""
        valid_envs = ["development", "staging", "production"]
        if v.lower() not in valid_envs:
            raise ValueError(f"ENVIRONMENT must be one of {valid_envs}")
        return v.lower()


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
settings = get_settings()