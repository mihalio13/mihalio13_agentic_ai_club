"""Службові в'юхи: health check і сторінки помилок."""

from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache


@never_cache
def healthz(request: HttpRequest) -> HttpResponse:
    """Перевірка для балансувальника: застосунок живий і БД відповідає."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001 — будь-яка помилка БД означає «нездоровий»
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


def bad_request(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return render(request, "errors/400.html", status=400)


def permission_denied(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return render(request, "errors/403.html", status=403)


def page_not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return render(request, "errors/404.html", status=404)


def server_error(request: HttpRequest) -> HttpResponse:
    # Без контекстних процесорів: якщо впала БД, шаблон усе одно має відрендеритись.
    return HttpResponse(render_to_string("errors/500.html"), status=500)


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    return render(request, "errors/403_csrf.html", status=403)
