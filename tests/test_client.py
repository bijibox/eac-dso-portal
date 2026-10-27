"""Login, JWT refresh, and HTTP error handling."""

from __future__ import annotations

import pytest

from eac_dso_portal import (
    EacApiError,
    EacAuthError,
    EacClient,
    EacRateLimitError,
)

from .conftest import BASE_URL, URL_LOGIN, URL_USER_DETAILS

# ---------- login ----------


async def test_login_success(session, mock_http) -> None:
    mock_http.post(URL_LOGIN, payload={"jwt": "abc.def.ghi"})
    client = EacClient("user@example.com", "pw", session=session, base_url=BASE_URL)
    await client.login()
    assert client.jwt == "abc.def.ghi"


async def test_login_uses_email_field_not_username(session, mock_http) -> None:
    """The portal expects {email, password}; {username, password} returns 403."""
    captured: dict[str, object] = {}

    def handler(url, **kwargs):
        captured["json"] = kwargs.get("json")
        from aioresponses.core import CallbackResult

        return CallbackResult(status=200, payload={"jwt": "x"})

    mock_http.post(URL_LOGIN, callback=handler)
    client = EacClient("user@example.com", "pw", session=session, base_url=BASE_URL)
    await client.login()
    assert captured["json"] == {"email": "user@example.com", "password": "pw"}


async def test_login_invalid_credentials_raises_auth_error(session, mock_http) -> None:
    mock_http.post(URL_LOGIN, status=403, payload={"error": "Forbidden"})
    client = EacClient("user@example.com", "wrong", session=session, base_url=BASE_URL)
    with pytest.raises(EacAuthError):
        await client.login()


async def test_login_401_raises_auth_error(session, mock_http) -> None:
    mock_http.post(URL_LOGIN, status=401, payload={"error": "Unauthorized"})
    client = EacClient("user@example.com", "pw", session=session, base_url=BASE_URL)
    with pytest.raises(EacAuthError):
        await client.login()


async def test_login_unexpected_status_raises_api_error(session, mock_http) -> None:
    mock_http.post(URL_LOGIN, status=500, body="boom")
    client = EacClient("user@example.com", "pw", session=session, base_url=BASE_URL)
    with pytest.raises(EacApiError) as exc_info:
        await client.login()
    assert exc_info.value.status == 500


async def test_login_missing_jwt_raises_auth_error(session, mock_http) -> None:
    mock_http.post(URL_LOGIN, payload={"not-jwt": "x"})
    client = EacClient("user@example.com", "pw", session=session, base_url=BASE_URL)
    with pytest.raises(EacAuthError):
        await client.login()


# ---------- automatic JWT refresh ----------


async def test_request_refreshes_jwt_on_401(session, mock_http) -> None:
    """A 401 on a normal endpoint triggers a re-login and one retry."""
    # initial login
    mock_http.post(URL_LOGIN, payload={"jwt": "old"})
    # first attempt fails with 401
    mock_http.get(URL_USER_DETAILS, status=401, payload={"error": "Unauthorized"})
    # re-login on the retry path
    mock_http.post(URL_LOGIN, payload={"jwt": "new"})
    # second attempt succeeds
    mock_http.get(
        URL_USER_DETAILS,
        payload={"name": "Test", "admin": False, "ids": [], "phones": []},
    )

    client = EacClient("u@e.com", "pw", session=session, base_url=BASE_URL)
    await client.login()
    assert client.jwt == "old"

    user = await client.get_user_details()
    assert user.name == "Test"
    assert client.jwt == "new"


async def test_request_does_not_loop_on_repeated_401(session, mock_http) -> None:
    """If the second 401 happens after a refresh, surface as EacAuthError, not infinite retry."""
    mock_http.post(URL_LOGIN, payload={"jwt": "first"})
    mock_http.get(URL_USER_DETAILS, status=401, payload={"e": "1"})
    mock_http.post(URL_LOGIN, payload={"jwt": "second"})
    mock_http.get(URL_USER_DETAILS, status=401, payload={"e": "2"})

    client = EacClient("u@e.com", "pw", session=session, base_url=BASE_URL)
    await client.login()
    with pytest.raises(EacApiError) as exc_info:
        await client.get_user_details()
    assert exc_info.value.status == 401


# ---------- error mapping for non-auth statuses ----------


async def test_429_raises_rate_limit_error(session, mock_http, logged_in_client) -> None:
    mock_http.get(URL_USER_DETAILS, status=429, body="slow down")
    with pytest.raises(EacRateLimitError) as exc_info:
        await logged_in_client.get_user_details()
    assert exc_info.value.status == 429


async def test_500_raises_api_error(session, mock_http, logged_in_client) -> None:
    mock_http.get(URL_USER_DETAILS, status=500, body="boom")
    with pytest.raises(EacApiError) as exc_info:
        await logged_in_client.get_user_details()
    assert exc_info.value.status == 500


async def test_unexpected_2xx_raises_api_error(session, mock_http, logged_in_client) -> None:
    """The portal only ever returns 200 for success. A 204 means the contract
    is broken and the next ``await resp.json()`` would fail with a confusing
    message, so surface it as EacApiError instead."""
    mock_http.get(URL_USER_DETAILS, status=204, body="")
    with pytest.raises(EacApiError) as exc_info:
        await logged_in_client.get_user_details()
    assert exc_info.value.status == 204


async def test_lazy_login_on_first_request(session, mock_http) -> None:
    """A request with no prior login() call should login automatically."""
    mock_http.post(URL_LOGIN, payload={"jwt": "auto"})
    mock_http.get(
        URL_USER_DETAILS,
        payload={"name": "Auto", "admin": False, "ids": [], "phones": []},
    )

    client = EacClient("u@e.com", "pw", session=session, base_url=BASE_URL)
    user = await client.get_user_details()
    assert client.jwt == "auto"
    assert user.name == "Auto"
