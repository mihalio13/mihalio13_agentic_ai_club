from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django import forms
from django.utils import timezone

from .images import InvalidImageError, ProcessedImage, process_cover
from .models import MAX_CAPACITY, MIN_CAPACITY, Attendance, Comment, Event

DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
MAX_YEARS_AHEAD = 5


class EventForm(forms.ModelForm[Event]):
    starts_at = forms.DateTimeField(
        label="Дата й час (за Києвом)",
        input_formats=[DATETIME_LOCAL_FORMAT, "%Y-%m-%d %H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_LOCAL_FORMAT),
    )
    capacity = forms.IntegerField(
        label="Кількість місць",
        min_value=MIN_CAPACITY,
        max_value=MAX_CAPACITY,
        widget=forms.NumberInput(attrs={"min": MIN_CAPACITY, "max": MAX_CAPACITY}),
    )
    cover = forms.FileField(
        label="Обкладинка",
        required=False,
        help_text="JPEG, PNG або WebP, до 5 МБ.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    remove_cover = forms.BooleanField(label="Прибрати поточну обкладинку", required=False)

    class Meta:
        model = Event
        # Явний перелік полів: author, invite_token тощо неможливо підмінити з форми.
        fields = ("title", "description", "starts_at", "capacity", "visibility")
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 120, "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 6, "maxlength": 5000}),
            "visibility": forms.RadioSelect,
        }
        help_texts = {
            "visibility": "Приватну подію бачать лише ті, хто має посилання-запрошення.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.processed_cover: ProcessedImage | None = None
        if not self.instance.pk or not self.instance.has_cover:
            del self.fields["remove_cover"]

    def clean_title(self) -> str:
        title = " ".join(str(self.cleaned_data["title"]).split())
        if not title:
            raise forms.ValidationError("Вкажіть назву події.")
        return title

    def clean_description(self) -> str:
        return str(self.cleaned_data.get("description") or "").strip()

    def clean_starts_at(self) -> datetime:
        starts_at: datetime = self.cleaned_data["starts_at"]
        is_new = self.instance.pk is None
        if is_new or "starts_at" in self.changed_data:
            now = timezone.now()
            if starts_at <= now:
                raise forms.ValidationError("Дата й час мають бути в майбутньому.")
            if starts_at > now + timedelta(days=365 * MAX_YEARS_AHEAD):
                raise forms.ValidationError(
                    f"Подію можна запланувати не більше ніж на {MAX_YEARS_AHEAD} років уперед."
                )
        return starts_at

    def clean_capacity(self) -> int:
        capacity = int(self.cleaned_data["capacity"])
        if self.instance.pk is not None:
            taken = Attendance.objects.filter(event=self.instance).count()
            if capacity < taken:
                raise forms.ValidationError(
                    f"Уже записалося {taken} учасників — місць не може бути менше."
                )
        return capacity

    def clean_cover(self) -> Any:
        upload = self.cleaned_data.get("cover")
        if upload:
            try:
                self.processed_cover = process_cover(upload)
            except InvalidImageError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return upload


class CommentForm(forms.ModelForm[Comment]):
    class Meta:
        model = Comment
        fields = ("body",)
        labels = {"body": "Ваш коментар"}
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 3, "maxlength": 2000, "placeholder": "Напишіть щось…"}
            ),
        }

    def clean_body(self) -> str:
        body = str(self.cleaned_data["body"]).strip()
        if not body:
            raise forms.ValidationError("Коментар не може бути порожнім.")
        return body


class SearchForm(forms.Form):
    q = forms.CharField(label="Пошук", required=False, max_length=100, strip=True)
