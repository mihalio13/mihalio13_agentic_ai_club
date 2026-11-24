from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm
from django.http import HttpRequest

from .models import User, normalize_email_address

INVALID_LOGIN = "Невірний email або пароль."


class RegisterForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    display_name = forms.CharField(
        label="Ім'я, яке бачитимуть інші",
        min_length=2,
        max_length=50,
        widget=forms.TextInput(attrs={"autocomplete": "nickname"}),
    )
    password1 = forms.CharField(
        label="Пароль",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Щонайменше 10 символів, не лише цифри і не надто простий.",
    )
    password2 = forms.CharField(
        label="Повторіть пароль",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self) -> str:
        email = normalize_email_address(self.cleaned_data["email"])
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Акаунт із цим email уже існує. Спробуйте увійти.")
        return email

    def clean_display_name(self) -> str:
        name = " ".join(self.cleaned_data["display_name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Ім'я має містити щонайменше 2 символи.")
        return name

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Паролі не збігаються.")
        elif p1:
            candidate = User(
                email=cleaned.get("email", ""), display_name=cleaned.get("display_name", "")
            )
            try:
                password_validation.validate_password(p1, candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self) -> User:
        return User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            display_name=self.cleaned_data["display_name"],
        )


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Пароль",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        self.request = request
        self.user: User | None = None
        super().__init__(*args, **kwargs)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        email, password = cleaned.get("email"), cleaned.get("password")
        if email and password:
            user = authenticate(
                self.request, username=normalize_email_address(email), password=password
            )
            # Однакове повідомлення для «немає такого email» і «невірний пароль»,
            # щоб не можна було перебором дізнатись, хто зареєстрований.
            if user is None or not isinstance(user, User):
                raise forms.ValidationError(INVALID_LOGIN, code="invalid_login")
            self.user = user
        return cleaned


class PasswordChangeForm(DjangoPasswordChangeForm):
    pass
