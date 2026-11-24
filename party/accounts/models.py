from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


def normalize_email_address(email: str) -> str:
    """Email зберігаємо в нижньому регістрі, щоб Ann@x.com і ann@x.com були одним акаунтом."""
    return email.strip().lower()


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError("Email обов'язковий")
        user = self.model(email=normalize_email_address(email), **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, username: str | None) -> User:
        return self.get(email=normalize_email_address(username or ""))


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("email", max_length=254, unique=True)
    display_name = models.CharField("ім'я", max_length=50)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["display_name"]

    class Meta:
        verbose_name = "користувач"
        verbose_name_plural = "користувачі"

    def __str__(self) -> str:
        return self.display_name

    def clean(self) -> None:
        super().clean()
        self.email = normalize_email_address(self.email)
        self.display_name = self.display_name.strip()
