from django import forms
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db.models import Q

from upload_validator import FileTypeValidator

from .models import Identificacion, PreIdentificacion
from elecciones.models import Mesa, Seccion, Circuito, Distrito

from .widgets import Select

import re

MENSAJES_ERROR = {
    "distrito": "",
    "seccion": "Esta sección no pertenece al distrito",
    "circuito": "Este circuito no pertenece a la sección",
    "mesa": "Esta mesa no pertenece al circuito",
    "circuito_mesa": "Esta mesa no existe en el circuito",
    "seccion_mesa": "Esta mesa no existe en la sección",
}


class SelectField(forms.ModelChoiceField):

    widget = Select

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = kwargs.get("label", self.queryset.model._meta.object_name)
        required = kwargs.get("required", True)
        self.widget.attrs["required"] = required

    def clean(self, value):
        if value == "" or value == -1 or value == "-1":
            return None
        return super().clean(value)


class CharFieldModel(forms.CharField):
    def queryset(self, value, *args):
        query = {self.predicate: value}
        return self.model.objects.filter(*args, **query)

    def __init__(self, model, predicate, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = model
        self.predicate = predicate
        self.label = kwargs.get("label", self.model._meta.object_name)

    def clean(self, value):
        if value == "" or value == "-1":
            return None
        return super().clean(value)

    def get_object(self, value, *args):
        datum = super().clean(value)
        objs = self.queryset(datum, *args).distinct()
        if objs.count() != 1:
            return None
        return objs[0]


class IdentificacionForm(forms.ModelForm):
    """
    Este formulario se utiliza para asignar mesa
    """

    class Media:
        js = ('identificacion.js',)

    distrito = SelectField(
        required=True,
        queryset=Distrito.objects.all(),
        help_text="Puede ingresar número o nombre",
    )

    seccion = CharFieldModel(
        model=Seccion,
        predicate="numero__iexact",
        label="Sección",
    )

    circuito = CharFieldModel(
        model=Circuito,
        predicate="numero__iexact",
    )

    mesa = CharFieldModel(required=True, model=Mesa, predicate="numero__iexact")

    class Meta:
        model = Identificacion
        fields = ["distrito", "seccion", "circuito", "mesa"]

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        if instance and instance.mesa:
            circuito = instance.mesa.lugar_votacion.circuito
            kwargs["initial"]["circuito"] = circuito
            kwargs["initial"]["seccion"] = circuito.seccion
            kwargs["initial"]["distrito"] = circuito.seccion.distrito
        super().__init__(*args, **kwargs)

    def check_seccion(self, distrito, mesa=None):
        seccion_nro = self.fields["seccion"].clean(self.data["seccion"])
        seccion = None

        if seccion_nro is not None:
            # la busco en el distrito
            lookup = Q(distrito_id=distrito.id)
            seccion = self.fields["seccion"].get_object(seccion_nro, lookup)
            if seccion is None:
                # no lo encontré, la seccion no pertenece al distrito
                self.add_error("seccion", MENSAJES_ERROR["seccion"])
            return seccion

        # sólo lo puedo encontrar gracias a la mesa.
        if mesa is None:
            self.add_error("seccion", MENSAJES_ERROR["seccion"])
            return None

        seccion = mesa.circuito.seccion
        if seccion and seccion.distrito != distrito:
            self.add_error("seccion", MENSAJES_ERROR["seccion"])
        else:
            return seccion

    def check_circuito(self, distrito, mesa=None, seccion=None):
        circuito_nro = self.fields["circuito"].clean(self.data["circuito"])

        circuito = None
        if circuito_nro is not None and seccion is not None:
            # lo busco en la sección
            lookup = Q(seccion__distrito=distrito, seccion=seccion)
            circuito = self.fields["circuito"].get_object(circuito_nro, lookup)
            if circuito is None:
                # no lo encontré, el circuito no pertenece a la sección
                self.add_error("circuito", MENSAJES_ERROR["circuito"])
            return circuito

        # Si no tengo sección, sólo lo puedo encontrar gracias a la mesa.
        if mesa is None:
            self.add_error("circuito", MENSAJES_ERROR["circuito"])
            return None

        circuito = mesa.circuito
        if seccion and circuito.seccion != seccion:
            self.add_error("circuito", MENSAJES_ERROR["circuito"])
        else:
            return circuito

    def check_seccion_circuito(self, distrito, mesa=None):
        seccion = self.check_seccion(distrito, mesa)
        circuito = self.check_circuito(distrito, mesa, seccion)
        return (seccion, circuito)

    def clean(self):
        super().clean()
        self.cleaned_data = {}
        # agarramos los campos SIEMPRE necesarios: mesa y distrito
        mesa_nro = self.data["mesa"]
        # distrito es un SelectField y nos devuelve un distrito posta.
        distrito = self.fields["distrito"].clean(self.data["distrito"])

        intento_identificacion = True

        if not distrito:
            self.add_error("distrito", "Distrito es un dato requerido")
            intento_identificacion = False

        if not mesa_nro:
            self.add_error("mesa", "Mesa es un dato requerido")
            intento_identificacion = False

        seccion_nro = self.fields["seccion"].clean(self.data["seccion"])
        circuito_nro = self.fields["circuito"].clean(self.data["circuito"])

        # No tenemos la data necesaria, no seguimos identificando.
        if not intento_identificacion:
            return self.cleaned_data

        self.cleaned_data["distrito"] = distrito

        # Intentamos obtener la mesa con distrito y número de mesa.
        lookup_mesa = Q(circuito__seccion__distrito=distrito)

        if seccion_nro:
            lookup_mesa &= Q(circuito__seccion__numero=seccion_nro)

        if circuito_nro:
            lookup_mesa &= Q(circuito__numero__iexact=circuito_nro)

        mesa = self.buscar_mesa(mesa_nro, lookup_mesa)

        # Intentamos obtener la sección y circuito con lo que tengamos
        # a nuestra disposición (distrito, mesa o los valores del form).
        seccion, circuito = self.check_seccion_circuito(distrito, mesa)

        if seccion:
            self.cleaned_data["seccion"] = seccion
        if circuito:
            self.cleaned_data["circuito"] = circuito

        if mesa:
            if circuito and mesa.circuito != circuito:
                self.add_error("mesa", MENSAJES_ERROR["mesa"])
            else:
                self.cleaned_data["mesa"] = mesa
        else:
            self.add_error("mesa", MENSAJES_ERROR["mesa"])

        return self.cleaned_data

    def buscar_mesa(self, mesa_nro, lookup_mesa):
        """
        Esta función busca una mesa en base al input que envía el usuario
        realizando una serie de normalizaciones tendientes a encontrarla por más
        que esté escrita de formas "raras".

        La busca de forma literal, eliminándole los ceros, sacándole su parte alfanumérica,
        etc.
        """
        # Nos aseguramos de que sea texto.
        nro_mesa = str(mesa_nro).strip()
        # Primero busco como viene o sacando ceros adelante.
        query_nro_mesa = Q(numero=nro_mesa) | Q(numero=nro_mesa.lstrip("0"))
        query_nro_mesa &= lookup_mesa
        mesa = Mesa.objects.filter(query_nro_mesa)

        if not mesa.exists():
            # Separo el nro de mesa dividiéndolo por letra o caracter
            # especial para buscar la primera parte del número de mesa.
            # ejemplo:
            # 23/7 queda como ['23', '7']
            # 47B queda como ['47', 'B']
            mesa_nro_split = re.findall(r"[A-Za-z]+|\d+|^\w", nro_mesa)
            # Busco solo la parte 1 con o sin ceros
            query_nro_mesa = Q(numero=mesa_nro_split[0]) | Q(
                numero=mesa_nro_split[0].lstrip("0")
            )
            query_nro_mesa &= lookup_mesa
            mesa = Mesa.objects.filter(query_nro_mesa)
        return mesa.first()


class PreIdentificacionForm(forms.ModelForm):
    """
    Este formulario se utiliza para asignar una pre identificación a un adjunto.
    """

    class Media:
        js = ('identificacion.js',)

    distrito = SelectField(
        queryset=Distrito.objects.all(),
        help_text="Puede ingresar número o nombre",
    )

    seccion = SelectField(
        required=False,
        queryset=Seccion.objects.all(),
        label="Sección",
    )

    circuito = SelectField(
        required=False,
        queryset=Circuito.objects.all(),
    )

    class Meta:
        model = PreIdentificacion
        fields = ["distrito", "seccion", "circuito"]

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        if instance:
            kwargs["initial"]["circuito"] = circuito = circuito
            kwargs["initial"]["seccion"] = seccion = circuito.seccion
            kwargs["initial"]["distrito"] = distrito = seccion.distrito
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        circuito = cleaned_data.get("circuito")
        seccion = cleaned_data.get("seccion")
        distrito = cleaned_data.get("distrito")
        if seccion and seccion.distrito != distrito:
            self.add_error("seccion", MENSAJES_ERROR["seccion"])
        if circuito and circuito.seccion != seccion:
            self.add_error("circuito", MENSAJES_ERROR["circuito"])
        return cleaned_data


class BaseUploadForm(forms.Form):
    file_field = forms.FileField(label="Imágenes/s")

    def __init__(self, *args, **kwargs):
        es_multiple = kwargs.pop("es_multiple") if "es_multiple" in kwargs else True
        super().__init__(*args, **kwargs)
        self.fields["file_field"].widget.attrs.update({"multiple": es_multiple})

    def clean_file_field(self):
        files = self.files.getlist("file_field")
        errors = []
        for content in files:
            if content.size > settings.MAX_UPLOAD_SIZE:
                errors.append(
                    forms.ValidationError(f"Archivo {content.name} demasiado grande")
                )
        if errors:
            raise forms.ValidationError(errors)
        return files


class AgregarAttachmentsForm(BaseUploadForm):
    """
    Form para subir uno o más archivos para ser asociados a instancias de
    :py:class:`adjuntos.Attachment`

    Se le puede pasar por kwargs si el form acepta múltiples archivos o uno solo.
    """

    file_field = forms.FileField(
        label="Imagen/es",
        help_text="Imagenes o PDF",
        validators=[FileTypeValidator(allowed_types=["image/*", "application/pdf"])],
    )


class AgregarAttachmentsCSV(BaseUploadForm):
    """
    Form para subir uno o más archivos CSV.
    """

    CSV_MIMETYPES = (
        "application/csv.ms-excel",
        "application/csv.msexcel",
        "application/csv",
        "text/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/x-csv",
        "text/comma-separated-values",
        "text/x-comma-separated-values",
    )

    file_field = forms.FileField(
        label="Archivos .csv",
        validators=[FileTypeValidator(allowed_types=CSV_MIMETYPES)],
    )
