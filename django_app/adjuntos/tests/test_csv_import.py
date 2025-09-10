import os

import pytest
from django.conf import settings
from elecciones.tests.conftest import fiscal_client, setup_groups # noqa
from django.urls import reverse
from http import HTTPStatus
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from adjuntos.csv_import import (ColumnasInvalidasError, CSVImporter, DatosInvalidosError,
                                 PermisosInvalidosError)
from elecciones.models import Carga, VotoMesaReportado, CategoriaOpcion, Opcion
from elecciones.tests.factories import (
    DistritoFactory,
    SeccionFactory,
    CircuitoFactory,
    MesaFactory,
    CategoriaGeneralFactory,
    CategoriaFactory,
    OpcionFactory,
    CategoriaOpcionFactory,
    MesaCategoriaFactory,
    FiscalFactory,
    UserFactory)
from adjuntos.models import CSVTareaDeImportacion
from elecciones.management.commands.importar_csv import Command as ImportarCSV
from constance.test import override_config

PATH_ARCHIVOS_TEST = os.path.dirname(os.path.abspath(__file__)) + '/archivos/'
CATEGORIAS = [('Presidente y vice', True), ('Gobernador y vice', True),
              ('Intendentes, Concejales y Consejeros Escolares', False),
              ('Senadores Nacionales', True), ('Diputados Nacionales', True),
              ('Senadores Provinciales', True), ('Diputados Provinciales', True)]


def test_validar_csv_fiscal_no_encontrado(db):
    user = UserFactory()
    with pytest.raises(PermisosInvalidosError) as e:
        CSVImporter(PATH_ARCHIVOS_TEST + 'info_resultados_negativos.csv', user).validar()
    assert 'Fiscal no encontrado' in str(e.value)


def test_validar_csv_fiscal_sin_permisos_suficientes(db):
    user = UserFactory()
    FiscalFactory(user=user)
    Group.objects.create(name='unidades basicas')
    g_visualizadores = Group.objects.create(name='visualizadores')
    user.groups.add(g_visualizadores)
    with pytest.raises(PermisosInvalidosError) as e:
        CSVImporter(PATH_ARCHIVOS_TEST + 'info_resultados_negativos.csv', user).validar()
    assert 'Su usuario no tiene los permisos necesarios' in str(e.value)


@pytest.fixture()
def usr_unidad_basica(db):
    user = UserFactory()
    FiscalFactory(user=user)
    for nombre in ['unidades basicas', 'visualizadores']:
        g = Group.objects.create(name=nombre)
    g_unidades_basicas = Group.objects.get(name='unidades basicas')
    user.groups.add(g_unidades_basicas)
    return user


def test_validar_csv_faltan_columnas(usr_unidad_basica):
    with pytest.raises(ColumnasInvalidasError):
        CSVImporter(PATH_ARCHIVOS_TEST + 'faltan_columnas.csv', usr_unidad_basica).validar()
    assert Carga.objects.count() == 0


def test_validar_csv_columnas_duplicadas(usr_unidad_basica):
    with pytest.raises(ColumnasInvalidasError):
        CSVImporter(PATH_ARCHIVOS_TEST + 'columnas_duplicadas.csv', usr_unidad_basica).validar()
    assert Carga.objects.count() == 0


def test_validar_csv_mesas_invalidas(db, usr_unidad_basica):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'mesas_invalidas.csv', usr_unidad_basica).procesar()
    assert 'No existe mesa' in errores
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 0
    assert Carga.objects.count() == 0


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_categorias_faltantes_en_archivo(db, usr_unidad_basica):
    CategoriaGeneralFactory()
    d1 = DistritoFactory(numero=1)
    s1 = SeccionFactory(numero=50, distrito=d1)
    c1 = CircuitoFactory(numero='2', seccion=s1)
    m = MesaFactory(numero='4012', lugar_votacion__circuito=c1, electores=100, circuito=c1)
    o2 = OpcionFactory(codigo='Todes')
    o3 = OpcionFactory(codigo='Juntos')
    c = CategoriaFactory(opciones=[o2, o3], nombre='Otra categoria')
    MesaCategoriaFactory(mesa=m, categoria=c)

    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_negativos.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 0
    assert 'Faltan datos en el archivo de la siguiente categoría' in errores
    assert Carga.objects.count() == 0


