from django.core.management.base import BaseCommand, CommandError
from fiscales.models import Fiscal
from elecciones.models import Seccion, Distrito
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = """ Generar accesos para los usuarios del sistema.
            """

    def add_arguments(self, parser):
        parser.add_argument('--prefijo', default='usr', type=str, help='Prefijo de los usuarios al que se agrega _ y el nro de serie.')
        parser.add_argument('--indice_inicial', type=int, default=0, help='Índice inicial.')
        parser.add_argument('--cantidad', type=int, help='Cantidad de usuarios a crear.')
        parser.add_argument('--grupo', default='fiscales con acceso al bot', type=str, help='En qué grupo se agregan.')
        parser.add_argument('--nro_seccion', type=str, help='Nro de la sección a la que corresponde el usuario.')
        parser.add_argument('--nro_distrito', type=str, help='Nro del distrito a la que corresponde el usuario.')
        parser.add_argument('--por_seccion', dest='por_seccion', action='store_true', default=False, help='Genera usuarios por sección dentro del distrito indicado.')
        parser.add_argument('--por_distrito', dest='por_distrito', action='store_true', default=False, help='Genera usuarios por distrito.')

    def crear_acceso(self, prefijo, indice, grupo, distrito, seccion, sobre_escribir=True):
        username = slugify(f'{prefijo}{indice:03d}')

        user, created = User.objects.get_or_create(username=username)
        user.is_staff = False
        if created or sobre_escribir:
            password = User.objects.make_random_password().lower()[0:8]
            user.set_password(password)
        else:
            password = None

        user.save()

        fiscal, created = Fiscal.objects.get_or_create(user=user)
        fiscal.estado = 'CONFIRMADO'
        fiscal.notas = f'Generado automáticamente en el grupo {grupo.name} por el sistema'
        fiscal.email_confirmado = True
        fiscal.apellido = username
        fiscal.nombres = username
        fiscal.distrito = distrito
        fiscal.seccion = seccion
        fiscal.save()

        # Lo agrego al grupo.
        user.groups.add(grupo)

        return user, password

    def alta_usuarios(self, prefijo, indice_inicial, cantidad, distrito, seccion, grupo):
        for i in range(indice_inicial, indice_inicial + cantidad):
            user, clave = self.crear_acceso(
                prefijo=prefijo, indice=i, grupo=grupo,
                distrito=distrito, seccion=seccion, sobre_escribir=True
            )
            self.stdout.write(self.style.SUCCESS(f'{user},{clave}'))

    def alta_usuarios_por_seccion(self, prefijo, indice_inicial, cantidad, distrito, grupo):
        """
        Da de alta usuarios en cada sección del distrito.
        """
        secciones = distrito.secciones.all()
        for seccion in secciones:
            nombre = seccion.nombre.lower().replace(' ', '')
            self.alta_usuarios(f'{nombre}{prefijo}', indice_inicial, cantidad, distrito, seccion, grupo)

    def alta_usuarios_por_distrito(self, prefijo, indice_inicial, cantidad, grupo):
        """
        Da de alta usuarios en cada distrito.
        """
        distritos = Distrito.objects.all()
        for distrito in distritos:
            nombre = distrito.nombre.lower().replace(' ', '')
            self.alta_usuarios(f'{nombre}{prefijo}', indice_inicial, cantidad, distrito, None, grupo)

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('--- Generando usuarios ---'))

        prefijo = options['prefijo']
        indice_inicial = options['indice_inicial']
        cantidad = options['cantidad']
        nombre_grupo = options['grupo']
        grupo = Group.objects.get(name=nombre_grupo)
        nro_seccion = options['nro_seccion']
        nro_distrito = options['nro_distrito']
        distrito = Distrito.objects.get(numero=nro_distrito) if nro_distrito else None
        seccion = Seccion.objects.get(numero=nro_seccion, distrito__numero=nro_distrito) if nro_seccion and nro_distrito else None

        if options['por_seccion']:
            self.alta_usuarios_por_seccion(prefijo, indice_inicial, cantidad, distrito, grupo)
        elif options['por_distrito']:
            self.alta_usuarios_por_distrito(prefijo, indice_inicial, cantidad, grupo)
        else:
            self.alta_usuarios(prefijo, indice_inicial, cantidad, distrito, seccion, grupo)

        self.stdout.write(self.style.SUCCESS('--- Terminado. ---'))

