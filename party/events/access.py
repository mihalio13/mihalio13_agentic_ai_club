"""Єдине місце, де вирішується, хто що може бачити й робити з подією.

Будь-яка в'юха, що працює з подією, бере її через ці функції — тож перевірку
доступу неможливо «забути» в окремому ендпоінті (обкладинка, коментарі, запис…).
Якщо доступу немає, відповідаємо 404, а не 403: так не можна навіть дізнатись,
що приватна подія з таким id існує.
"""

from __future__ import annotations

from django.http import Http404, HttpRequest
from django.utils.crypto import constant_time_compare

from .models import Attendance, Event

INVITES_SESSION_KEY = "event_invites"
MAX_INVITES_IN_SESSION = 100


def remember_invite(request: HttpRequest, event: Event) -> None:
    invites = dict(request.session.get(INVITES_SESSION_KEY, {}))
    invites.pop(str(event.pk), None)
    invites[str(event.pk)] = event.invite_token
    while len(invites) > MAX_INVITES_IN_SESSION:
        invites.pop(next(iter(invites)))
    request.session[INVITES_SESSION_KEY] = invites


def has_valid_invite(request: HttpRequest, event: Event) -> bool:
    token = request.session.get(INVITES_SESSION_KEY, {}).get(str(event.pk))
    return isinstance(token, str) and constant_time_compare(token, event.invite_token)


def is_author(request: HttpRequest, event: Event) -> bool:
    return request.user.is_authenticated and event.author_id == request.user.pk


def is_attending(request: HttpRequest, event: Event) -> bool:
    if not request.user.is_authenticated:
        return False
    return Attendance.objects.filter(event=event, user_id=request.user.pk).exists()


def can_view(request: HttpRequest, event: Event) -> bool:
    if not event.is_private:
        return True
    return (
        is_author(request, event)
        or has_valid_invite(request, event)
        or is_attending(request, event)
    )


def get_viewable_event_or_404(request: HttpRequest, pk: int) -> Event:
    event = Event.objects.select_related("author").filter(pk=pk).first()
    if event is None or not can_view(request, event):
        raise Http404
    return event


def get_owned_event_or_404(request: HttpRequest, pk: int) -> Event:
    if not request.user.is_authenticated:
        raise Http404
    event = Event.objects.filter(pk=pk, author_id=request.user.pk).first()
    if event is None:
        raise Http404
    return event
