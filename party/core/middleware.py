"""Захисні middleware: ліміт розміру запиту та безпекові HTTP-заголовки."""

from __future__ import annotations

import re
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string

EVENT_PATH_RE = re.compile(r"^/events/(\d+)/")


class MethodNotAllowedPageMiddleware:
    """Замість порожньої відповіді 405 показує зрозумілу сторінку.

    Буває, коли адресу дії (напр. `/events/3/join/`) відкрили напряму, через
    історію браузера чи кнопку «Назад». Даємо шлях назад до події, а не білий екран.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if response.status_code != 405 or response.content:
            return response
        match = EVENT_PATH_RE.match(request.path)
        back_url = f"/events/{match.group(1)}/" if match else "/"
        page = render(request, "errors/405.html", {"back_url": back_url}, status=405)
        if "Allow" in response.headers:
            page.headers["Allow"] = response.headers["Allow"]
        return page


CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        # blob: — лише для локального прев'ю обкладинки перед завантаженням.
        "img-src 'self' data: blob:",
        "style-src 'self'",
        "script-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class MaxRequestSizeMiddleware:
    """Відхиляє завеликі запити до того, як Django почне їх читати (захист від DoS)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_length = request.META.get("CONTENT_LENGTH") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            length = -1
        if length < 0 or length > settings.MAX_REQUEST_BYTES:
            body = render_to_string("errors/413.html", request=None)
            return HttpResponse(body, status=413)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """CSP, Permissions-Policy і заборона кешування сторінок з персональними даними."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/html") and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "private, no-cache, no-store"
        return response
