from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
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


RESET_IP_LIMIT = (10, 60 * 60)  # 10 запитів на скидання / год з одного IP
RESET_EMAIL_LIMIT = (3, 60 * 60)  # 3 листи / год на одну адресу — щоб не спамити людину


@method_decorator(never_cache, name="dispatch")
class PasswordResetView(auth_views.PasswordResetView):
    """Запит на скидання пароля.

    Відповідь однакова незалежно від того, чи існує акаунт — перебором не можна
    дізнатися, хто зареєстрований.
    """

    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/emails/password_reset.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        email = normalize_email_address(str(request.POST.get("email", "")))[:254]
        ip_ok = hit("reset-ip", client_ip(request), *RESET_IP_LIMIT)
        email_ok = hit("reset-email", email, *RESET_EMAIL_LIMIT)
        if not (ip_ok and email_ok):
            return too_many_requests(request)
        # Django шукає акаунт без урахування регістру й лише серед активних
        # користувачів з придатним паролем (демо-акаунти листів не отримують).
        return super().post(request, *args, **kwargs)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


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
