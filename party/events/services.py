"""Бізнес-операції з подіями, що мають бути атомарними.

Бронювання місця — класичне місце для race condition: два запити одночасно
бачать «залишилось 1 місце» і обидва записуються. Тут кожна операція блокує
рядок події (`SELECT ... FOR UPDATE` на PostgreSQL, `BEGIN IMMEDIATE` на SQLite),
тому перевірка «є вільне місце» і запис відбуваються як одне ціле.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from accounts.models import User

from .images import ProcessedImage
from .models import Attendance, Event, EventCover


class EventActionError(Exception):
    """Помилка бізнес-правила; текст показується користувачу."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _lock_event(event_id: int) -> Event:
    try:
        return Event.objects.select_for_update().get(pk=event_id)
    except Event.DoesNotExist as exc:
        raise EventActionError("Подію не знайдено або її видалено.") from exc


def join_event(event_id: int, user: User) -> None:
    with transaction.atomic():
        event = _lock_event(event_id)
        if event.author_id == user.pk:
            raise EventActionError("Ви організатор цієї події — місце для вас уже є.")
        if event.has_started():
            raise EventActionError("Подія вже почалася, записатися не можна.")
        if Attendance.objects.filter(event=event, user=user).exists():
            return  # повторне натискання «Іду» — не помилка
        if Attendance.objects.filter(event=event).count() >= event.capacity:
            raise EventActionError("На жаль, вільних місць уже немає.")
        try:
            with transaction.atomic():
                Attendance.objects.create(event=event, user=user)
        except IntegrityError:
            return  # паралельний дубль від того ж користувача — він уже записаний


def leave_event(event_id: int, user: User) -> None:
    with transaction.atomic():
        event = _lock_event(event_id)
        if event.has_started():
            raise EventActionError("Подія вже почалася, скасувати участь не можна.")
        Attendance.objects.filter(event=event, user=user).delete()


def remove_participant(event_id: int, author: User, user_id: int) -> None:
    with transaction.atomic():
        event = _lock_event(event_id)
        if event.author_id != author.pk:
            raise EventActionError("Лише автор може керувати учасниками.")
        Attendance.objects.filter(event=event, user_id=user_id).delete()


def save_event(
    event: Event,
    *,
    cover: ProcessedImage | None = None,
    remove_cover: bool = False,
) -> Event:
    """Створює або оновлює подію.

    Для існуючої події під блокуванням перевіряємо, що нова кількість місць
    не менша за кількість уже записаних (інакше лічильник піде в мінус).
    """
    with transaction.atomic():
        if event.pk is not None:
            locked = _lock_event(event.pk)
            taken = Attendance.objects.filter(event=locked).count()
            if event.capacity < taken:
                raise EventActionError(
                    f"Уже записалося {taken} учасників — місць не може бути менше."
                )
        event.full_clean()
        if cover is not None:
            event.has_cover = True
            event.cover_version = cover.sha256[:16]
        elif remove_cover:
            event.has_cover = False
            event.cover_version = ""
        event.save()
        if cover is not None:
            EventCover.objects.update_or_create(
                event=event,
                defaults={
                    "data": cover.data,
                    "content_type": cover.content_type,
                    "width": cover.width,
                    "height": cover.height,
                    "sha256": cover.sha256,
                },
            )
        elif remove_cover:
            EventCover.objects.filter(event=event).delete()
    return event


def regenerate_invite(event_id: int, author: User) -> Event:
    with transaction.atomic():
        event = _lock_event(event_id)
        if event.author_id != author.pk:
            raise EventActionError("Лише автор може змінити посилання-запрошення.")
        event.rotate_invite_token()
        event.save(update_fields=["invite_token", "updated_at"])
        return event
