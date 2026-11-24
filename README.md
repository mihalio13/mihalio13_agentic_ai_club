# mihalio13 · AI Agentic Club

## «Тусовка» — сервіс подій → [`party/`](party/)

Сервіс подій з обмеженою кількістю місць (спрощений Meetup): акаунти, публічні та приватні (за запрошенням) події, запис «Іду» / «Скасувати», коментарі, профіль.

**Запуск, змінні середовища, тести й деплой:** [party/README.md](party/README.md).

```bash
cd party
uv sync
cp .env.example .env
uv run --env-file .env python manage.py migrate
uv run --env-file .env python manage.py runserver
```

Тести однією командою: `cd party && uv run pytest`.
