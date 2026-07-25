from django import forms
from django.forms import BaseModelFormSet, modelformset_factory
from django.utils import timezone

from .models import EbookDocument, EbookLesson, EbookPageMappingAnchor


class TocReviewSettingsForm(forms.ModelForm):
    class Meta:
        model = EbookDocument
        fields = (
            "toc_mode",
            "toc_start_page",
            "toc_end_page",
            "page_mapping_mode",
            "page_number_offset",
        )


class EbookLessonReviewForm(forms.ModelForm):
    selected = forms.BooleanField(required=False)

    class Meta:
        model = EbookLesson
        fields = (
            "order",
            "title",
            "printed_page_number",
            "start_page",
            "end_page",
            "source_toc_page",
            "confidence",
            "parser_strategy",
            "warnings",
            "is_verified",
            "is_manually_edited",
        )
        widgets = {
            "title": forms.TextInput(attrs={"size": 34}),
            "warnings": forms.Textarea(attrs={"rows": 2, "cols": 26}),
            "parser_strategy": forms.TextInput(attrs={"size": 16}),
        }

    def __init__(self, *args, total_pdf_pages=None, request_user=None, **kwargs):
        self.total_pdf_pages = total_pdf_pages
        self.request_user = request_user
        super().__init__(*args, **kwargs)
        self.fields["confidence"].disabled = True
        self.fields["source_toc_page"].disabled = True
        self.fields["parser_strategy"].disabled = True

    def clean(self):
        cleaned = super().clean()
        title = (cleaned.get("title") or "").strip()
        cleaned["title"] = title
        start_page = cleaned.get("start_page")
        end_page = cleaned.get("end_page")
        if cleaned.get("is_verified") and not title:
            self.add_error("title", "Verified lessons must have a title.")
        if start_page is not None:
            if start_page < 1:
                self.add_error("start_page", "Start page must be at least 1.")
            if self.total_pdf_pages and start_page > self.total_pdf_pages:
                self.add_error("start_page", "Start page cannot exceed total PDF pages.")
        if end_page is not None:
            if start_page is None:
                self.add_error("start_page", "Start page is required when end page is set.")
            elif end_page < start_page:
                self.add_error("end_page", "End page must be greater than or equal to start page.")
            if self.total_pdf_pages and end_page > self.total_pdf_pages:
                self.add_error("end_page", "End page cannot exceed total PDF pages.")
        if cleaned.get("is_verified") and not start_page:
            self.add_error("start_page", "Verified lessons need a physical PDF start page.")
        return cleaned

    def has_meaningful_changes(self):
        return bool(set(self.changed_data) - {"selected"})

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.has_meaningful_changes():
            instance.is_manually_edited = True
            if "is_verified" in self.changed_data and instance.is_verified:
                instance.verified_by = self.request_user
                instance.verified_at = timezone.now()
            if "is_verified" in self.changed_data and not instance.is_verified:
                instance.verified_by = None
                instance.verified_at = None
        if commit:
            instance.save()
        return instance


class BaseEbookLessonReviewFormSet(BaseModelFormSet):
    def __init__(self, *args, total_pdf_pages=None, request_user=None, **kwargs):
        self.total_pdf_pages = total_pdf_pages
        self.request_user = request_user
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs["total_pdf_pages"] = self.total_pdf_pages
        kwargs["request_user"] = self.request_user
        return super()._construct_form(i, **kwargs)

    def clean(self):
        super().clean()
        seen_orders = {}
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            order = form.cleaned_data.get("order")
            title = form.cleaned_data.get("title")
            start_page = form.cleaned_data.get("start_page")
            is_verified = form.cleaned_data.get("is_verified")
            if order is not None:
                if order in seen_orders:
                    form.add_error("order", "Duplicate lesson order.")
                    seen_orders[order].add_error("order", "Duplicate lesson order.")
                else:
                    seen_orders[order] = form
            if is_verified and (not title or not start_page):
                form.add_error(None, "Invalid rows cannot be verified.")


LessonReviewFormSet = modelformset_factory(
    EbookLesson,
    form=EbookLessonReviewForm,
    formset=BaseEbookLessonReviewFormSet,
    extra=0,
    can_delete=False,
)


class PageMappingAnchorForm(forms.ModelForm):
    class Meta:
        model = EbookPageMappingAnchor
        fields = ("printed_page_number", "physical_pdf_page", "is_verified", "note")


PageMappingAnchorFormSet = modelformset_factory(
    EbookPageMappingAnchor,
    form=PageMappingAnchorForm,
    extra=2,
    can_delete=True,
)
