from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import (
    BooleanField,
    Count,
    Exists,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Value,
)
from django.db.models.functions import Greatest
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User
from core.ratelimit import client_ip, rate_limit

from . import access, services
from .forms import CommentForm, EventForm, SearchForm
from .models import Attendance, Comment, Event, EventCover, RemovedParticipant, search_key

EVENTS_PER_PAGE = 12
COMMENTS_PER_PAGE = 30


def _current_user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover — гарантовано login_required
        raise Http404
    return user


def _with_seats(qs: QuerySet[Event], request: HttpRequest) -> QuerySet[Event]:
    """Додає до подій лічильники місць, ознаку «минула» і «я йду» — одним SQL-запитом."""
    taken = Count("attendances", distinct=True)
    if request.user.is_authenticated:
        attending: Exists | Value = Exists(
            Attendance.objects.filter(event=OuterRef("pk"), user_id=request.user.pk)
        )
    else:
        attending = Value(False)
    return qs.select_related("author").annotate(
        taken=taken,
        free=Greatest(
            ExpressionWrapper(F("capacity") - taken, output_field=IntegerField()), Value(0)
        ),
        is_past=ExpressionWrapper(Q(starts_at__lte=timezone.now()), output_field=BooleanField()),
        is_attending=ExpressionWrapper(attending, output_field=BooleanField()),
    )


def _ip_key(request: HttpRequest) -> str:
    return f"ip:{client_ip(request)}"


# ----------------------------------------------------------------------------- listing


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    form = SearchForm(request.GET or None)
    query = ""
    if form.is_valid():
        query = form.cleaned_data["q"]
    upcoming = Event.objects.filter(
        visibility=Event.Visibility.PUBLIC, starts_at__gt=timezone.now()
    )
    events = _with_seats(upcoming, request).order_by("starts_at", "pk")
    if query:
        events = events.filter(title_search__contains=search_key(query))
    page = Paginator(events, EVENTS_PER_PAGE).get_page(request.GET.get("page"))
    featured = None
    if not query and page.number == 1:
        featured = (
            # `free` — анотація з _with_seats; плагін mypy не бачить її через межу функції.
            _with_seats(upcoming, request)
            .filter(free__gt=0)  # type: ignore[misc]
            .order_by("starts_at", "pk")
            .first()
        )
    context = {
        "form": form,
        "query": query,
        "page": page,
        "featured": featured,
        "total_upcoming": upcoming.count(),
    }
    return render(request, "events/home.html", context)


def _upcoming_first(events: QuerySet[Event]) -> list[Event]:
    """Спершу майбутні (найближчі зверху), потім минулі (найсвіжіші зверху)."""

    def key(event: Event) -> tuple[bool, float, int]:
        past = bool(getattr(event, "is_past", False))
        ts = event.starts_at.timestamp()
        return (past, -ts if past else ts, event.pk)

    return sorted(events, key=key)


@login_required
@require_GET
def profile(request: HttpRequest) -> HttpResponse:
    user = _current_user(request)
    created = _upcoming_first(_with_seats(Event.objects.filter(author=user), request))
    attending = _upcoming_first(_with_seats(Event.objects.filter(attendances__user=user), request))
    context = {
        "created": created,
        "attending": attending,
        "upcoming_count": sum(1 for e in attending if not getattr(e, "is_past", False)),
    }
    return render(request, "events/profile.html", context)


# ----------------------------------------------------------------------------- detail


def _detail_context(request: HttpRequest, event: Event) -> dict[str, Any]:
    taken = Attendance.objects.filter(event=event).count()
    is_author = access.is_author(request, event)
    comments = (
        Comment.objects.filter(event=event).select_related("author").order_by("-created_at", "-pk")
    )
    is_removed = (
        request.user.is_authenticated
        and RemovedParticipant.objects.filter(event=event, user_id=request.user.pk).exists()
    )
    context: dict[str, Any] = {
        "event": event,
        "taken": taken,
        "free": max(event.capacity - taken, 0),
        "is_author": is_author,
        "is_attending": access.is_attending(request, event),
        "is_removed": is_removed,
        "has_started": event.has_started(),
        "is_ongoing": event.is_ongoing(),
        "comments_page": Paginator(comments, COMMENTS_PER_PAGE).get_page(
            request.GET.get("comments")
        ),
        "comment_form": CommentForm(),
    }
    if is_author:
        context["participants"] = (
            Attendance.objects.filter(event=event).select_related("user").order_by("created_at")
        )
        context["removed"] = (
            RemovedParticipant.objects.filter(event=event)
            .select_related("user")
            .order_by("-created_at")
        )
        context["invite_url"] = request.build_absolute_uri(
            reverse("events:invite", args=[event.invite_token])
        )
    return context


