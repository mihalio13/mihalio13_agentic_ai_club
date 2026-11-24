"""Простий rate limiter на фіксованих вікнах поверх кешу Django.

Кеш у продакшні зберігається в БД (спільний для всіх воркерів), тому ліміти
не обходяться тим, що запити потрапляють у різні процеси.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

P = ParamSpec("P")
View = Callable[..., HttpResponse]


def client_ip(request: HttpRequest) -> str:
    """IP клієнта з урахуванням рівно TRUSTED_PROXY_COUNT довірених проксі.

    Беремо адресу, яку дописав *наш* проксі (N-й елемент з кінця X-Forwarded-For),
    тому підставлений клієнтом заголовок не допоможе обійти ліміт.
    """
    proxies = settings.TRUSTED_PROXY_COUNT
    remote = str(request.META.get("REMOTE_ADDR", ""))
    if proxies <= 0:
        return remote
    forwarded = [p.strip() for p in str(request.META.get("HTTP_X_FORWARDED_FOR", "")).split(",")]
    forwarded = [p for p in forwarded if p]
    if len(forwarded) >= proxies:
        return forwarded[-proxies]
    return remote


def _cache_key(scope: str, identity: str, window: int) -> str:
    bucket = int(time.time() // window)
    digest = hashlib.sha256(f"{scope}:{identity}".encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}:{bucket}"


def hit(scope: str, identity: str, limit: int, window: int) -> bool:
    """Реєструє спробу. Повертає True, якщо ліміт ще не перевищено."""
    key = _cache_key(scope, identity, window)
    if cache.add(key, 1, timeout=window + 5):
        return True
    try:
        count = cache.incr(key)
    except ValueError:  # ключ щойно протух між add та incr
        cache.add(key, 1, timeout=window + 5)
        return True
    return count <= limit


def too_many_requests(request: HttpRequest) -> HttpResponse:
    response = render(request, "errors/429.html", status=429)
    response.headers["Retry-After"] = "60"
    return response


def rate_limit(
    scope: str,
    limit: int,
    window: int,
    key: Callable[[HttpRequest], str] | None = None,
    methods: tuple[str, ...] = ("POST",),
) -> Callable[[View], View]:
    """Декоратор: обмежує кількість запитів `limit` за `window` секунд.

    За замовчуванням ключем є користувач (якщо залогінений) або IP.
    """

    def default_key(request: HttpRequest) -> str:
        if request.user.is_authenticated:
            return f"user:{request.user.pk}"
        return f"ip:{client_ip(request)}"

    key_func = key or default_key

    def decorator(view: View) -> View:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
            if request.method in methods and not hit(scope, key_func(request), limit, window):
                return too_many_requests(request)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