def hacer_prioritaria_en_cat(categoria, opcion):
    cat_opcion = categoria.categoriaopcion_set.get(opcion=opcion)
    cat_opcion.prioritaria = True
    cat_opcion.save()


@pytest.fixture()
def carga_inicial(db):
    d1 = DistritoFactory(numero=1)
    s1 = SeccionFactory(numero=50, distrito=d1)
    circ = CircuitoFactory(numero='2', seccion=s1)

    # Creamos los partidos.
    fdt = OpcionFactory(codigo='FdT', nombre='FdT', partido__nombre='FpT')
    jpc = OpcionFactory(codigo='JpC', nombre='JpC', partido__nombre='JpC')
    c2019 = OpcionFactory(codigo='C2019', nombre='C2019', partido__nombre='C2019')

    categorias = []
    for categoria, prioritaria in CATEGORIAS:
        categoria_general = CategoriaGeneralFactory(nombre=categoria)
        # La categoría en sí tiene un nombre arbitrario para testear que
        # el matching sea en base a la categoría general.
        categoria_bd = CategoriaFactory(nombre=f'Categoría {categoria}',
            categoria_general=categoria_general)

        # La factory las crea con unas opciones que hacen ruido en estos tests.
        for nombre in ['opc1', 'opc2', 'opc3', 'opc4']:
            opcion = Opcion.objects.get(nombre=nombre)
            opcion.delete()

        categorias.append(categoria_bd)
        CategoriaOpcionFactory(categoria=categoria_bd, prioritaria=prioritaria, opcion=fdt)
        CategoriaOpcionFactory(categoria=categoria_bd, prioritaria=prioritaria, opcion=jpc)
        if categoria == 'Presidente y vice':
            CategoriaOpcionFactory(categoria=categoria_bd, prioritaria=False, opcion=c2019)
        if prioritaria:
            # Adecuamos las opciones prioritarias.
            hacer_prioritaria_en_cat(categoria_bd, Opcion.total_votos())
            hacer_prioritaria_en_cat(categoria_bd, Opcion.blancos())
            hacer_prioritaria_en_cat(categoria_bd, Opcion.nulos())
            hacer_prioritaria_en_cat(categoria_bd, Opcion.sobres())
            hacer_prioritaria_en_cat(categoria_bd, Opcion.recurridos())
            hacer_prioritaria_en_cat(categoria_bd, Opcion.id_impugnada())
            hacer_prioritaria_en_cat(categoria_bd, Opcion.comando_electoral())

    MesaFactory(numero='4012', lugar_votacion__circuito=circ, electores=100, circuito=circ,
                categorias=categorias)


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_resultados_negativos(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_negativos.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 0
    assert 'Los resultados deben ser números enteros positivos' in errores
    assert Carga.objects.count() == 0


def test_procesar_csv_opciones_no_encontradas(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'opciones_invalidas.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 0
    assert 'El número de lista C2019 no fue encontrado' in errores
    assert Carga.objects.count() == 0


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_falta_total_de_votos(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'falta_total_votos.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 0
    assert f"Faltan las opciones: ['{Opcion.total_votos().nombre}'] en la mesa" in errores
    assert Carga.objects.count() == 0


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_informacion_valida_genera_resultados(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    # Debería haber 2 cargas total: Int (que no es prio), y presi, que es prio pero tiene
    # además opción no prioritaria.
    assert cargas_totales.count() == 2
    for total in cargas_totales:
        assert total.origen == 'csv'

    votos_carga_total = VotoMesaReportado.objects.filter(carga__in=cargas_totales).all()
    # Cat Int tiene 2 partidos + total + blancos + nulos + sobres = 6
    # Cat Pres tiene 3 partidos + total + blancos + nulos + sobres = 7
    assert votos_carga_total.count() == 13

    cargas_parciales = Carga.objects.filter(tipo=Carga.TIPOS.parcial)
    # Hay una sola categoría no prioritaria.
    assert cargas_parciales.count() == len(CATEGORIAS) - 1

    for parcial in cargas_parciales:
        assert parcial.origen == 'csv'

    votos_carga_parcial = VotoMesaReportado.objects.filter(carga__in=cargas_parciales).all()
    # Cada cat tiene 2 partidos + total + blancos + nulos + sobres = 6
    assert votos_carga_parcial.count() == (len(CATEGORIAS) - 1) * 6


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=False)
def test_procesar_csv_informacion_valida_genera_resultados_salvo_totales(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 0

    votos_carga_total = VotoMesaReportado.objects.filter(carga__in=cargas_totales).all()
    assert votos_carga_total.count() == 0

    cargas_parciales = Carga.objects.filter(tipo=Carga.TIPOS.parcial)
    # Hay una sola categoría no prioritaria.
    assert cargas_parciales.count() == len(CATEGORIAS) - 1

    for parcial in cargas_parciales:
        assert parcial.origen == 'csv'

    votos_carga_parcial = VotoMesaReportado.objects.filter(carga__in=cargas_parciales).all()
    # Cada cat tiene 2 partidos + total + blancos + nulos + sobres = 6
    assert votos_carga_parcial.count() == (len(CATEGORIAS) - 1) * 6


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_informacion_valida_copia_parciales_a_totales(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_copia_parciales_a_totales.csv',
        usr_unidad_basica).procesar()
    assert cant_mesas_parcialmente_ok == 0
    assert cant_mesas_ok == 1
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total).all()
    cargas_parciales = Carga.objects.filter(tipo=Carga.TIPOS.parcial).all()

    # Todo lo que está en carga total también está en carga parcial para la misma categoría.
    for carga_parcial in cargas_parciales:
        cargas_totales_misma_mc = cargas_totales.filter(mesa_categoria=carga_parcial.mesa_categoria)
        if cargas_totales_misma_mc.count() == 0:
            continue
        carga_total_misma_mc = cargas_totales_misma_mc.first()
        for voto in carga_parcial.reportados.all():
            assert VotoMesaReportado.objects.filter(carga=carga_total_misma_mc, votos=voto.votos,
                                                    opcion=voto.opcion).exists()

@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_falta_jpc_en_carga_parcial(db, usr_unidad_basica, carga_inicial):
    settings.OPCIONES_CARGAS_TOTALES_COMPLETAS = False
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'falta_jpc_carga_parcial.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 1
    assert "Faltan las opciones: ['JpC'] en la mesa" in errores
    assert Carga.objects.count() == 1


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_falta_jpc_en_carga_total(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'falta_jpc_carga_total.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 1
    assert "Los resultados para la carga total de la categoría Intendentes, Concejales y Consejeros Escolares deben estar completos. " \
           "Faltan las opciones: ['JpC'] en la mesa" in errores
    assert Carga.objects.count() == len(CATEGORIAS) - 1


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_caracteres_alfabeticos_en_votos(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'valores_texto_en_votos.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 1
    assert 'Los resultados deben ser números enteros positivos.' in errores
    assert Carga.objects.count() == 0


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_acumula_errores(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'acumula_errores.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 0
    assert cant_mesas_parcialmente_ok == 0
    assert 'Los resultados deben ser números enteros positivos.' in errores
    assert "Faltan las opciones: ['JpC'] en la mesa" in errores
    assert Carga.objects.count() == 0


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_informacion_valida_con_listas_numericas(db, usr_unidad_basica, carga_inicial):
    fdt = Opcion.objects.get(nombre='FdT')
    fdt.codigo = '136'
    fdt.save()
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok_con_listas_numericas.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    # Debería haber 2 cargas total: Int (que no es prio), y presi, que es prio pero tiene
    # además opción no prioritaria.
    assert cargas_totales.count() == 2


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_carga_reemplaza_anterior(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 2

    ids_viejos = list(cargas_totales.values_list('id', flat=True))

    # Vuelvo a cargar.

    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    # No aumentó.
    assert cargas_totales.count() == 2
    cargas_repetidas = Carga.objects.filter(id__in=ids_viejos)
    # No quedó ninguna de las viejas.
    assert cargas_repetidas.count() == 0


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_acepta_metadata_opcional(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok_con_metadata_optativa.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 2
    cargas_parciales = Carga.objects.filter(tipo=Carga.TIPOS.parcial)
    assert cargas_parciales.count() == len(CATEGORIAS) - 1


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_otros_separadores(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(PATH_ARCHIVOS_TEST + 'info_resultados_ok_separados_por_punto_y_coma.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 2

    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok_separados_por_tab.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 2


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_hace_importacion_parcial(db, usr_unidad_basica, carga_inicial):
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok_mas_error.csv', usr_unidad_basica).procesar()
    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    assert 'No existe mesa 4013' in errores
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 2


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
def test_procesar_csv_sanitiza_ok(db, usr_unidad_basica, carga_inicial):
    fdt = Opcion.objects.get(nombre='FdT')
    fdt.codigo = '136'
    fdt.save()
    cant_mesas_ok, cant_mesas_parcialmente_ok, errores = CSVImporter(
        PATH_ARCHIVOS_TEST + 'info_resultados_ok_con_sanitizar.csv', usr_unidad_basica).procesar()

    assert cant_mesas_ok == 1
    assert cant_mesas_parcialmente_ok == 0
    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    # Debería haber 2 cargas total: Int (que no es prio), y presi, que es prio pero tiene
    # además opción no prioritaria.
    assert cargas_totales.count() == 2


@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
@pytest.mark.django_db(transaction=True)
def test_web_upload_sin_errores(fiscal_client, carga_inicial):
    archivo = 'info_resultados_ok.csv'
    content = open(PATH_ARCHIVOS_TEST + archivo, 'rb')
    file = SimpleUploadedFile(archivo, content.read(), content_type="text/csv")
    data = {
        'file_field': (file,),
    }

    assert CSVTareaDeImportacion.objects.count() == 0

    response = fiscal_client.post(reverse('agregar-adjuntos-csv'), data)
    assert response.status_code == HTTPStatus.OK

    assert CSVTareaDeImportacion.objects.count() == 1

    tarea = CSVTareaDeImportacion.objects.first()

    assert tarea.status == CSVTareaDeImportacion.STATUS.pendiente

    importar_csv = ImportarCSV()

    importar_csv.wait_and_process_task()

    tarea.refresh_from_db()

    assert tarea.status == CSVTareaDeImportacion.STATUS.procesado
    assert tarea.mesas_total_ok == 1
    assert tarea.mesas_parc_ok == 0
    assert tarea.errores is None

    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 2

@override_config(CARGAR_OPCIONES_NO_PRIO_CSV=True)
@pytest.mark.django_db(transaction=True)
def test_web_upload_con_errores(fiscal_client, carga_inicial):
    archivo = 'falta_jpc_carga_parcial.csv'
    content = open(PATH_ARCHIVOS_TEST + archivo, 'rb')
    file = SimpleUploadedFile(archivo, content.read(), content_type="text/csv")
    data = {
        'file_field': (file,),
    }

    assert CSVTareaDeImportacion.objects.count() == 0

    response = fiscal_client.post(reverse('agregar-adjuntos-csv'), data)
    assert response.status_code == HTTPStatus.OK

    assert CSVTareaDeImportacion.objects.count() == 1

    tarea = CSVTareaDeImportacion.objects.first()

    assert tarea.status == CSVTareaDeImportacion.STATUS.pendiente

    importar_csv = ImportarCSV()

    importar_csv.wait_and_process_task()

    tarea.refresh_from_db()

    assert tarea.status == CSVTareaDeImportacion.STATUS.procesado
    assert tarea.mesas_total_ok == 0
    assert tarea.mesas_parc_ok == 1
    assert "Faltan las opciones: ['JpC'] en la mesa" in tarea.errores
    assert len(tarea.errores.split('\n')) == 6  # 6 líneas de error.

    cargas_totales = Carga.objects.filter(tipo=Carga.TIPOS.total)

    assert cargas_totales.count() == 1
