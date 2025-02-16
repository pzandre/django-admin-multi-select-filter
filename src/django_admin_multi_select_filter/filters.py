from django.contrib import admin
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.utils import reverse_field_path
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _


class MultiSelectFieldListFilter(admin.FieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        self.lookup_kwarg = field_path + "__in"
        self.lookup_kwarg_isnull = field_path + "__isnull"

        super().__init__(field, request, params, model, model_admin, field_path)

        self.lookup_val = self.used_parameters.get(self.lookup_kwarg, [])
        if len(self.lookup_val) == 1 and self.lookup_val[0] == "":
            self.lookup_val = []
        self.lookup_val_isnull = self.used_parameters.get(self.lookup_kwarg_isnull)

        self.empty_value_display = model_admin.get_empty_value_display()
        parent_model, reverse_path = reverse_field_path(model, field_path)
        # Obey parent ModelAdmin queryset when deciding which options to show
        if model == parent_model:
            queryset = model_admin.get_queryset(request)
        else:
            queryset = parent_model._default_manager.all()
        self.lookup_choices = (
            queryset.distinct().order_by(field.name).values_list(field.name, flat=True)
        )
        self.field_verboses = {}
        if self.field.choices:
            self.field_verboses = {field_value: field_verbose for
                                   field_value, field_verbose in
                                   self.field.choices}

    def expected_parameters(self):
        return [self.lookup_kwarg, self.lookup_kwarg_isnull]

    def choices(self, changelist):
        yield {
            "selected": not self.lookup_val and self.lookup_val_isnull is None,
            "query_string": changelist.get_query_string(
                remove=[self.lookup_kwarg, self.lookup_kwarg_isnull]
            ),
            "display": _("All"),
        }
        include_none = False
        for val in self.lookup_choices:
            if val is None:
                include_none = True
                continue
            val = str(val)

            if val in self.lookup_val:
                values = [v for v in self.lookup_val if v != val]
            else:
                values = self.lookup_val + [val]

            if values:
                yield {
                    "selected": val in self.lookup_val,
                    "query_string": changelist.get_query_string(
                        {self.lookup_kwarg: ",".join(values)},
                        [self.lookup_kwarg_isnull],
                    ),
                    "display": self.field_verboses.get(val, val),
                }
            else:
                yield {
                    "selected": val in self.lookup_val,
                    "query_string": changelist.get_query_string(
                        remove=[self.lookup_kwarg]
                    ),
                    "display": self.field_verboses.get(val, val),
                }

        if include_none:
            yield {
                "selected": bool(self.lookup_val_isnull),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "True"}, [self.lookup_kwarg]
                ),
                "display": self.empty_value_display,
            }


class MultiSelectRelatedFieldListFilter(admin.RelatedFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.lookup_kwarg = "%s__%s__in" % (field_path, field.target_field.name)
        self.lookup_kwarg_isnull = "%s__isnull" % field_path
        values = params.get(self.lookup_kwarg, [])
        self.lookup_val = values.split(",") if values else []
        self.lookup_choices = self.field_choices(field, request, model_admin)

    def choices(self, changelist):
        yield {
            "selected": self.lookup_val is None and not self.lookup_val_isnull,
            "query_string": changelist.get_query_string(
                remove=[self.lookup_kwarg, self.lookup_kwarg_isnull]
            ),
            "display": _("All"),
        }

        for pk_val, val in self.lookup_choices:
            if val is None:
                self.include_empty_choice = True
                continue
            val = str(val)

            if str(pk_val) in self.lookup_val:
                values = [str(v) for v in self.lookup_val if str(v) != str(pk_val)]
            else:
                values = self.lookup_val + [str(pk_val)]

            yield {
                "selected": self.lookup_val is not None
                and str(pk_val) in self.lookup_val,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: ",".join(values)}, [self.lookup_kwarg_isnull]
                ),
                "display": val,
            }
        empty_title = self.empty_value_display
        if self.include_empty_choice:
            yield {
                "selected": bool(self.lookup_val_isnull),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "True"}, [self.lookup_kwarg]
                ),
                "display": empty_title,
            }


class ExclusiveMultiSelectRelatedFieldListFilter(MultiSelectRelatedFieldListFilter):
    def queryset(self, request, queryset):
        try:
            if self.lookup_val_isnull:
                return queryset.filter(**{self.lookup_kwarg_isnull: True})

            choices = self.lookup_val
            choice_len = len(choices)
            if choice_len == 0:
                return queryset

            queryset = queryset.alias(
                nmatch=Count(
                    self.field_path,
                    filter=Q(**{f'{self.lookup_kwarg}': choices}),
                    distinct=True
                )
            ).filter(nmatch=choice_len)
            return queryset

        except (ValueError, ValidationError) as e:
            raise IncorrectLookupParameters(e)
