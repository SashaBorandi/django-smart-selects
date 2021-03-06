import django

from django.conf import settings
from django.contrib.admin.templatetags.admin_static import static
from django.core.urlresolvers import reverse
from django.forms.widgets import Select, SelectMultiple
from django import forms
from django.utils.safestring import mark_safe
from django.utils.encoding import force_text
from django.utils.html import escape
import json

from smart_selects.utils import unicode_sorter, sort_results

try:
    from django.apps import apps
    get_model = apps.get_model
except ImportError:
    from django.db.models.loading import get_model

if django.VERSION >= (1, 2, 0) and getattr(settings, 'USE_DJANGO_JQUERY', True):
    USE_DJANGO_JQUERY = True
else:
    USE_DJANGO_JQUERY = False
    JQUERY_URL = getattr(settings, 'JQUERY_URL', 'https://ajax.googleapis.com/ajax/libs/jquery/2.2.0/jquery.min.js')

URL_PREFIX = getattr(settings, "SMART_SELECTS_URL_PREFIX", "")


class ChainedSelect(Select):
    def __init__(self, to_app_name, to_model_name, chained_field, chained_model_field,
                 foreign_key_app_name, foreign_key_model_name, foreign_key_field_name,
                 show_all, auto_choose, manager=None, view_name=None, *args, **kwargs):
        self.to_app_name = to_app_name
        self.to_model_name = to_model_name
        self.chained_field = chained_field
        self.chained_model_field = chained_model_field
        self.show_all = show_all
        self.auto_choose = auto_choose
        self.manager = manager
        self.view_name = view_name
        self.foreign_key_app_name = foreign_key_app_name
        self.foreign_key_model_name = foreign_key_model_name
        self.foreign_key_field_name = foreign_key_field_name
        super(Select, self).__init__(*args, **kwargs)

    @property
    def media(self):
        """Media defined as a dynamic property instead of an inner class."""
        vendor = '' if django.VERSION < (1, 9, 0) else 'vendor/jquery/'
        extra = '' if settings.DEBUG else '.min'
        js = [
            '%sjquery%s.js' % (vendor, extra),
            'jquery.init.js',
        ]
        if USE_DJANGO_JQUERY:
            js = [static('admin/js/%s' % url) for url in js]
        elif JQUERY_URL:
            js = [JQUERY_URL]
        js = js + [static('smart-selects/admin/js/chainedfk.js')]

        return forms.Media(js=js)

    def render(self, name, value, attrs=None, choices=()):
        if len(name.split('-')) > 1:  # formset
            chained_field = '-'.join(name.split('-')[:-1] + [self.chained_field])
        else:
            chained_field = self.chained_field

        if not self.view_name:
            if self.show_all:
                view_name = "chained_filter_all"
            else:
                view_name = "chained_filter"
        else:
            view_name = self.view_name
        kwargs = {
            'app': self.to_app_name,
            'model': self.to_model_name,
            'field': self.chained_model_field,
            'foreign_key_app_name': self.foreign_key_app_name,
            'foreign_key_model_name': self.foreign_key_model_name,
            'foreign_key_field_name': self.foreign_key_field_name,
            'value': '1'
            }
        if self.manager is not None:
            kwargs.update({'manager': self.manager})
        url = URL_PREFIX + ("/".join(reverse(view_name, kwargs=kwargs).split("/")[:-2]))
        if self.auto_choose:
            auto_choose = 'true'
        else:
            auto_choose = 'false'
        iterator = iter(self.choices)
        if hasattr(iterator, '__next__'):
            empty_label = iterator.__next__()[1]
        else:
            # Hacky way to getting the correct empty_label from the field instead of a hardcoded '--------'
            empty_label = iterator.next()[1]

        js = """
        <script type="text/javascript">
        (function($) {
            var chainfield = "#id_%(chainfield)s";
            var url = "%(url)s";
            var id = "#%(id)s";
            var value = "%(value)s";
            var auto_choose = %(auto_choose)s;
            var empty_label = "%(empty_label)s";

            $(document).ready(function() {
                chainedfk.init(chainfield, url, id, value, empty_label, auto_choose);
            });
        })(jQuery || django.jQuery);
        </script>

        """
        js = js % {"chainfield": chained_field,
                   "url": url,
                   "id": attrs['id'],
                   'value': 'undefined' if value is None or value == '' else value,
                   'auto_choose': auto_choose,
                   'empty_label': escape(empty_label)}
        final_choices = []
        if value:
            available_choices = self._get_available_choices(self.queryset, value)
            for choice in available_choices:
                final_choices.append((choice.pk, force_text(choice)))
        if len(final_choices) > 1:
            final_choices = [("", (empty_label))] + final_choices
        if self.show_all:
            final_choices.append(("", (empty_label)))
            self.choices = list(self.choices)
            self.choices.sort(key=lambda x: unicode_sorter(x[1]))
            for ch in self.choices:
                if ch not in final_choices:
                    final_choices.append(ch)
        self.choices = ()
        final_attrs = self.build_attrs(attrs, name=name)
        if 'class' in final_attrs:
            final_attrs['class'] += ' chained'
        else:
            final_attrs['class'] = 'chained'
        
        output = js
        output += super(ChainedSelect, self).render(name, value, final_attrs, choices=final_choices)
        
        return mark_safe(output)

    def _get_available_choices(self, queryset, value):
        """
        get possible choices for selection
        """
        item = queryset.filter(pk=value).first()
        if item:
            try:
                pk = getattr(item, self.chained_model_field + "_id")
                filter = {self.chained_model_field: pk}
            except AttributeError:
                try:  # maybe m2m?
                    pks = getattr(item, self.chained_model_field).all().values_list('pk', flat=True)
                    filter = {self.chained_model_field + "__in": pks}
                except AttributeError:
                    try:  # maybe a set?
                        pks = getattr(item, self.chained_model_field + "_set").all().values_list('pk', flat=True)
                        filter = {self.chained_model_field + "__in": pks}
                    except:  # give up
                        filter = {}
            filtered = list(get_model(self.to_app_name, self.to_model_name).objects.filter(**filter).distinct())
            sort_results(filtered)
        else:
            # invalid value for queryset
            filtered = []

        return filtered


