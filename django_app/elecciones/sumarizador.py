from functools import lru_cache
from attrdict import AttrDict
from django.db.models import Q, Sum, Subquery
from .models import (
    Distrito,
    SeccionPolitica,
    Seccion,
    Circuito,
    Opcion,
    VotoMesaReportado,
    LugarVotacion,
    Categoria,
    MesaCategoria,
    Mesa,
    TIPOS_DE_AGREGACIONES,
    OPCIONES_A_CONSIDERAR,
    NIVELES_DE_AGREGACION,
)
from .resultados import Resultados


NIVEL_DE_AGREGACION = {
    NIVELES_DE_AGREGACION.distrito: Distrito,
    NIVELES_DE_AGREGACION.seccion_politica: SeccionPolitica,
    NIVELES_DE_AGREGACION.seccion: Seccion,
    NIVELES_DE_AGREGACION.circuito: Circuito,
    NIVELES_DE_AGREGACION.lugar_de_votacion: LugarVotacion,
    NIVELES_DE_AGREGACION.mesa: Mesa
}


class Sumarizador():
    """
    Esta clase encapsula el cómputo de resultados.
    """
    def __init__(
        self,
        tipo_de_agregacion=TIPOS_DE_AGREGACIONES.todas_las_cargas,
        opciones_a_considerar=OPCIONES_A_CONSIDERAR.prioritarias,
        nivel_de_agregacion=None,
        ids_a_considerar=None
    ):
        """
        El tipo de cómputo indica qué datos se tienen en cuenta y cuáles no.
        Las opciones a considerar, lo que su nombre indica (si sólo las prioritarias o todas).
        El nivel_de_agregacion indica qué se va a tener en cuenta: si es None es todo el país.
        Si no, toma opciones en Eleccion.NIVELES_AGREGACION (distrito, sección, etc.)
        Por último, los ids_a_considerar son los ids de unidades de el nivel `nivel_de_agregacion`
        que deben considerarse. Si es None se consideran todos.
        """
        # Es una de TIPOS_DE_AGREGACIONES
        self.tipo_de_agregacion = tipo_de_agregacion

        # Es una de OPCIONES_A_CONSIDERAR
        self.opciones_a_considerar = opciones_a_considerar

        self.nivel_de_agregacion = nivel_de_agregacion

        self.ids_a_considerar = ids_a_considerar

        self.cache_opciones = None

    @lru_cache(128)
    def cargas_a_considerar_status_filter(self, categoria, prefix='carga__mesa_categoria__'):
        """
        Esta función devuelve los filtros que indican qué cargas se consideran para hacer el
        cómputo.
        """
        lookups = dict()

        if self.tipo_de_agregacion == TIPOS_DE_AGREGACIONES.solo_consolidados_doble_carga:
            if self.opciones_a_considerar == OPCIONES_A_CONSIDERAR.todas:
                lookups[f'{prefix}status'] = MesaCategoria.STATUS.total_consolidada_dc
            else:
                lookups[f'{prefix}status'] = MesaCategoria.STATUS.parcial_consolidada_dc

        elif self.tipo_de_agregacion == TIPOS_DE_AGREGACIONES.solo_consolidados:
            # Doble carga y CSV.
            if self.opciones_a_considerar == OPCIONES_A_CONSIDERAR.todas:
                lookups[f'{prefix}status__in'] = (
                    MesaCategoria.STATUS.total_consolidada_dc,
                    MesaCategoria.STATUS.total_consolidada_csv,
                )
            else:
                lookups[f'{prefix}status__in'] = (
                    MesaCategoria.STATUS.parcial_consolidada_dc,
                    MesaCategoria.STATUS.parcial_consolidada_csv,
                )

        elif self.tipo_de_agregacion == TIPOS_DE_AGREGACIONES.todas_las_cargas:
            if self.opciones_a_considerar == OPCIONES_A_CONSIDERAR.todas:
                lookups[f'{prefix}status__in'] = (
                    MesaCategoria.STATUS.total_consolidada_dc,
                    MesaCategoria.STATUS.total_consolidada_csv,
                    MesaCategoria.STATUS.total_sin_consolidar,
                )
            else:
                lookups[f'{prefix}status__in'] = (
                    MesaCategoria.STATUS.parcial_consolidada_dc,
                    MesaCategoria.STATUS.parcial_consolidada_csv,
                    MesaCategoria.STATUS.parcial_sin_consolidar,
                )

        return lookups

    @property
    def filtros(self):
        """
        Devuelve listas de sección, circuito, etc. para filtrar.
        """
        if not self.ids_a_considerar:
            return

        modelo = NIVEL_DE_AGREGACION.get(self.nivel_de_agregacion, None)
        if modelo:
            return modelo.objects.filter(id__in=self.ids_a_considerar)

    def lookups_de_mesas(self, prefix=""):
        lookups = dict()
        if self.filtros:
            if self.filtros.model is Distrito:
                lookups[f'{prefix}circuito__seccion__distrito__in'] = self.filtros

            if self.filtros.model is SeccionPolitica:
                lookups[f'{prefix}circuito__seccion__seccion_politica__in'] = self.filtros

            elif self.filtros.model is Seccion:
                lookups[f'{prefix}circuito__seccion__in'] = self.filtros

            elif self.filtros.model is Circuito:
                lookups[f'{prefix}circuito__in'] = self.filtros

            elif self.filtros.model is LugarVotacion:
                lookups[f'{prefix}lugar_votacion__id__in'] = self.filtros

            elif self.filtros.model is Mesa:
                lookups[f'{prefix}id__in'] = self.filtros
        return lookups

    def categorias(self):
        """
        Devuelve la lista de categorías posibles de acuerdo al model recibido.
        Esto podría no ser responsabilidad del sumarizador, pero su lógica es muy parecida a la de
        lookups_de_mesas, prefiero mantenerlos juntos.
        """

        lookups = Q(distrito__isnull=True)
        if self.filtros:
            distritos = None
            secciones = None

            # Shortcut para mesas que se resuelve por otro mecanismo
            if self.filtros.model is Mesa:
                cats = [categoria.id for mesa in self.filtros for categoria in mesa.categorias.all()]
                lookups = Q(id__in=cats)

            elif self.filtros.model is Distrito:
                distritos = self.filtros

            elif self.filtros.model is SeccionPolitica:
                # TODO Esto es dudoso porque al entrar a Buenos Aires muestra todas las categorías
                # de diputados/senadores provinciales. Sin embargo, si lo sacamos no hay otra forma
                # de llegar a ver esas categorías. Creo que el arbol debería incorporar las secciones
                # políticas como un subnivel.
                distritos = [seccion_politica.distrito for seccion_politica in self.filtros]

            elif self.filtros.model is Seccion:
                secciones = self.filtros

            elif self.filtros.model is Circuito:
                secciones = [circuito.seccion for circuito in self.filtros]

            elif self.filtros.model is LugarVotacion:
                secciones = [lugar_votacion.circuito.seccion for lugar_votacion in self.filtros]

            if secciones and not distritos:
                distritos = [seccion.distrito for seccion in secciones]

            if distritos:
                lookups = lookups | Q(distrito__in=distritos, seccion__isnull=True)

            if secciones:
                lookups = lookups | Q(seccion__in=secciones)

        return Categoria.objects.filter(lookups, activa=True)

    @lru_cache(128)
    def mesas(self, categoria):
        """
        Considerando los filtros posibles, devuelve el conjunto de mesas
        asociadas a la categoría dada.
        """
        lookups = self.lookups_de_mesas()
        return Mesa.objects.filter(categorias=categoria).filter(**lookups).distinct()

    def mesas_escrutadas(self):
        """
        De las mesas incluidas en los filtros seleccionados,
        aquellas que tienen votos para la categoría seleccionada.
        """
        return self.mesas_a_considerar.filter(
            mesacategoria__categoria=self.categoria,
            mesacategoria__carga_testigo__isnull=False,
            **self.cargas_a_considerar_status_filter(self.categoria, 'mesacategoria__')
        ).distinct()

    @lru_cache(128)
    def electores(self, categoria):
        """
        Devuelve el número de electores para :meth:`~.mesas`

        TODO: convertir esto en un método de ``MesaManager``
        """
        mesas = self.mesas(categoria)
        electores = mesas.aggregate(v=Sum('electores'))['v']
        return electores or 0

    def votos_reportados(self, categoria, mesas):
        """
        Me quedo con los votos reportados pertenecientes a las "cargas testigo"
        de las mesas que corresponden de acuerdo a los parámetros y la categoría.
        """
        votos_reportados = VotoMesaReportado.objects.filter(
            carga__mesa_categoria__mesa__in=Subquery(mesas.values('id')),
            carga__mesa_categoria__categoria=categoria,
            carga__es_testigo__isnull=False,
            opcion__in=self.opciones(),
            **self.cargas_a_considerar_status_filter(categoria)
        )

        return votos_reportados

    def opciones_dict(self):
        if self.cache_opciones is None:
            self.cache_opciones = {
                opcion.id: opcion
                for opcion in self.categoria.opciones_actuales(
                    solo_prioritarias=self.opciones_a_considerar == OPCIONES_A_CONSIDERAR.prioritarias,
                    excluir_optativas=True
                )
            }

        return self.cache_opciones

    def opciones(self):
        return self.opciones_dict().values()

    def get_opcion(self, id_opcion):
        return self.opciones_dict()[id_opcion]

    def opciones_no_partidarias(self):
        return (opcion for opcion in self.opciones() if opcion.partido is None)

    def votos_csv_export(self, categoria):
        """
        Obtiene el listado de votos para incluirse en una exportación CSV.
        """
        return VotoMesaReportado.objects.filter(
            carga__mesa_categoria__categoria=categoria,
            carga__es_testigo__isnull=False,
            **self.cargas_a_considerar_status_filter(categoria),
            **self.lookups_de_mesas("carga__mesa_categoria__mesa__")
        ).values_list(
            'carga__mesa_categoria__mesa__circuito__seccion__distrito__numero',
            'carga__mesa_categoria__mesa__circuito__seccion__numero',
            'carga__mesa_categoria__mesa__circuito__numero',
            'carga__mesa_categoria__mesa__numero',
            'opcion__codigo',
            'votos',
        ).order_by(
            "carga__mesa_categoria__mesa__circuito__seccion__distrito__numero",
            "carga__mesa_categoria__mesa__circuito__seccion__numero",
            "carga__mesa_categoria__mesa__circuito__numero",
            "carga__mesa_categoria__mesa__numero"
        )

    def votos_por_opcion(self, categoria, mesas):
        """
        Dada una categoría y un conjunto de mesas, devuelve una tabla de resultados con la cantidad de
        votos por cada una de las opciones posibles (partidarias o no)
        """

        # Obtener los votos reportados
        votos_reportados = self.votos_reportados(categoria, mesas).values_list('opcion__id').annotate(
            sum_votos=Sum('votos')
        )

        # Diccionario inicial, opciones completas, todas en 0 (por si alguna opción no viene reportada).
        votos_por_opcion = {opcion.id: 0 for opcion in self.opciones()}

        # Sobreescribir los valores default (en 0) con los votos reportados
        votos_por_opcion.update(votos_reportados)

        return votos_por_opcion.items()

    def agrupar_votos(self, votos_por_opcion):
        votos_positivos = {}
        votos_no_positivos = {opcion.nombre_corto: 0 for opcion in self.opciones_no_partidarias()}
        for id_opcion, sum_votos in votos_por_opcion:
            opcion = self.get_opcion(id_opcion)
            if opcion.partido:
                # 3.1 Opciones partidarias se agrupan con otras opciones del mismo partido.
                votos_positivos.setdefault(opcion.partido, {})[opcion] = sum_votos
            else:
                # 3.2 Opciones no partidarias
                # TODO ¿Puede realmente pasar que no vengan las opciones completas?
                votos_no_positivos[opcion.nombre_corto] = sum_votos if sum_votos else 0

        return votos_positivos, votos_no_positivos

    def calcular(self, categoria, mesas):
        """
        Implementa los cómputos esenciales de la categoría para las mesas dadas.
        Se invoca una vez para el cálculo de resultados y N veces para los proyectados.

        Devuelve
            electores: cantidad de electores en las mesas válidas de la categoría
            electores_en_mesas_escrutadas: cantidad de electores en las mesas efectivamente escrutadas
            votos: diccionario con resultados de votos por partido y opción (positivos y no positivos)
            total_positivos: total votos positivos
            total: total votos (positivos + no positivos)
        """

        # 1) Mesas.
        # Me quedo con las mesas que corresponden de acuerdo a los parámetros
        # y la categoría, que tengan la carga testigo para esa categoría.
        mesas_escrutadas = self.mesas_escrutadas()
        total_mesas_escrutadas = mesas_escrutadas.count()
        total_mesas = mesas.count()

        # 2) Electores.
        electores = mesas.filter(categorias=categoria).aggregate(v=Sum('electores'))['v'] or 0
        electores_en_mesas_escrutadas = mesas_escrutadas.aggregate(v=Sum('electores'))['v'] or 0

        # 3) Votos
        votos_por_opcion = self.votos_por_opcion(categoria, mesas)
        votos_positivos, votos_no_positivos = self.agrupar_votos(votos_por_opcion)

        return AttrDict({
            "total_mesas": total_mesas,
            "total_mesas_escrutadas": total_mesas_escrutadas,
            "electores": electores,
            "electores_en_mesas_escrutadas": electores_en_mesas_escrutadas,
            "votos_positivos": votos_positivos,
            "votos_no_positivos": votos_no_positivos,
        })

    @lru_cache(128)
    def get_resultados(self, categoria):
        """
        Realiza la contabilidad para la categoría, invocando al método ``calcular``.
        """
        self.categoria = categoria
        self.mesas_a_considerar = self.mesas(categoria)
        return Resultados(self.opciones_a_considerar, self.calcular(categoria, self.mesas_a_considerar))
