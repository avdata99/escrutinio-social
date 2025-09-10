from django import forms
from django.contrib import admin
from django.urls import reverse
from djangoql.admin import DjangoQLSearchMixin
from leaflet.admin import LeafletGeoAdmin
from .models import (
    Distrito,
    SeccionPolitica,
    Seccion,
    Circuito,
    LugarVotacion,
    Mesa,
    Partido,
    Carga,
    Opcion,
    CategoriaOpcion,
    CategoriaGeneral,
    Categoria,
    VotoMesaReportado,
    MesaCategoria,
    Eleccion,
    TecnicaProyeccion,
    AgrupacionCircuitos,
    AgrupacionCircuito,
    ConfiguracionComputo,
    ConfiguracionComputoDistrito,
    CargaOficialControl,
)
from .forms import CategoriaForm, SeccionForm
from django.http import HttpResponseRedirect
from django_admin_row_actions import AdminRowActionsMixin
from fiscales.admin import BaseBooleanFilter


class EsTestigoFilter(BaseBooleanFilter):
    title = 'Es testigo'
    parameter_name = 'es_testigo'
    base_lookup = 'es_testigo__isnull'
    reversed_criteria = True


class HasLatLongListFilter(BaseBooleanFilter):
    """
    Filtro para escuelas
    """
    title = 'Tiene coordenadas'
    parameter_name = 'coordenadas'
    base_lookup = 'geom__isnull'
    reversed_criteria = True


class TieneResultados(BaseBooleanFilter):
    """
    filtro para mesas
    """
    title = 'Tiene resultados'
    parameter_name = 'tiene_resultados'
    base_lookup = 'cargas__isnull'
    reversed_criteria = True


def mostrar_en_mapa(modeladmin, request, queryset):
    selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
    ids = ",".join(selected)
    mapa_url = reverse('mapa')
    return HttpResponseRedirect(f'{mapa_url}?ids={ids}')


mostrar_en_mapa.short_description = "Mostrar seleccionadas en el mapa"


def mostrar_resultados_escuelas(modeladmin, request, queryset):
    selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
    ids = ",".join(selected)
    mapa_url = reverse('resultados_escuelas')
    return HttpResponseRedirect(f'{mapa_url}?ids={ids}')


mostrar_resultados_escuelas.short_description = "Mostrar resultados de Escuelas seleccionadas"


def resultados_reportados(modeladmin, request, queryset):

    selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
    name = modeladmin.model.__name__.lower()
    ids = "&".join(f'{name}={s}' for s in selected)
    res_url = reverse('resultados-categoria', args=[1])
    return HttpResponseRedirect(f'{res_url}?{ids}')


resultados_reportados.short_description = "Ver Resultados"


class LugarVotacionAdmin(DjangoQLSearchMixin, AdminRowActionsMixin, LeafletGeoAdmin):

    def sección(o):
        return o.circuito.seccion.numero

    list_display = (
        'nombre', 'direccion', 'ciudad', 'circuito', sección, 'mesas_desde_hasta', 'electores',
        'estado_geolocalizacion'
    )
    raw_ids_fields = ('circuito',)
    list_display_links = ('nombre', )
    list_filter = (HasLatLongListFilter, 'circuito__seccion', 'circuito')
    search_fields = ('nombre', 'direccion', 'ciudad', 'barrio', 'mesas__numero')
    show_full_result_count = False
    actions = [mostrar_en_mapa, resultados_reportados]

    def get_row_actions(self, obj):
        row_actions = [{
            'label': 'Mesas',
            'url': reverse('admin:elecciones_mesa_changelist') + f'?lugar_votacion__id={obj.id}',
            'enabled': True,
        }]
        row_actions += super().get_row_actions(obj)
        return row_actions


def mostrar_resultados_mesas(modeladmin, request, queryset):
    selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
    ids = ",".join(selected)
    mapa_url = reverse('resultados_mesas_ids')
    return HttpResponseRedirect(f'{mapa_url}?ids={ids}')


mostrar_resultados_mesas.short_description = "Mostrar resultados de Mesas seleccionadas"


