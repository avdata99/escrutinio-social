from constance import config
from adjuntos.models import Identificacion
from elecciones.models import Carga, CargasIncompatiblesError
from .models import (
    aumentar_scoring_troll_carga,
    disminuir_scoring_troll_carga,
    aumentar_scoring_troll_identificacion,
    disminuir_scoring_troll_identificacion,
    aumentar_scoring_troll_problema_descartado,
    EventoScoringTroll
)

import structlog

logger = structlog.get_logger(__name__)


def efecto_scoring_troll_asociacion_attachment(attachment, mesa):
    """
    Realizar las actualizaciones de scoring troll que correspondan
    a partir de que se confirma la asignación de mesa a un attachment
    """

    for identificacion in attachment.identificaciones.filter(invalidada=False):
        if identificacion.status != Identificacion.STATUS.identificada or identificacion.mesa != mesa:
            #  Para cada identificación del attachment que no coincida en mesa,
            #  aumentar el scoring troll del fiscal que la hizo
            aumentar_scoring_troll_identificacion(
                config.SCORING_TROLL_IDENTIFICACION_DISTINTA_A_CONFIRMADA,
                identificacion
            )
        else:
            #  Para cada identificación del attachment que sí coincida en mesa,
            #  disminuir el scoring troll del fiscal que la hizo
            disminuir_scoring_troll_identificacion(
                config.SCORING_TROLL_DESCUENTO_ACCION_CORRECTA,
                identificacion
            )


def efecto_scoring_troll_confirmacion_carga(mesa_categoria):
    """
    Realizar las actualizaciones de scoring troll que correspondan
    a partir de que se confirman los datos cargados para una MesaCategoria.
    Funciona para confirmación, tanto de carga parcial como de carga total.
    """

    testigo = mesa_categoria.carga_testigo
    for carga in mesa_categoria.cargas.filter(invalidada=False):
        if carga.tipo == testigo.tipo and carga.firma != testigo.firma:
            # se calcula la diferencia. Puede dar error, en tal caso se considera diferencia 0
            try:
                diferencia = testigo - carga
            except CargasIncompatiblesError as e:
                logger.warning(f'Error al calcular diferencia entre opciones, {e} - se toma 0')
                diferencia = 0

            # se aumenta el scoring del fiscal que cargo distinto
            if diferencia:
                aumentar_scoring_troll_carga(
                    diferencia, carga, EventoScoringTroll.MOTIVOS.carga_valores_distintos_a_confirmados
                )
        elif carga.tipo == Carga.TIPOS.problema:
            aumentar_scoring_troll_carga(
                config.SCORING_TROLL_PROBLEMA_MESA_CATEGORIA_CON_CARGA_CONFIRMADA,
                carga,
                EventoScoringTroll.MOTIVOS.indica_problema_mesa_categoria_confirmada
            )
        elif carga.tipo == testigo.tipo and carga.firma == testigo.firma:
            # se disminuye el scoring del fiscal que cargo los valores aceptados
            disminuir_scoring_troll_carga(
                config.SCORING_TROLL_DESCUENTO_ACCION_CORRECTA, carga
            )


def efecto_determinacion_fiscal_troll(fiscal):
    """
    Acciones que se desencadenan a partir de que se determina que un fiscal es troll.
    La determinación puede ser automática o manual.
    """

    # Invalidar todas las cargas e identificaciones que hubiera hecho el fiscal
    for carga in Carga.objects.filter(fiscal=fiscal):
        carga.invalidar()

    for identificacion in Identificacion.objects.filter(fiscal=fiscal):
        identificacion.invalidar()


def efecto_scoring_troll_descartar_problema(fiscal, problema):
    """
    Realiza el efecto de que se descarte un "problema" reportado por el usuario parámetro.
    """
    aumentar_scoring_troll_problema_descartado(
        config.SCORING_TROLL_PROBLEMA_DESCARTADO,
        fiscal,
        problema.mesa,
        problema.attachment
    )
