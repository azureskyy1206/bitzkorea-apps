"""계약 기간(contract_term)별 Adobe IMS / UMAPI 자격."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.license_terms import DEFAULT_CONTRACT_TERM, is_valid_term


@dataclass(frozen=True)
class AdobeTermConfig:
    contract_term: str
    org_id: str
    client_id: str
    client_secret: str
    default_product_profile_id: str
    ims_host: str
    umapi_host: str
    user_country: str

    def is_configured(self) -> bool:
        return bool(self.org_id and self.client_id and self.client_secret)

    def ims_redis_key(self) -> str:
        return f"adobe:ims:access_token:{self.contract_term}"


def _strip(value: str | None) -> str:
    return (value or "").strip()


def _term_fields(settings: Settings, term: str) -> tuple[str, str, str, str]:
    """(org_id, client_id, client_secret, default_product_profile_id) for term."""
    if term == "CY26-H1":
        return (
            _strip(settings.adobe_org_id_cy26_h1) or _strip(settings.adobe_org_id),
            _strip(settings.adobe_client_id_cy26_h1),
            _strip(settings.adobe_client_secret_cy26_h1),
            _strip(settings.adobe_default_product_profile_id_cy26_h1)
            or _strip(settings.adobe_default_product_profile_id),
        )
    # CY25-H2 및 기본
    return (
        _strip(settings.adobe_org_id),
        _strip(settings.adobe_client_id),
        _strip(settings.adobe_client_secret),
        _strip(settings.adobe_default_product_profile_id),
    )


def get_adobe_term_config(contract_term: str) -> AdobeTermConfig:
    term = contract_term.strip() if contract_term else DEFAULT_CONTRACT_TERM
    if not is_valid_term(term):
        term = DEFAULT_CONTRACT_TERM
    settings = get_settings()
    org_id, client_id, client_secret, default_profile = _term_fields(settings, term)
    return AdobeTermConfig(
        contract_term=term,
        org_id=org_id,
        client_id=client_id,
        client_secret=client_secret,
        default_product_profile_id=default_profile,
        ims_host=_strip(settings.adobe_ims_host) or "https://ims-na1.adobelogin.com",
        umapi_host=_strip(settings.adobe_umapi_host) or "https://usermanagement.adobe.io",
        user_country=_strip(settings.adobe_user_country) or "KR",
    )


def is_adobe_configured_for_term(contract_term: str) -> bool:
    return get_adobe_term_config(contract_term).is_configured()


def adobe_configured_terms() -> dict[str, bool]:
    from app.license_terms import TERM_META

    return {code: is_adobe_configured_for_term(code) for code in TERM_META}
