from django.urls import reverse
from django.contrib import admin

from django.http import HttpResponseRedirect
from djangoql.admin import DjangoQLSearchMixin
from .models import Fiscal, CodigoReferido
from .forms import FiscalForm
from contacto.admin import ContactoAdminInline
from django_admin_row_actions import AdminRowActionsMixin
from django.contrib.admin.filters import DateFieldListFilter
from antitrolling.models import EventoScoringTroll


class FechaIsNull(DateFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.links = self.links[-2:]


class BaseBooleanFilter(admin.SimpleListFilter):
    # define a que lookup se tiene que aplicar el parametro booleano del filtro
    base_lookup = None
    # por defecto aplica True para 'sí' y "false" para no. Si
    # reversed_criteria está en True, se hace lo contrario
    reversed_criteria = False

    def lookups(self, request, model_admin):
        return (
            ('sí', 'sí'),
            ('no', 'no'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "sí":
            return self.queryset_si(request, queryset)
        elif value == "no":
            return self.queryset_no(request, queryset)
        return queryset

    def queryset_si(self, request, queryset):
        return queryset.filter(**{self.base_lookup: not self.reversed_criteria})

    def queryset_no(self, request, queryset):
        return queryset.filter(**{self.base_lookup: self.reversed_criteria})


class EsStaffFilter(BaseBooleanFilter):
    title = 'Es Staff'
    parameter_name = 'es_staff'
    base_lookup = 'user__is_staff'


class TieneReferente(BaseBooleanFilter):
    title = 'Tiene referente'
    parameter_name = 'tiene_referente'
    base_lookup = 'referente__isnull'
    reversed_criteria = True


class CertezaFilter(admin.SimpleListFilter):

    title = 'Certeza del referato'
    parameter_name = 'certeza'

    def lookups(self, request, model_admin):
        return (
            ('100', '100%'),
            ('75', '< 75%'),
            ('50', '< 50%'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == '100':
            return queryset.filter(referente_certeza=100)
        elif value:
            return queryset.filter(referente_certeza__lt=int(value))
        return queryset


def hacer_staff(modeladmin, request, queryset):
    for f in queryset:
        f.user.is_staff = True
        f.user.save(update_fields=['is_staff'])


hacer_staff.short_description = "Hacer staff (dataentry)"

def hacer_no_troll(modeladmin, request, queryset):
    for f in queryset:
        f.troll = False
        f.save(update_fields=['troll'])


hacer_no_troll.short_description = "Hacer NO troll"

class EventoScoringTrollInline(admin.TabularInline):
    model = EventoScoringTroll
    extra = 0
    fk_name = "fiscal_afectado"
    fields = ('motivo', 'mesa_categoria', 'automatico', 'attachment', 'actor', 'variacion')
    readonly_fields = ('motivo', 'mesa_categoria', 'attachment', 'automatico', 'actor', 'variacion')

    verbose_name = "Evento que afecta al scoring troll del fiscal"
    verbose_name_plural = "Eventos que afectan al scoring troll del fiscal"
    can_delete = False

    def has_add_permission(self, request):
        return False


class CodigoReferidoInline(admin.TabularInline):
    model = CodigoReferido
    extra = 0
    fk_name = "fiscal"
    readonly_fields = ('codigo',)
    verbose_name = "Código de referidos"

    def has_add_permission(self, request):
        return False


def enviar_email(modeladmin, request, queryset):
    selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
    ids = ",".join(selected)
    url = reverse('enviar-email')
    return HttpResponseRedirect(f'{url}?ids={ids}')


class FiscalAdmin(DjangoQLSearchMixin, AdminRowActionsMixin, admin.ModelAdmin):
    actions = [hacer_staff, enviar_email, hacer_no_troll]

    def get_row_actions(self, obj):
        row_actions = []
        if obj.user:
            row_actions.append(
                {
                    'label': f'Loguearse como {obj.nombres}',
                    'url': f'/hijack/{obj.user.id}/',
                    'enabled': True,
                }
            )
        if obj.estado == 'AUTOCONFIRMADO':
            row_actions.append(
                {
                    'label': f'Confirmar Fiscal',
                    'url': reverse('confirmar-fiscal', args=(obj.id,)),
                    'enabled': True,
                    'method': 'POST',
                }
            )
        label_troll = 'troll' if not obj.troll else 'no troll'
        row_actions.append(
            {
                'label': f'Marcar como {label_troll}',
                'url': reverse('cambiar-status-troll', args=(obj.id, not obj.troll)),
                'enabled': True
            }
        )
        row_actions.append(
            {
                'label': f'Ver referidos directos',
                'url': reverse('admin:fiscales_fiscal_changelist') + f'?referente__id={obj.id}',
                'enabled': True
            }
        )
        row_actions += super().get_row_actions(obj)
        return row_actions

    def scoring_troll(o):
        return o.scoring_troll()

    def es_staff(o):
        return o.user.is_staff if o.user else False

    es_staff.boolean = True

    form = FiscalForm
    list_display = ('__str__', 'dni', 'distrito', 'referente', 'referido_por_codigos', es_staff, 'troll', scoring_troll)
    readonly_fields = ['troll']
    search_fields = ('apellido', 'nombres', 'dni',)
    list_display_links = ('__str__',)
    list_filter = (TieneReferente, CertezaFilter, 'troll', EsStaffFilter, 'estado')
    raw_id_fields = ('attachment_asignado', 'mesa_categoria_asignada', 'referente', 'user')

    inlines = [
        EventoScoringTrollInline,
        CodigoReferidoInline,
        ContactoAdminInline,
    ]


admin.site.register(Fiscal, FiscalAdmin)
