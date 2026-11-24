"""Демо-дані для локальної розробки: `uv run python manage.py seed_demo`.

Демо-користувачі мають *непридатний* пароль (увійти під ними неможливо) і email
на зарезервованому домені `.invalid`. У продакшні (DEBUG=0) команда відмовиться
працювати без явного `--force`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from events.models import Attendance, Comment, Event

DEMO_DOMAIN = "demo.tusovka.invalid"

USERS = ["Олена", "Тарас", "Марта", "Андрій", "Ірина", "Богдан"]

# (назва, опис, через скільки днів, година, місць, скільки записано, приватна)
EVENTS: list[tuple[str, str, int, int, int, int, bool]] = [
    (
        "Настолки в «Кубику»: Каркассон і Кодові імена",
        "Граємо в легкі ігри для компанії. Новачкам пояснимо правила, ігри беремо з собою.\n"
        "Чай і печиво — за рахунок закладу.",
        2,
        19,
        12,
        9,
        False,
    ),
    (
        "Ранкова пробіжка Набережною — 5 км",
        "Спокійний темп 6:30/км, без змагань. Збираємось біля Поштової площі, після — кава.",
        3,
        8,
        20,
        7,
        False,
    ),
    (
        "Лекція: як працює ШІ-агент зсередини",
        "Розбираємо архітектуру агентів, інструменти та типові помилки. Буде час на питання.",
        5,
        18,
        40,
        38,
        False,
    ),
    (
        "Кіновечір: «Тіні забутих предків»",
        "Дивимось класику на проєкторі, потім обговорюємо. Попкорн є, пледи беріть свої.",
        6,
        20,
        15,
        15,
        False,
    ),
    (
        "Хакатон вихідного дня",
        "48 годин, команди по 3–4 людини. Тема оголошується на старті.",
        12,
        10,
        60,
        21,
        False,
    ),
    (
        "День народження Марти",
        "Тільки для своїх. Дрес-код — щось жовте 🙂",
        9,
        19,
        25,
        6,
        True,
    ),
    (
        "Мовний клуб English Speaking",
        "Розмовна практика в невимушеній атмосфері. Рівень від B1.",
        -3,
        18,
        10,
        8,
        False,
    ),
]

COMMENTS = [
    "Я буду! Можна прийти з другом?",
    "А що брати з собою?",
    "Супер ідея, давно такого чекав(ла).",
    "Чи буде запис для тих, хто не встигне?",
]


class Command(BaseCommand):
    help = "Створює демо-користувачів і події для локальної розробки."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--reset", action="store_true", help="Спершу видалити старі демо-дані")
        parser.add_argument("--force", action="store_true", help="Дозволити при DEBUG=0")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Відмовлено: DEBUG вимкнено. Додайте --force, якщо ви впевнені.")

        demo_users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        if options["reset"]:
            deleted, _ = demo_users.delete()
            self.stdout.write(f"Видалено старих демо-об'єктів: {deleted}")
        elif demo_users.exists():
            self.stdout.write("Демо-дані вже є. Використайте --reset, щоб створити заново.")
            return

        users = []
        for i, name in enumerate(USERS):
            user = User(email=f"user{i}@{DEMO_DOMAIN}", display_name=name)
            user.set_unusable_password()
            user.save()
            users.append(user)

        today = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        for idx, (title, description, days, hour, capacity, taken, private) in enumerate(EVENTS):
            author = users[idx % len(users)]
            event = Event.objects.create(
                author=author,
                title=title,
                description=description,
                starts_at=(today + timedelta(days=days)).replace(hour=hour),
                capacity=capacity,
                visibility=Event.Visibility.PRIVATE if private else Event.Visibility.PUBLIC,
            )
            attendees = [u for u in users if u != author][: min(taken, len(users) - 1)]
            Attendance.objects.bulk_create(Attendance(event=event, user=u) for u in attendees)
            # Решта «учасників» — додаткові демо-акаунти, щоб лічильники були реалістичні.
            for extra in range(taken - len(attendees)):
                filler = User(
                    email=f"guest{idx}-{extra}@{DEMO_DOMAIN}", display_name=f"Гість {extra + 1}"
                )
                filler.set_unusable_password()
                filler.save()
                Attendance.objects.create(event=event, user=filler)
            for c, body in enumerate(COMMENTS[: (idx % 3) + 1]):
                Comment.objects.create(
                    event=event, author=users[(idx + c + 1) % len(users)], body=body
                )

        self.stdout.write(self.style.SUCCESS(f"Створено {len(EVENTS)} демо-подій."))