class ChainedSelectMultiple(SelectMultiple):
    def __init__(self, to_app_name, to_model_name, chain_field, chained_model_field,
                 foreign_key_app_name, foreign_key_model_name, foreign_key_field_name,
                 auto_choose, manager=None, *args, **kwargs):
        self.to_app_name = to_app_name
        self.to_model_name = to_model_name
        self.chain_field = chain_field
        self.chained_model_field = chained_model_field
        self.auto_choose = auto_choose
        self.manager = manager
        self.foreign_key_app_name = foreign_key_app_name
        self.foreign_key_model_name = foreign_key_model_name
        self.foreign_key_field_name = foreign_key_field_name

        super(SelectMultiple, self).__init__(*args, **kwargs)

    @property
    def media(self):
        """Media defined as a dynamic property instead of an inner class."""
        vendor = '' if django.VERSION < (1, 9, 0) else 'vendor/jquery/'
        extra = '' if settings.DEBUG else '.min'
        js = [
            '%sjquery%s.js' % (vendor, extra),
            'jquery.init.js',
        ]
        if USE_DJANGO_JQUERY:
            js = [static('admin/js/%s' % url) for url in js]
        elif JQUERY_URL:
            js = [JQUERY_URL]
        js = js + [static('smart-selects/admin/js/chainedm2m.js')]

        return forms.Media(js=js)

    def render(self, name, value, attrs=None, choices=()):
        if len(name.split('-')) > 1:  # formset
            chain_field = '-'.join(name.split('-')[:-1] + [self.chain_field])
        else:
            chain_field = self.chain_field

        view_name = 'chained_filter'

        kwargs = {
            'app': self.to_app_name,
            'model': self.to_model_name,
            'field': self.chained_model_field,
            'foreign_key_app_name': self.foreign_key_app_name,
            'foreign_key_model_name': self.foreign_key_model_name,
            'foreign_key_field_name': self.foreign_key_field_name,
            'value': '1'
            }
        if self.manager is not None:
            kwargs.update({'manager': self.manager})
        url = URL_PREFIX + ("/".join(reverse(view_name, kwargs=kwargs).split("/")[:-2]))
        if self.auto_choose:
            auto_choose = 'true'
        else:
            auto_choose = 'false'
        js = """
        <script type="text/javascript">
        (function($) {

        var chainfield = "#id_%(chainfield)s";
        var url = "%(url)s";
        var id = "#%(id)s";
        var value = %(value)s;
        var auto_choose = %(auto_choose)s;

        $(document).ready(function() {
            chainedm2m.init(chainfield, url, id, value, auto_choose);
        });
        })(jQuery || django.jQuery);
        </script>

        """
        js = js % {"chainfield": chain_field,
                   "url": url,
                   "id": attrs['id'],
                   'value': json.dumps(value),
                   'auto_choose': auto_choose}

        # since we cannot deduce the value of the chained_field
        # so we just render empty choices here and let the js
        # fetch related choices later
        final_choices = []
        self.choices = ()  # need to set explicitly because the Select widget will use it in render
        final_attrs = self.build_attrs(attrs, name=name)
        if 'class' in final_attrs:
            final_attrs['class'] += ' chained'
        else:
            final_attrs['class'] = 'chained'
        output = super(ChainedSelectMultiple, self).render(name, value, final_attrs, choices=final_choices)
        output += js
        return mark_safe(output)
