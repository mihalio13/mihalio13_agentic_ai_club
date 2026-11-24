from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError


class MaximumLengthValidator:
    """Обмежує довжину пароля, щоб хешування гігантських рядків не було DoS-вектором."""

    def __init__(self, max_length: int = 128) -> None:
        self.max_length = max_length

    def validate(self, password: str, user: Any = None) -> None:
        if len(password) > self.max_length:
            raise ValidationError(
                f"Пароль задовгий (максимум {self.max_length} символів).",
                code="password_too_long",
            )

    def get_help_text(self) -> str:
        return f"Не більше {self.max_length} символів."