class MesaForm(forms.ModelForm):
    copiar_categorias = forms.BooleanField(
        initial=True,
        label="Copiar las categorias del resto de las mesas en el circuito (sólo vale para la creación)"
    )

    def save(self, commit=True):
        add = not self.instance.pk
        copiar_categorias = self.cleaned_data.get('copiar_categorias', None)

        mesa = super().save(commit=commit)
        mesa.save()

        if add and copiar_categorias:
            otra_mesa = Mesa.objects.filter(circuito=mesa.circuito).first()

            if otra_mesa:
                if not mesa.electores:
                    mesa.electores = otra_mesa.electores
                for categoria in otra_mesa.categorias.all():
                    mesa.categorias.add(categoria)
        return mesa

    class Meta:
        model = Mesa
        fields = '__all__'


class MesaAdmin(DjangoQLSearchMixin, AdminRowActionsMixin, admin.ModelAdmin):
    form = MesaForm
    actions = [resultados_reportados]
    list_display = ('numero', 'get_circuito', 'get_seccion', 'get_distrito')
    raw_id_fields = ('circuito', 'lugar_votacion')
    list_filter = (
        TieneResultados, 'es_testigo',# 'circuito__seccion', 'circuito'
    )
    search_fields = (
        'numero',
        'circuito__nombre',
        'circuito__seccion__nombre',
        'circuito__seccion__distrito__nombre',
        'circuito__numero',
        'circuito__seccion__numero',
        'circuito__seccion__distrito__numero',
    )

    def get_circuito(self, obj):
        return obj.circuito
    get_circuito.short_description = "Circuito"
    get_circuito.admin_order_field = "circuito__numero"

    def get_seccion(self, obj):
        return obj.circuito.seccion
    get_seccion.short_description = "Sección"
    get_seccion.admin_order_field = "circuito__seccion__numero"

    def get_distrito(self, obj):
        return obj.circuito.seccion.distrito
    get_distrito.short_description = "Distrito"
    get_distrito.admin_order_field = "circuito__seccion__distrito__numero"

    def get_row_actions(self, obj):
        row_actions = []

        row_actions.append({
            'label': f'Ver Mesa-categorias',
            'url': reverse('admin:elecciones_mesacategoria_changelist') + f'?mesa={obj.id}',
            'enabled': True
        })

        if obj.lugar_votacion:
            row_actions.append({
                'label': 'Escuela',
                'url': reverse('admin:elecciones_lugarvotacion_changelist') + f'?id={obj.lugar_votacion.id}',
                'enabled': True,
            })
        row_actions += super().get_row_actions(obj)
        return row_actions


class PartidoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre')
    list_display_links = list_display


class MesaCategoriaAdmin(DjangoQLSearchMixin, AdminRowActionsMixin, admin.ModelAdmin):
    list_display = ['mesa', 'categoria', 'status']
    raw_id_fields = ['mesa', 'categoria', 'carga_testigo', 'carga_oficial', 'parcial_oficial']
    list_filter = ['status', ]

    def get_row_actions(self, obj):
        row_actions = [{
            'label': 'Ver cargas',
            'url': reverse('admin:elecciones_carga_changelist') + f'?mesa_categoria={obj.id}',
            'enabled': True,
        }]
        row_actions += super().get_row_actions(obj)
        return row_actions


class CircuitoAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    list_display = ('__str__', 'seccion', 'distrito')
    list_display_links = list_display
    list_filter = ('seccion', )
    search_fields = (
        'nombre',
        'numero',
        'seccion__nombre',
        'seccion__distrito__nombre'
    )


class DistritoAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    search_fields = (
        'nombre',
        'numero',
    )


class SeccionPoliticaAdmin(admin.ModelAdmin):
    list_display = ['numero', 'nombre', 'distrito']

    search_fields = (
        'nombre',
        'numero',
    )


class SeccionAdmin(admin.ModelAdmin):
    list_display = ['numero', 'nombre', 'distrito', 'seccion_politica']
    search_fields = (
        'nombre',
        'numero',
        'distrito__nombre',
    )
    form = SeccionForm
    fieldsets = (
        (None, {
            'fields': ('distrito', 'seccion_politica', 'numero', 'nombre', 'electores')
        }),
        (
            'Prioridades', {
                'fields': (
                    'prioridad_hasta_2', 'prioridad_2_a_10', 'prioridad_10_a_100',
                    'cantidad_minima_prioridad_hasta_2'
                ),
                'classes': ['wide']
            }
        ),
    )


class VotoMesaReportadoAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    list_display = [
        'carga',
        'id',
        'opcion',
        'votos',
    ]
    list_display_links = list_display
    list_filter = ('carga__mesa_categoria__categoria', 'opcion')
    search_fields = [
        'carga__mesa_categoria__mesa__numero',
        'carga__mesa_categoria__mesa__circuito__nombre',
        'carga__mesa_categoria__mesa__lugar_votacion__nombre'
    ]


class OpcionAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    list_display = ['codigo', 'nombre_corto', 'partido', 'nombre']


class CategoriaGeneralAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    list_display = ['nombre', 'slug']
    search_fields = ['nombre', 'slug']
    ordering = ['nombre']


class CategoriaAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    list_display = ['categoria_general', 'nombre', 'activa', 'distrito', 'seccion']
    search_fields = ['nombre']
    list_filter = ['activa']
    ordering = ['categoria_general__nombre', 'nombre']
    form = CategoriaForm


class CategoriaOpcionAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    search_fields = ['categoria__nombre', 'opcion__nombre']
    ordering = ['categoria__nombre', 'orden']


class AgrupacionCircuitoInline(admin.TabularInline):
    model = AgrupacionCircuito
    raw_id_fields = ['circuito']
    extra = 1
    verbose_name = "Circuitos"
    verbose_name_plural = "Circuitos en esta Agrupación"


class AgrupacionCircuitosInline(admin.TabularInline):
    model = AgrupacionCircuitos
    ordering = ['nombre']
    inlines = [AgrupacionCircuitoInline]


class TecnicaProyeccionAdmin(admin.ModelAdmin):
    search_fields = ['nombre']
    ordering = ['nombre']
    inlines = [AgrupacionCircuitosInline]


class AgrupacionCircuitosAdmin(admin.ModelAdmin):
    search_fields = ['proyeccion__nombre', 'nombre']
    ordering = ['proyeccion']
    list_filter = ['proyeccion']
    inlines = [AgrupacionCircuitoInline]


class VotoMesaReportadoInline(admin.TabularInline):
    model = VotoMesaReportado
    extra = 0
    can_delete = False
    fields = ['opcion', 'votos']
    readonly_fields = ['opcion']
    ordering = ['opcion__id']


class CargaAdmin(DjangoQLSearchMixin, AdminRowActionsMixin, admin.ModelAdmin):
    list_display = ['mesa_categoria', 'fiscal', 'tipo', 'created', 'es_testigo']
    readonly_fields = ['fiscal', 'mesa_categoria']
    inlines = [VotoMesaReportadoInline]
    list_filter = ['tipo', EsTestigoFilter]

    def es_testigo(self, obj):
        return obj.es_testigo.exists()

    es_testigo.boolean = True

    def get_row_actions(self, obj):
        row_actions = [{
            'label': 'Ver mesa-categoria',
            'url': reverse('admin:elecciones_mesacategoria_changelist') + f'?id={obj.mesa_categoria.id}',
            'enabled': True,
        }]
        row_actions += super().get_row_actions(obj)
        return row_actions


class ConfiguracionComputoDistritoInline(admin.TabularInline):
    model = ConfiguracionComputoDistrito


class ConfiguracionComputoAdmin(admin.ModelAdmin):
    inlines = (ConfiguracionComputoDistritoInline, )


class CargaOficialControlAdmin(admin.ModelAdmin):
    list_display = ['fecha_ultimo_registro', 'categoria']


admin.site.register(Eleccion)
admin.site.register(Carga, CargaAdmin)
admin.site.register(Distrito, DistritoAdmin)
admin.site.register(SeccionPolitica, SeccionPoliticaAdmin)
admin.site.register(Seccion, SeccionAdmin)
admin.site.register(Circuito, CircuitoAdmin)
admin.site.register(Partido, PartidoAdmin)
admin.site.register(LugarVotacion, LugarVotacionAdmin)
admin.site.register(Mesa, MesaAdmin)
admin.site.register(MesaCategoria, MesaCategoriaAdmin)
admin.site.register(VotoMesaReportado, VotoMesaReportadoAdmin)
admin.site.register(Opcion, OpcionAdmin)
admin.site.register(Categoria, CategoriaAdmin)
admin.site.register(CategoriaGeneral, CategoriaGeneralAdmin)
admin.site.register(CategoriaOpcion, CategoriaOpcionAdmin)
admin.site.register(TecnicaProyeccion, TecnicaProyeccionAdmin)
admin.site.register(AgrupacionCircuitos, AgrupacionCircuitosAdmin)
admin.site.register(ConfiguracionComputo, ConfiguracionComputoAdmin)
admin.site.register(CargaOficialControl, CargaOficialControlAdmin)
