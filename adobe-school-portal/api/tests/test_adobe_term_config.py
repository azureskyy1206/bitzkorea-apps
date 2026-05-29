"""계약 기간별 Adobe 자격 매핑."""

from app.adobe.term_config import get_adobe_term_config, is_adobe_configured_for_term
from app.config import get_settings


def test_cy26_uses_separate_client_credentials(monkeypatch):
    monkeypatch.setenv("ADOBE_ORG_ID", "org25@AdobeOrg")
    monkeypatch.setenv("ADOBE_CLIENT_ID", "client25")
    monkeypatch.setenv("ADOBE_CLIENT_SECRET", "secret25")
    monkeypatch.setenv("ADOBE_ORG_ID_CY26_H1", "org26@AdobeOrg")
    monkeypatch.setenv("ADOBE_CLIENT_ID_CY26_H1", "client26")
    monkeypatch.setenv("ADOBE_CLIENT_SECRET_CY26_H1", "secret26")
    monkeypatch.setenv("ADOBE_DEFAULT_PRODUCT_PROFILE_ID", "profile25")
    monkeypatch.setenv("ADOBE_DEFAULT_PRODUCT_PROFILE_ID_CY26_H1", "profile26")
    get_settings.cache_clear()

    cy25 = get_adobe_term_config("CY25-H2")
    cy26 = get_adobe_term_config("CY26-H1")

    assert cy25.org_id == "org25@AdobeOrg"
    assert cy25.client_id == "client25"
    assert cy25.client_secret == "secret25"
    assert cy25.default_product_profile_id == "profile25"

    assert cy26.org_id == "org26@AdobeOrg"
    assert cy26.client_id == "client26"
    assert cy26.client_secret == "secret26"
    assert cy26.default_product_profile_id == "profile26"
    assert cy26.client_id != cy25.client_id

    assert is_adobe_configured_for_term("CY25-H2")
    assert is_adobe_configured_for_term("CY26-H1")

    get_settings.cache_clear()