@require_GET
def detail(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_viewable_event_or_404(request, pk)
    return render(request, "events/detail.html", _detail_context(request, event))


@require_GET
@rate_limit("invite", limit=60, window=60, key=_ip_key, methods=("GET",))
def invite(request: HttpRequest, token: str) -> HttpResponse:
    if len(token) > 64:
        raise Http404
    event = Event.objects.filter(invite_token=token).first()
    if event is None:
        raise Http404
    access.remember_invite(request, event)
    # Редирект на «чисту» адресу: токен не лишається в адресному рядку та історії.
    return redirect(event)


@require_GET
def cover(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_viewable_event_or_404(request, pk)
    image = EventCover.objects.filter(event=event).first()
    if image is None:
        raise Http404
    response = HttpResponse(bytes(image.data), content_type=image.content_type)
    response.headers["Content-Disposition"] = "inline"
    # Ніколи не "public": інакше спільний кеш (CDN/проксі) міг би віддати обкладинку
    # події, яку автор потім зробив приватною.
    if event.is_private:
        response.headers["Cache-Control"] = "private, no-store"
    else:
        response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["ETag"] = f'"{image.sha256}"'
    return response


# ----------------------------------------------------------------------------- author


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("event-create", limit=20, window=60 * 60)
def create(request: HttpRequest) -> HttpResponse:
    form = EventForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.author = _current_user(request)
        try:
            services.save_event(event, cover=form.processed_cover)
        except services.EventActionError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, "Подію створено!")
            return redirect(event)
    return render(request, "events/form.html", {"form": form, "is_new": True})


@login_required
@require_http_methods(["GET", "POST"])
@rate_limit("event-edit", limit=60, window=60 * 60)
def edit(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_owned_event_or_404(request, pk)
    form = EventForm(request.POST or None, request.FILES or None, instance=event)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_event(
                form.instance,
                cover=form.processed_cover,
                remove_cover=bool(form.cleaned_data.get("remove_cover")),
            )
        except services.EventActionError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, "Зміни збережено.")
            return redirect(event)
    return render(request, "events/form.html", {"form": form, "is_new": False, "event": event})


@login_required
@require_http_methods(["GET", "POST"])
def delete(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_owned_event_or_404(request, pk)
    if request.method == "POST":
        title = event.title
        event.delete()
        messages.success(request, f"Подію «{title}» видалено.")
        return redirect("events:profile")
    taken = Attendance.objects.filter(event=event).count()
    return render(request, "events/confirm_delete.html", {"event": event, "taken": taken})


@login_required
@require_POST
def regenerate_invite(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_owned_event_or_404(request, pk)
    services.regenerate_invite(event.pk, _current_user(request))
    messages.success(request, "Створено нове посилання-запрошення. Старе більше не працює.")
    return redirect(event)


@login_required
@require_POST
def remove_participant(request: HttpRequest, pk: int, user_id: int) -> HttpResponse:
    event = access.get_owned_event_or_404(request, pk)
    services.remove_participant(event.pk, _current_user(request), user_id)
    messages.success(request, "Учасника прибрано. Записатися знову він не зможе.")
    return redirect(f"{event.get_absolute_url()}#participants")


@login_required
@require_POST
def restore_participant(request: HttpRequest, pk: int, user_id: int) -> HttpResponse:
    event = access.get_owned_event_or_404(request, pk)
    services.restore_participant(event.pk, _current_user(request), user_id)
    messages.success(request, "Користувач знову може записатися на подію.")
    return redirect(f"{event.get_absolute_url()}#participants")


# ----------------------------------------------------------------------------- attendee


@require_POST
@rate_limit("attendance", limit=30, window=60)
def join(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_viewable_event_or_404(request, pk)
    if not request.user.is_authenticated:
        return redirect_to_login(event.get_absolute_url())
    try:
        services.join_event(event.pk, _current_user(request))
    except services.EventActionError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "Ви записалися на подію!")
    return redirect(event)


@require_POST
@rate_limit("attendance", limit=30, window=60)
def leave(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_viewable_event_or_404(request, pk)
    if not request.user.is_authenticated:
        return redirect_to_login(event.get_absolute_url())
    try:
        services.leave_event(event.pk, _current_user(request))
    except services.EventActionError as exc:
        messages.error(request, exc.message)
    else:
        messages.info(request, "Участь скасовано.")
    return redirect(event)


@require_POST
@rate_limit("comment", limit=10, window=60)
def add_comment(request: HttpRequest, pk: int) -> HttpResponse:
    event = access.get_viewable_event_or_404(request, pk)
    if not request.user.is_authenticated:
        return redirect_to_login(event.get_absolute_url())
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.event = event
        comment.author = _current_user(request)
        comment.save()
        messages.success(request, "Коментар додано.")
    else:
        # Редирект (а не рендер з адресою /comments/), щоб «Оновити» чи «Назад»
        # не вели на адресу, яку не можна відкрити напряму.
        error = next(iter(form.errors.get("body", [])), "Коментар не збережено.")
        messages.error(request, str(error))
    return redirect(f"{event.get_absolute_url()}#comments")


@login_required
@require_POST
def delete_comment(request: HttpRequest, pk: int) -> HttpResponse:
    comment = get_object_or_404(Comment.objects.select_related("event"), pk=pk)
    event = comment.event
    if not access.can_view(request, event):
        raise Http404
    user = _current_user(request)
    if user.pk not in {comment.author_id, event.author_id}:
        raise Http404
    comment.delete()
    messages.info(request, "Коментар видалено.")
    return redirect(f"{event.get_absolute_url()}#comments")
