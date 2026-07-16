from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://portal:portal@localhost:5432/adobe_school_portal"
    redis_url: str = "redis://localhost:6379/0"

    # CY25-H2 (기본 콘솔)
    adobe_org_id: str = ""
    adobe_client_id: str = ""
    adobe_client_secret: str = ""
    adobe_ims_host: str = "https://ims-na1.adobelogin.com"
    adobe_default_product_profile_id: str = ""
    adobe_umapi_host: str = "https://usermanagement.adobe.io"
    adobe_user_country: str = "KR"

    # CY26-H1 (별도 Admin Console — Client ID/Secret 필수, ORG·프로필은 미설정 시 CY25 값 사용)
    adobe_org_id_cy26_h1: str = ""
    adobe_client_id_cy26_h1: str = ""
    adobe_client_secret_cy26_h1: str = ""
    adobe_default_product_profile_id_cy26_h1: str = ""

    sync_max_retries: int = 3
    sync_poll_interval_seconds: float = 2.0
    sync_poll_max_attempts: int = 30

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_exp_hours: int = 8

    admin_api_key: str = ""
    admin_password: str = ""

    log_level: str = "INFO"
    environment: str = "development"

    # TODO(Phase 3): EMAIL_MX_CHECK 플래그 연동
    email_mx_check: bool = False

    # Microsoft 365 / Graph — 로그인 안내 메일 (Adobe@bitzkorea.com)
    email_enabled: bool = False
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    mail_from_address: str = ""
    # Graph /users/{id}/sendMail — 이메일 대신 Azure AD 개체 ID(권장, 공용 사서함)
    mail_from_user_id: str = ""
    portal_public_url: str = "https://adobe.bitzkorea.com"

    login_lock_max_attempts: int = 5
    login_lock_ttl_seconds: int = 900  # 15분

    # school.bitzkorea.com ↔ adobe SSO (서명 토큰 브릿지)
    sso_shared_secret: str = ""  # school.bitzkorea.com 과 동일 값
    sso_admin_shared_secret: str = ""  # 관리자 SSO 전용 — 회원용(sso_shared_secret)과 반드시 다른 값
    sso_token_ttl_seconds: int = 120  # 서명 토큰 허용 시간
    school_site_url: str = "https://school.bitzkorea.com"  # SSO 실패 시 돌아갈 곳


@lru_cache
def get_settings() -> Settings:
    return Settings()
