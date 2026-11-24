"""Невеликі фільтри для шаблонів інтерфейсу."""

from __future__ import annotations

from django import template

register = template.Library()

PALETTE_SIZE = 8


@register.filter
def hue(value: object) -> int:
    """Стабільний номер кольорової теми (0..7) для обкладинки чи аватара за id.

    Колір задається класом `hue-N`, а не inline-стилем — так CSP лишається суворою.
    """
    try:
        return abs(int(str(value))) % PALETTE_SIZE
    except (TypeError, ValueError):
        return 0


@register.filter
def initial(value: object) -> str:
    """Перша літера імені для аватара."""
    text = str(value or "").strip()
    return text[:1].upper() or "?"


@register.filter
def plural_uk(count: object, forms: str) -> str:
    """Українська множина: `{{ n|plural_uk:"учасник,учасники,учасників" }}`."""
    try:
        n = abs(int(str(count)))
    except (TypeError, ValueError):
        n = 0
    one, few, many = ([*forms.split(","), "", ""])[:3]
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
