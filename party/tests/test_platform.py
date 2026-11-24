"""Безпекові заголовки, обробка помилок, health check, rate limiter."""

from __future__ import annotations

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from hypothesis import given
from hypothesis import strategies as st

from core import ratelimit, views

pytestmark = pytest.mark.django_db


def test_security_headers(client: Client) -> None:
    response = client.get(reverse("events:home"))
    csp = response["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"
    assert "no-store" in response["Cache-Control"]
    assert "camera=()" in response["Permissions-Policy"]


def test_no_inline_scripts_or_styles(author_client: Client, author, make_event) -> None:
    event = make_event(author=author, visibility="private")
    for url in [reverse("events:home"), event.get_absolute_url(), reverse("events:create")]:
        html = author_client.get(url).content.decode()
        assert "<script>" not in html
        assert "style=" not in html
        assert "onclick=" not in html


def test_csrf_cookie_and_session_flags(client: Client) -> None:
    response = client.get(reverse("accounts:login"))
    assert response.cookies["csrftoken"]["samesite"] == "Lax"


def test_healthz(client: Client) -> None:
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_reports_db_failure(monkeypatch) -> None:
    def broken_cursor():
        raise RuntimeError("db down")

    monkeypatch.setattr("core.views.connection.cursor", broken_cursor)
    response = views.healthz(RequestFactory().get("/healthz"))
    assert response.status_code == 503


def test_404_page(client: Client) -> None:
    response = client.get("/no-such-page/")
    assert response.status_code == 404
    assert "Сторінку не знайдено" in response.content.decode()


def test_error_handlers_render() -> None:
    request = RequestFactory().get("/")
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    assert views.bad_request(request).status_code == 400
    assert views.permission_denied(request).status_code == 403
    assert views.server_error(request).status_code == 500
    assert views.csrf_failure(request).status_code == 403


def test_oversized_request_rejected(client: Client, settings) -> None:
    settings.MAX_REQUEST_BYTES = 1000
    response = client.post(reverse("accounts:login"), {"email": "a@b.c", "password": "x" * 5000})
    assert response.status_code == 413


def test_invalid_content_length_rejected(client: Client) -> None:
    response = client.generic("POST", reverse("accounts:login"), b"", CONTENT_LENGTH="abc")
    assert response.status_code == 413


def test_wrong_http_method(client: Client) -> None:
    assert client.post(reverse("events:home")).status_code == 405
    assert client.delete(reverse("events:home")).status_code == 405


class TestClientIp:
    def make(self, remote: str = "10.0.0.1", xff: str | None = None):
        request = RequestFactory().get("/", REMOTE_ADDR=remote)
        if xff is not None:
            request.META["HTTP_X_FORWARDED_FOR"] = xff
        return request

    def test_no_proxy_uses_remote_addr(self, settings) -> None:
        settings.TRUSTED_PROXY_COUNT = 0
        assert ratelimit.client_ip(self.make(xff="6.6.6.6")) == "10.0.0.1"

    def test_one_proxy_takes_rightmost(self, settings) -> None:
        settings.TRUSTED_PROXY_COUNT = 1
        assert ratelimit.client_ip(self.make(xff="6.6.6.6, 203.0.113.9")) == "203.0.113.9"

    def test_missing_header_falls_back(self, settings) -> None:
        settings.TRUSTED_PROXY_COUNT = 2
        assert ratelimit.client_ip(self.make(xff="1.1.1.1")) == "10.0.0.1"


@given(
    limit=st.integers(min_value=1, max_value=15),
    attempts=st.integers(min_value=0, max_value=30),
    identity=st.text(max_size=40),
)
def test_rate_limiter_allows_exactly_limit(limit: int, attempts: int, identity: str) -> None:
    """Property-based: за вікно пропускається рівно min(attempts, limit) запитів."""
    from django.core.cache import cache

    cache.clear()
    allowed = sum(ratelimit.hit("prop", identity, limit, 3600) for _ in range(attempts))
    assert allowed == min(attempts, limit)


def test_rate_limiter_recovers_if_key_expires(monkeypatch) -> None:
    from django.core.cache import cache

    cache.clear()
    monkeypatch.setattr(cache, "add", lambda *a, **k: False)

    def gone(*args, **kwargs):
        raise ValueError("expired")

    monkeypatch.setattr(cache, "incr", gone)
    assert ratelimit.hit("x", "y", 1, 60) is True


def test_production_settings_are_hardened(monkeypatch) -> None:
    """Перевіряємо прод-конфіг: без SECRET_KEY застосунок не стартує, а cookies — Secure."""
    import importlib

    from django.core.exceptions import ImproperlyConfigured

    import config.settings as prod

    monkeypatch.setenv("DJANGO_DEBUG", "0")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured):
        importlib.reload(prod)

    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "tusovka.onrender.com")
    importlib.reload(prod)
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS > 0
    assert "tusovka.onrender.com" in prod.ALLOWED_HOSTS
    assert prod.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")

    monkeypatch.setenv("DJANGO_DEBUG", "1")
    monkeypatch.delenv("DJANGO_SECRET_KEY")
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME")
    importlib.reload(prod)
    assert prod.DEBUG is True
    assert "localhost" in prod.ALLOWED_HOSTS
