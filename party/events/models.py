from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

MIN_CAPACITY = 1
MAX_CAPACITY = 10_000
ONGOING_WINDOW = timedelta(hours=12)


def new_invite_token() -> str:
    """256 біт випадковості — перебрати посилання-запрошення неможливо."""
    return secrets.token_urlsafe(32)


def search_key(text: str) -> str:
    """Нормалізований для пошуку текст: регістр не важливий навіть для кирилиці на SQLite."""
    return " ".join(text.casefold().split())


class Event(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Публічна"
        PRIVATE = "private", "Приватна"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events"
    )
    title = models.CharField("назва", max_length=120)
    title_search = models.CharField(max_length=120, editable=False, db_index=True)
    description = models.TextField("опис", max_length=5000, blank=True)
    starts_at = models.DateTimeField("дата й час", db_index=True)
    capacity = models.PositiveIntegerField(
        "кількість місць",
        validators=[MinValueValidator(MIN_CAPACITY), MaxValueValidator(MAX_CAPACITY)],
    )
    visibility = models.CharField(
        "тип", max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    invite_token = models.CharField(
        max_length=64, unique=True, default=new_invite_token, editable=False
    )
    has_cover = models.BooleanField(default=False, editable=False)
    cover_version = models.CharField(max_length=16, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("starts_at", "pk")
        verbose_name = "подія"
        verbose_name_plural = "події"
        indexes = [models.Index(fields=["visibility", "starts_at"], name="event_listing_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__gte=MIN_CAPACITY) & Q(capacity__lte=MAX_CAPACITY),
                name="event_capacity_range",
            ),
            models.CheckConstraint(
                condition=Q(visibility__in=["public", "private"]),
                name="event_visibility_valid",
            ),
            models.CheckConstraint(condition=~Q(title=""), name="event_title_not_empty"),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args: object, **kwargs: object) -> None:
        self.title_search = search_key(self.title)
        update_fields = kwargs.get("update_fields")
        if isinstance(update_fields, list | tuple | set) and "title" in update_fields:
            kwargs["update_fields"] = {*update_fields, "title_search"}
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def get_absolute_url(self) -> str:
        return reverse("events:detail", args=[self.pk])

    @property
    def is_private(self) -> bool:
        return self.visibility == self.Visibility.PRIVATE

    def has_started(self, now: datetime | None = None) -> bool:
        return self.starts_at <= (now or timezone.now())

    def is_ongoing(self, now: datetime | None = None) -> bool:
        """Почалася нещодавно (часу завершення немає, тому вважаємо «триває» 12 год)."""
        now = now or timezone.now()
        return self.starts_at <= now < self.starts_at + ONGOING_WINDOW

    def rotate_invite_token(self) -> None:
        self.invite_token = new_invite_token()


class EventCover(models.Model):
    """Обкладинка зберігається в БД: не губиться на хостингах з ефемерним диском."""

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, primary_key=True, related_name="cover"
    )
    data = models.BinaryField()
    content_type = models.CharField(max_length=32, default="image/webp")
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "обкладинка"
        verbose_name_plural = "обкладинки"

    def __str__(self) -> str:
        return f"Обкладинка {self.event_id} ({self.width}x{self.height})"


class Attendance(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attendances")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendances"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = "участь"
        verbose_name_plural = "участь"
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="attendance_unique_per_user")
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.event}"


class RemovedParticipant(models.Model):
    """Учасник, якого організатор прибрав: повторно записатися він не може."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="removed")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="removed_from"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "прибраний учасник"
        verbose_name_plural = "прибрані учасники"
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="removed_unique_per_user")
        ]

    def __str__(self) -> str:
        return f"{self.user} ✕ {self.event}"


class Comment(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    body = models.TextField("коментар", max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = "коментар"
        verbose_name_plural = "коментарі"
        indexes = [models.Index(fields=["event", "created_at"], name="comment_event_idx")]
        constraints = [models.CheckConstraint(condition=~Q(body=""), name="comment_not_empty")]

    def __str__(self) -> str:
        return f"{self.author}: {self.body[:40]}"
