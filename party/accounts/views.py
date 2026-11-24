from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from core.ratelimit import client_ip, hit, rate_limit, too_many_requests

from .forms import LoginForm, PasswordChangeForm, RegisterForm
from .models import User, normalize_email_address

LOGIN_IP_LIMIT = (30, 10 * 60)  # 30 спроб / 10 хв з одного IP
LOGIN_EMAIL_LIMIT = (8, 15 * 60)  # 8 спроб / 15 хв на один email


def _safe_next(request: HttpRequest) -> str:
    """Повертає URL з ?next= лише якщо він веде на наш же сайт (захист від open redirect)."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return reverse("events:home")


def _ip_key(request: HttpRequest) -> str:
    return f"ip:{client_ip(request)}"


@sensitive_post_parameters("password1", "password2")
@csrf_protect
@never_cache
@require_http_methods(["GET", "POST"])
@rate_limit("register", limit=10, window=60 * 60, key=_ip_key)
def register(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("events:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Вітаємо, {user.display_name}! Акаунт створено.")
        return HttpResponseRedirect(_safe_next(request))
    return render(request, "accounts/register.html", {"form": form, "next": _safe_next(request)})


@sensitive_post_parameters("password")
@csrf_protect
@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("events:home")
    form = LoginForm(request, request.POST or None)
    if request.method == "POST":
        email = normalize_email_address(str(request.POST.get("email", "")))[:254]
        ip_ok = hit("login-ip", client_ip(request), *LOGIN_IP_LIMIT)
        email_ok = hit("login-email", email, *LOGIN_EMAIL_LIMIT)
        if not (ip_ok and email_ok):
            return too_many_requests(request)
        if form.is_valid() and form.user is not None:
            login(request, form.user)
            messages.success(request, f"З поверненням, {form.user.display_name}!")
            return HttpResponseRedirect(_safe_next(request))
    return render(request, "accounts/login.html", {"form": form, "next": _safe_next(request)})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.info(request, "Ви вийшли з акаунта.")
    return redirect("events:home")


@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@rate_limit("password-change", limit=10, window=15 * 60)
def password_change(request: HttpRequest) -> HttpResponse:
    if not isinstance(request.user, User):  # pragma: no cover — гарантовано login_required
        raise PermissionDenied
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Пароль змінено.")
        return redirect("events:profile")
    return render(request, "accounts/password_change.html", {"form": form})
