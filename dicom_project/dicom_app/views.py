import pydicom
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import DetailView, CreateView, DeleteView
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
import os
import traceback
import shutil
import tempfile
from pathlib import Path
from dicom2nifti import convert_directory
import json
import zipfile
from .models import DicomFile, DicomTag, Experiment, Participant, ConsentFile, Member, ParticipantGroup, ExperimentParticipant
from .forms import DicomFileForm, ExperimentForm
from .utils import get_user_experiments, get_user_participants, get_user_members, get_user_dicom_files
import logging
import uuid
import numpy as np
import nibabel as nib

logger = logging.getLogger(__name__)
from .bids_utils import (
    normalize_subject_id, detect_modality, convert_dicom_to_nifti,
    create_dataset_description, create_participants_tsv, calculate_age
)

def generate_pacient_code():
    # Genera un UUID4 y toma los primeros 8 caracteres en mayúsculas
    return str(uuid.uuid4())[:8].upper()



def process_dicom_file(dicom_file_upload, participant=None, experiment=None):
    """
    Procesa un archivo DICOM: lee, anonimiza, guarda y crea registros en BD.

    Args:
        dicom_file_upload: Archivo subido desde request.FILES
        participant: Instancia de Participant (opcional)
        experiment: Instancia de Experiment (opcional)

    Returns:
        Tuple: (DicomFile instance, list of tag dictionaries)
    """
    # Leer el archivo DICOM
    ds = pydicom.dcmread(dicom_file_upload)

    # No aplicar anonimización aquí. Guardar archivo original.
    # ds = anonymize_dicom(ds)  <-- REMOVED

    # Generar código de paciente
    pacient_code = generate_pacient_code()

    # Crear directorio y nombre de archivo para RAW
    # El path debe ser relativo a MEDIA_ROOT (sin incluir 'media/')
    save_dir = Path("media/dicoms/raw/")
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{pacient_code}_{uuid.uuid4().hex[:6]}.dcm"
    full_path = save_dir / filename

    # Guardar el archivo ORIGINAL
    ds.save_as(str(full_path))

    # Path relativo a MEDIA_ROOT para Django FileField
    relative_path = f"dicoms/raw/{filename}"

    # Crear instancia DicomFile
    dicom_instance = DicomFile.objects.create(
        participant=participant,
        experiment=experiment,
        patient_name=pacient_code,
        file=relative_path,  # Usar path relativo a MEDIA_ROOT
        original_filename=dicom_file_upload.name,
        file_size=dicom_file_upload.size
    )

    # Guardar los tags en la base de datos
    dicom_data = []
    tags_to_create = []
    for element in ds:
        tag_obj = DicomTag(
            dicom_file=dicom_instance,
            tag=str(element.tag),
            description=element.description(),
            vr=element.VR,
            value=str(element.value)
        )
        tags_to_create.append(tag_obj)

        dicom_data.append({
            'tag': tag_obj.tag,
            'description': tag_obj.description,
            'vr': tag_obj.vr,
            'value': tag_obj.value,
        })

    DicomTag.objects.bulk_create(tags_to_create)

    return dicom_instance, dicom_data





class DicomFileDetailView(LoginRequiredMixin, DetailView):
    model = DicomFile
    template_name = 'dicom_app/dicomfile_detail.html'  # Plantilla corregida
    context_object_name = 'dicom_file'  # Nombre del contexto en la plantilla

    def get_queryset(self):
        return get_user_dicom_files(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add participant_id to context for the back button
        if self.object.participant:
            context['participant_id'] = self.object.participant.id

        # Optimization: Fetch all tags efficiently
        # We fetch all tags in one query to avoid N+1 issues and multiple hits
        all_tags = list(self.object.tags.all())

        # Filter and clean tags for display
        cleaned_tags = []
        binary_vrs = ["OB", "OW", "OF", "OL", "UN"]

        for tag in all_tags:
            display_value = tag.value

            # Check for binary VRs, PixelData, or excessive length
            if (tag.vr in binary_vrs or
                "PixelData" in tag.tag or
                "7FE0,0010" in tag.tag or
                len(tag.value) > 400):
                display_value = "[Valor binario omitido]"

            cleaned_tags.append({
                'tag': tag.tag,
                'description': tag.description,
                'vr': tag.vr,
                'value': display_value
            })

        # Split into initial (server-side rendered) and remaining (client-side rendered)
        initial_count = 50
        context['initial_tags'] = cleaned_tags[:initial_count]

        # Serialize remaining tags for JavaScript
        context['remaining_tags_json'] = json.dumps(cleaned_tags[initial_count:])
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = DicomFileForm(request.POST, instance=self.object)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.META.get('HTTP_ACCEPT', ''):
                return JsonResponse({
                    'status': 'success',
                    'patient_name': self.object.patient_name
                })
            return redirect('dicomfile_detail', pk=self.object.pk)
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.META.get('HTTP_ACCEPT', ''):
                return JsonResponse({
                    'status': 'error',
                    'message': 'El nombre del paciente no puede estar vacío.'
                }, status=400)
            context = self.get_context_data(object=self.object, form=form)
            return self.render_to_response(context)



class DicomFileDeleteView(LoginRequiredMixin, DeleteView):
    model = DicomFile
    template_name = 'dicomfile_confirm_delete.html'

    def get_queryset(self):
        return get_user_dicom_files(self.request.user)

    def get_success_url(self):
        # Redirect to the participant's experiments list after deletion
        if self.object.participant:
            return reverse_lazy('participant_experiments', kwargs={'participant_id': self.object.participant.id})
        return reverse_lazy('participant_dashboard')

def convert_single_dicom_to_nifti(dicom_path, output_path):
    ds = pydicom.dcmread(dicom_path)
    if "PixelData" not in ds:
        raise Exception("DICOM no contiene datos de imagen (PixelData)")

    image = ds.pixel_array
    if image.ndim < 2:
        raise Exception("La imagen es inválida o vacía.")

    affine = np.eye(4)
    nii = nib.Nifti1Image(image, affine)
    nib.save(nii, output_path)



@login_required
def export_experiment_to_bids(request, experiment_id):
    """
    Exporta todos los archivos DICOM de un experimento a formato BIDS.
    Genera una estructura BIDS completa con todos los participantes.
    """
    experiment = get_object_or_404(get_user_experiments(request.user), pk=experiment_id)

    # Crear directorio temporal para la estructura BIDS
    temp_dir = tempfile.mkdtemp()
    bids_root = Path(temp_dir) / "my_dataset"
    bids_root.mkdir(parents=True, exist_ok=True)

    try:
        # Obtener los registros ExperimentParticipant para este experimento ordenados determinísticamente por ID
        exp_participants = ExperimentParticipant.objects.filter(
            experiment=experiment
        ).select_related('participant', 'group').order_by('id')

        if not exp_participants.exists():
            return HttpResponse("No hay participantes asociados a este experimento.", status=404)

        participants_data = []

        # Procesar cada participante a través de su relación en este experimento
        for idx, ep in enumerate(exp_participants, start=1):
            participant = ep.participant

            # Normalizar ID BIDS: sub-01, sub-02...
            subject_id = normalize_subject_id(idx)

            # Grupo del participante en este experimento específico
            group_name = ep.group.name if ep.group else 'n/a'

            # Sexo del participante ('M', 'F', 'O' o 'n/a')
            sex_val = participant.sex if participant.sex in ['M', 'F', 'O'] else 'n/a'

            # Edad calculada a partir de birth_date y la fecha de creación del experimento
            age_val = calculate_age(participant.birth_date, experiment.created_at)

            participants_data.append({
                'participant_id': subject_id,
                'age': age_val,
                'sex': sex_val,
                'group': group_name
            })

            subject_dir = bids_root / subject_id

            # Obtener todos los archivos DICOM del participante en este experimento
            dicom_files = DicomFile.objects.filter(
                participant=participant,
                experiment=experiment
            )

            # Procesar cada archivo DICOM
            for dicom_file in dicom_files:
                try:
                    dicom_path = dicom_file.file.path

                    if not os.path.exists(dicom_path):
                        logger.warning(f"Archivo DICOM no encontrado: {dicom_path}")
                        continue

                    # Detectar modalidad
                    ds = pydicom.dcmread(dicom_path)
                    modality_folder, suffix = detect_modality(ds)

                    # Estructura: sub-XX/modality/
                    # Nota: BIDS a veces usa ses-XX. El usuario pidió sub-01/anat/...
                    # Si quisiéramos sesiones: sub-01/ses-01/anat/...
                    # El prompt dice: sub-01/anat/ (sin sesión explícita en el ejemplo principal,
                    # pero luego dice "sub-01/anat/"). Seguiré el ejemplo del prompt.

                    output_dir = subject_dir / modality_folder
                    output_dir.mkdir(parents=True, exist_ok=True)

                    # Logic to detect existing files and increment index
                    if modality_folder == 'func':
                        # Pattern: sub-01_task-rest_run-XX_bold
                        # We glob for *task-rest*bold.nii.gz to count existing runs
                        # Or if suffix is just 'task-rest_bold', we can split it or look for the unique part

                        # In detect_modality for func we return suffix="task-rest_bold"
                        # We want: sub-XX_task-rest_run-XX_bold

                        # Count existing .nii.gz files in this folder that match pattern
                        existing_files = list(output_dir.glob("*_bold.nii.gz"))
                        run_index = len(existing_files) + 1
                        run_entity = f"run-{run_index:02d}"

                        # Construct basename
                        # suffix is 'task-rest_bold', we want to insert run-XX
                        if "task-rest" in suffix:
                            # format: sub-XX_task-rest_run-XX_bold
                            output_basename = f"{subject_id}_task-rest_{run_entity}_bold"
                        else:
                            # fallback if suffix changes
                            output_basename = f"{subject_id}_{run_entity}_{suffix}"

                    else:
                        # For anat and dwi use 'acq'
                        # sub-XX_acq-XX_T1w or sub-XX_acq-XX_dwi

                        # Count files with same suffix
                        existing_files = list(output_dir.glob(f"*{suffix}.nii.gz"))
                        acq_index = len(existing_files) + 1
                        acq_entity = f"acq-{acq_index:02d}"

                        output_basename = f"{subject_id}_{acq_entity}_{suffix}"

                    # Convertir
                    logger.info(f"Processing DICOM {dicom_file.id} for {subject_id}/{modality_folder}")
                    nifti_path, json_path = convert_dicom_to_nifti(dicom_path, output_dir, output_basename)

                    if not nifti_path:
                        logger.warning(f"Conversion failed for DICOM {dicom_file.id}, skipping...")
                        continue

                except Exception as e:
                    logger.error(f"Error procesando archivo DICOM {dicom_file.id}: {str(e)}")
                    traceback.print_exc()
                    continue

        # Crear participants.tsv
        create_participants_tsv(bids_root, participants_data)

        # Crear dataset_description.json con metadatos del experimento
        create_dataset_description(bids_root, experiment)

        # Comprimir todo en un ZIP
        zip_path = tempfile.NamedTemporaryFile(delete=False, suffix=".zip").name
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(bids_root):
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, temp_dir) # relative to temp_dir so my_dataset is root
                    zipf.write(full_path, arcname=arcname)

        # Retornar el archivo ZIP
        experiment_name_safe = experiment.name.replace(" ", "_").lower()
        return FileResponse(
            open(zip_path, 'rb'),
            as_attachment=True,
            filename=f"{experiment_name_safe}_bids.zip"
        )

    except Exception as e:
        traceback.print_exc()
        return HttpResponse(f"Error exportando experimento: {e}", status=500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def zip_bids_folder(bids_dir):
    zip_path = bids_dir + '.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(bids_dir):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, arcname=os.path.relpath(file_path, bids_dir))
    return zip_path



@login_required
def experiment_success(request):
    """Vista de éxito después de crear un experimento"""
    return render(request, 'dicom_app/experiment_success.html')

# Experiment and Participant Views
@login_required
def dashboard(request):
    # Check if user is in 'Participante' group
    if request.user.groups.filter(name='Participante').exists():
        return redirect('participant_dashboard')

    experiments = get_user_experiments(request.user).filter(status='Active')

    # Search functionality
    query = request.GET.get('q')
    if query:
        experiments = experiments.filter(name__icontains=query)

    return render(request, 'dicom_app/dashboard.html', {'experiments': experiments})

@login_required
def participant_dashboard(request):
    participants = get_user_participants(request.user)
    query = request.GET.get('q')
    if query:
        participants = participants.filter(
            Q(subject_id__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    # Calcular la última participación para cada participante desde DICOM uploads
    participants_with_last_date = []
    for participant in participants:
        latest_dicom = DicomFile.objects.filter(participant=participant).order_by('-upload_date').first()
        participant.last_participation = latest_dicom.upload_date if latest_dicom else None
        participants_with_last_date.append(participant)

    return render(request, 'dicom_app/participant_dashboard.html', {
        'participants': participants_with_last_date
    })

class ExperimentCreateView(LoginRequiredMixin, CreateView):
    model = Experiment
    form_class = ExperimentForm
    template_name = 'dicom_app/experiment_form.html'
    success_url = reverse_lazy('experiment_success')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)

        # Debug output
        experiment = self.object
        logger.info(f"Experiment created: {experiment.name} by {experiment.created_by}")

        return response

class ExperimentDetailView(LoginRequiredMixin, DetailView):
    model = Experiment
    template_name = 'dicom_app/experiment_detail.html'
    context_object_name = 'experiment'

    def get_queryset(self):
        return get_user_experiments(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        experiment = self.object
        context['groups'] = experiment.groups.all()
        context['experiment_participants'] = (
            ExperimentParticipant.objects
            .filter(experiment=experiment)
            .select_related('participant', 'group')
            .order_by('joined_at')
        )
        context['available_participants'] = get_user_participants(self.request.user).exclude(
            id__in=experiment.participants.values_list('id', flat=True)
        )
        context['available_members'] = get_user_members(self.request.user).exclude(
            id__in=experiment.members.values_list('id', flat=True)
        )
        return context

class ExperimentDeleteView(LoginRequiredMixin, DeleteView):
    model = Experiment
    template_name = 'dicom_app/experiment_confirm_delete.html'
    success_url = reverse_lazy('dashboard')

    def get_queryset(self):
        return get_user_experiments(self.request.user)

    def form_valid(self, form):
        success_url = self.get_success_url()
        experiment = self.get_object()

        with transaction.atomic():
            associated_participants = list(experiment.participants.all())
            associated_members = list(experiment.members.all())

            orphan_participants = [
                p for p in associated_participants
                if not p.experiments.exclude(pk=experiment.pk).exists()
            ]
            orphan_members = [
                m for m in associated_members
                if not m.experiments.exclude(pk=experiment.pk).exists()
            ]

            experiment.delete()

            for p in orphan_participants:
                p.delete()

            for m in orphan_members:
                m.delete()

        return HttpResponseRedirect(success_url)

class ParticipantDetailView(LoginRequiredMixin, DetailView):
    model = Participant
    template_name = 'dicom_app/participant_detail.html'
    context_object_name = 'participant'

    def get_queryset(self):
        return get_user_participants(self.request.user)

# New views for file uploads
@login_required
def upload_consent_note(request, experiment_id, participant_id):
    """Vista para subir nota de consentimiento de un participante"""
    experiment = get_object_or_404(get_user_experiments(request.user), pk=experiment_id)
    participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)

    error_message = None
    if request.method == 'POST':
        if 'consent_file' in request.FILES:
            file = request.FILES['consent_file']

            # Validación backend: Extensión + contenido real (magic bytes %PDF-)
            is_valid_pdf = True
            if not file.name.lower().endswith('.pdf'):
                is_valid_pdf = False
                error_message = 'Formato no permitido. Solo se permiten archivos con extensión .pdf.'
            else:
                try:
                    file.seek(0)
                    header = file.read(5)
                    file.seek(0)
                    if header != b'%PDF-':
                        is_valid_pdf = False
                        error_message = 'El archivo seleccionado no es un documento PDF válido.'
                except Exception:
                    is_valid_pdf = False
                    error_message = 'Error al verificar el archivo. Asegúrese de seleccionar un PDF válido.'

            if is_valid_pdf:
                # Create ConsentFile record
                consent_file = ConsentFile.objects.create(
                    participant=participant,
                    experiment=experiment,
                    file=file,
                    original_filename=file.name,
                    file_size=file.size
                )

                return render(request, 'dicom_app/upload_success_consent.html', {
                    'experiment': experiment,
                    'participant': participant
                })
        else:
            error_message = 'Por favor seleccione un archivo PDF.'

    return render(request, 'dicom_app/upload_consent_note.html', {
        'participant': participant,
        'experiment': experiment,
        'error_message': error_message
    })

@login_required
def view_consent_note(request, participant_id, experiment_id):
    """Vista para visualizar la nota de consentimiento de un participante en un experimento"""
    participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)
    experiment = get_object_or_404(get_user_experiments(request.user), pk=experiment_id)

    # Buscar el ConsentFile más reciente para este participante y experimento
    consent_file = ConsentFile.objects.filter(
        participant=participant,
        experiment=experiment
    ).order_by('-upload_date').first()

    # Si no existe el archivo, mostrar mensaje de error
    if not consent_file or not consent_file.file:
        return HttpResponse(
            "Este participante no tiene nota de consentimiento cargada.",
            content_type="text/plain; charset=utf-8"
        )

    # Verificar que el archivo existe en el sistema de archivos
    try:
        file_path = consent_file.file.path
        if not os.path.exists(file_path):
            return HttpResponse(
                "El archivo de consentimiento no se encuentra en el servidor.",
                content_type="text/plain; charset=utf-8"
            )
    except Exception as e:
        return HttpResponse(
            f"Error al acceder al archivo: {str(e)}",
            content_type="text/plain; charset=utf-8"
        )

    # Detectar el tipo de contenido basado en la extensión del archivo
    file_extension = os.path.splitext(file_path)[1].lower()
    content_type_map = {
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
    }
    content_type = content_type_map.get(file_extension, 'application/pdf')

    # Servir el archivo directamente usando FileResponse con context manager
    try:
        file_handle = open(file_path, 'rb')
        response = FileResponse(
            file_handle,
            content_type=content_type
        )
        # Configurar para mostrar inline (en el navegador) en lugar de descargar
        filename = consent_file.original_filename or "consent_note.pdf"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
    except Exception as e:
        return HttpResponse(
            f"Error al servir el archivo: {str(e)}",
            content_type="text/plain; charset=utf-8"
        )


@login_required
def upload_participant_dicom(request, experiment_id, participant_id):
    """Vista para subir archivos DICOM de un participante"""
    experiment = get_object_or_404(get_user_experiments(request.user), pk=experiment_id)
    participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)

    if request.method == 'POST':
        if 'dicom_file' in request.FILES:
            file = request.FILES['dicom_file']

            # Usar la función helper para procesar el DICOM
            # Esto incluye: leer, anonimizar, guardar archivo, crear DicomFile y DicomTags
            dicom_instance, dicom_data = process_dicom_file(
                file,
                participant=participant,
                experiment=experiment
            )

            return render(request, 'dicom_app/upload_success_dicom.html', {
                'experiment': experiment,
                'participant': participant
            })

    return render(request, 'dicom_app/upload_dicom.html', {
        'participant': participant,
        'experiment': experiment
    })



@login_required
def participant_experiments(request, participant_id):
    """Vista para mostrar todos los experimentos de un participante"""
    participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)

    # Obtener el experimento de origen si proviene del detalle de un experimento
    from_experiment_id = request.GET.get('from_experiment')
    from_experiment = None
    if from_experiment_id:
        from_experiment = get_user_experiments(request.user).filter(pk=from_experiment_id).first()

    # Obtener todos los experimentos del participante usando la relación ManyToMany permitidos para el usuario
    experiments = get_user_experiments(request.user).filter(participants=participant).order_by('-created_at')

    # Filtrar por búsqueda si se envió el parámetro q
    query = request.GET.get('q')
    if query:
        experiments = experiments.filter(name__icontains=query)

    return render(request, 'dicom_app/participant_experiments.html', {
        'participant': participant,
        'experiments': experiments,
        'from_experiment': from_experiment,
    })

@login_required
def participant_experiment_dicoms(request, participant_id, experiment_id):
    """
    Muestra los Datos del Participante dentro del contexto de un experimento específico.
    """
    participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)
    experiment = get_object_or_404(get_user_experiments(request.user), pk=experiment_id)

    ep = ExperimentParticipant.objects.filter(experiment=experiment, participant=participant).select_related('group').first()
    if not ep and not experiment.participants.filter(pk=participant.pk).exists():
        raise Http404("El participante no pertenece a este experimento.")

    group = ep.group if ep else None

    consent_file = ConsentFile.objects.filter(
        participant=participant,
        experiment=experiment
    ).order_by('-upload_date').first()

    dicom_files = get_user_dicom_files(request.user).filter(
        participant=participant,
        experiment=experiment
    ).order_by('-upload_date')

    from_experiment_id = request.GET.get('from_experiment')
    from_experiment = None
    if from_experiment_id:
        from_experiment = get_user_experiments(request.user).filter(pk=from_experiment_id).first()

    return render(request, 'dicom_app/participant_experiment_dicoms.html', {
        'participant': participant,
        'experiment': experiment,
        'group': group,
        'consent_file': consent_file,
        'dicom_files': dicom_files,
        'from_experiment': from_experiment,
    })

@login_required
def dicom_image_view(request, dicom_id):
    """
    Vista para visualizar la imagen renderizada de un archivo DICOM.
    Retorna directamente la imagen PNG.
    """
    import io
    from PIL import Image
    from django.conf import settings

    dicom_file = get_object_or_404(get_user_dicom_files(request.user), pk=dicom_id)

    # 1. Resolución robusta de la ruta del archivo
    possible_paths = []

    # Ruta estándar de Django
    try:
        possible_paths.append(dicom_file.file.path)
    except:
        pass

    # Ruta corrigiendo posible duplicación de 'media/'
    if dicom_file.file.name.startswith('media/'):
        clean_name = dicom_file.file.name.replace('media/', '', 1)
        possible_paths.append(os.path.join(settings.MEDIA_ROOT, clean_name))

    # Ruta asumiendo que el nombre ya es relativo a MEDIA_ROOT
    possible_paths.append(os.path.join(settings.MEDIA_ROOT, dicom_file.file.name))

    # Ruta absoluta hardcodeada para debug
    try:
        fname = os.path.basename(dicom_file.file.name)
        manual_path = os.path.join(settings.MEDIA_ROOT, 'dicoms', 'raw', fname)
        possible_paths.append(manual_path)
    except:
        pass

    dicom_path = None
    for path in possible_paths:
        if os.path.exists(path):
            dicom_path = path
            break

    if not dicom_path:
        return HttpResponse("Archivo DICOM no encontrado en el servidor.", status=404)

    try:
        # 2. Leer archivo DICOM
        ds = pydicom.dcmread(dicom_path)

        # 3. Verificar PixelData
        if "PixelData" not in ds:
            # Intentar generar una imagen placeholder con texto
            img = Image.new('RGB', (400, 100), color = (255, 255, 255))
            # Aquí podríamos dibujar texto, pero por ahora retornamos error simple
            return HttpResponse("El archivo DICOM no contiene datos de imagen (PixelData).", status=400)

        # 4. Procesar imagen
        pixel_array = ds.pixel_array

        # Normalizar a 0-255
        pixel_array = pixel_array.astype(float)
        pixel_min = pixel_array.min()
        pixel_max = pixel_array.max()

        if pixel_max > pixel_min:
            pixel_array = ((pixel_array - pixel_min) / (pixel_max - pixel_min) * 255.0)

        pixel_array = pixel_array.astype(np.uint8)

        # Convertir a PIL
        if len(pixel_array.shape) == 2:
            image = Image.fromarray(pixel_array, mode='L')
        elif len(pixel_array.shape) == 3:
            # Si es RGB, asegurar orden correcto
            if pixel_array.shape[0] == 3: # Canales primero
                pixel_array = np.moveaxis(pixel_array, 0, -1)
            image = Image.fromarray(pixel_array, mode='RGB')
        else:
            return HttpResponse("Formato de dimensiones de imagen no soportado.", status=400)

        # 5. Retornar respuesta HTTP con imagen
        response = HttpResponse(content_type="image/png")
        image.save(response, "PNG")
        return response

    except Exception as e:
        traceback.print_exc()
        return HttpResponse(f"Error procesando imagen DICOM: {str(e)}", status=500)

@require_POST
@login_required
def create_group_ajax(request, pk):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        data = json.loads(request.body)
        name = data.get('name', '').strip()

        if not name:
            return JsonResponse({'status': 'error', 'message': 'El nombre del grupo es obligatorio.'}, status=400)

        if ParticipantGroup.objects.filter(experiment=experiment, name__iexact=name).exists():
            return JsonResponse({
                'status': 'error',
                'message': f"Ya existe un grupo llamado '{name}' en este experimento."
            }, status=400)

        group = ParticipantGroup.objects.create(experiment=experiment, name=name)

        return JsonResponse({
            'status': 'success',
            'id': group.id,
            'name': group.name
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
def get_group_participants_ajax(request, pk, group_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)

        eps = (
            ExperimentParticipant.objects
            .filter(experiment=experiment, group=group)
            .select_related('participant')
            .order_by('participant__first_name', 'participant__last_name')
        )

        participants = [
            {
                'id': ep.participant.id,
                'name': f"{ep.participant.first_name} {ep.participant.last_name}".strip()
            }
            for ep in eps
        ]

        return JsonResponse({
            'status': 'success',
            'group_id': group.id,
            'group_name': group.name,
            'participants': participants
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def delete_group_ajax(request, pk, group_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)

        group.delete()

        return JsonResponse({
            'status': 'success',
            'message': 'Grupo eliminado exitosamente.'
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def assign_participant_group_ajax(request, pk):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        data = json.loads(request.body)
        participant_id = data.get('participant_id')
        group_id = data.get('group_id')

        if not participant_id or not group_id:
            return JsonResponse({'status': 'error', 'message': 'Participante y grupo son obligatorios.'}, status=400)

        group = get_object_or_404(ParticipantGroup, pk=group_id)
        if group.experiment_id != experiment.id:
            return JsonResponse({'status': 'error', 'message': 'El grupo seleccionado no pertenece a este experimento.'}, status=400)

        ep = get_object_or_404(ExperimentParticipant, experiment=experiment, participant_id=participant_id)
        ep.group = group
        ep.save()

        return JsonResponse({
            'status': 'success',
            'message': 'Grupo asignado exitosamente.',
            'group_name': group.name
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def create_participant_ajax(request):
    try:
        data = json.loads(request.body)
        raw_name = data.get('full_name', '')
        experiment_id = data.get('experiment_id')
        group_id = data.get('group_id')

        # Normalizar espacios: quitar bordes y colapsar espacios internos
        clean_full_name = " ".join(raw_name.split())

        if not clean_full_name:
            return JsonResponse({'status': 'error', 'message': 'El nombre es obligatorio.'}, status=400)

        parts = clean_full_name.split(' ', 1)
        first_name = parts[0].title()
        last_name = parts[1].title() if len(parts) > 1 else ''

        existing = get_user_participants(request.user).filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name
        ).first()

        if existing:
            full_existing_name = f"{existing.first_name} {existing.last_name}".strip()
            return JsonResponse({
                'status': 'error',
                'message': f"Ya existe un participante registrado con el nombre '{full_existing_name}'."
            }, status=400)

        group = None
        experiment = None
        if experiment_id:
            experiment = get_object_or_404(get_user_experiments(request.user), pk=experiment_id)
            if not group_id:
                return JsonResponse({'status': 'error', 'message': 'Debe seleccionar un grupo obligatoriamente para asociar al experimento.'}, status=400)
            group = get_object_or_404(ParticipantGroup, pk=group_id)
            if group.experiment_id != experiment.id:
                return JsonResponse({'status': 'error', 'message': 'El grupo seleccionado no pertenece a este experimento.'}, status=400)

        subject_id = f"SUB-{uuid.uuid4().hex[:6].upper()}"

        participant = Participant.objects.create(
            subject_id=subject_id,
            first_name=first_name,
            last_name=last_name
        )

        if experiment and group:
            ExperimentParticipant.objects.create(
                experiment=experiment,
                participant=participant,
                group=group
            )

        return JsonResponse({
            'status': 'success',
            'id': participant.id,
            'value': f"{participant.first_name} {participant.last_name}".strip(),
            'group_name': group.name if group else None
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def update_participant_demographics_ajax(request, participant_id):
    try:
        participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)
        data = json.loads(request.body)

        first_name = data.get('first_name')
        last_name = data.get('last_name')

        if first_name is not None:
            first_name_clean = " ".join(str(first_name).split()).title()
            if not first_name_clean:
                return JsonResponse({'status': 'error', 'message': 'El nombre no puede estar vacío.'}, status=400)
        else:
            first_name_clean = participant.first_name

        if last_name is not None:
            last_name_clean = " ".join(str(last_name).split()).title()
        else:
            last_name_clean = participant.last_name

        duplicate = get_user_participants(request.user).filter(
            first_name__iexact=first_name_clean,
            last_name__iexact=last_name_clean
        ).exclude(pk=participant.pk).first()

        if duplicate:
            full_dup_name = f"{duplicate.first_name} {duplicate.last_name}".strip()
            return JsonResponse({
                'status': 'error',
                'message': f"Ya existe un participante registrado con el nombre '{full_dup_name}'."
            }, status=400)

        participant.first_name = first_name_clean
        participant.last_name = last_name_clean

        birth_date = data.get('birth_date')
        if birth_date is not None:
            if not birth_date or not str(birth_date).strip():
                participant.birth_date = None
            else:
                from datetime import datetime
                participant.birth_date = datetime.strptime(str(birth_date).strip(), '%Y-%m-%d').date()

        sex = data.get('sex')
        if sex is not None:
            if not sex or not str(sex).strip():
                participant.sex = None
            else:
                sex_clean = str(sex).strip().upper()
                if sex_clean not in [c[0] for c in Participant.SEX_CHOICES]:
                    return JsonResponse({'status': 'error', 'message': 'Opción de sexo inválida.'}, status=400)
                participant.sex = sex_clean

        participant.save()

        return JsonResponse({
            'status': 'success',
            'message': 'Datos del participante actualizados correctamente.',
            'first_name': participant.first_name,
            'last_name': participant.last_name,
            'birth_date': participant.birth_date.strftime('%Y-%m-%d') if participant.birth_date else None,
            'sex': participant.sex,
            'sex_display': participant.get_sex_display() if participant.sex else 'No especificado'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def create_member_ajax(request):
    try:
        data = json.loads(request.body)
        raw_name = data.get('full_name', '')
        role = data.get('role', '').strip()

        clean_full_name = " ".join(raw_name.split())

        if not clean_full_name or not role:
            return JsonResponse({'status': 'error', 'message': 'Nombre y rol son obligatorios.'}, status=400)

        parts = clean_full_name.split(' ', 1)
        first_name = parts[0].title()
        last_name = parts[1].title() if len(parts) > 1 else ''

        existing = get_user_members(request.user).filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name
        ).first()

        if existing:
            full_existing_name = f"{existing.first_name} {existing.last_name}".strip()
            return JsonResponse({
                'status': 'error',
                'message': f"Ya existe un miembro del equipo registrado con el nombre '{full_existing_name}'."
            }, status=400)

        member = Member.objects.create(
            first_name=first_name,
            last_name=last_name,
            role=role
        )

        return JsonResponse({
            'status': 'success',
            'id': member.id,
            'value': f"{member.first_name} {member.last_name}".strip() + f" - {member.role}"
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def update_experiment_description(request, pk):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        data = json.loads(request.body)
        description = data.get('description', '').strip()

        experiment.description = description
        experiment.save()

        return JsonResponse({
            'status': 'success',
            'description': experiment.description
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def update_experiment_name(request, pk):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        data = json.loads(request.body)
        name = data.get('name', '').strip()

        if not name:
            return JsonResponse({'status': 'error', 'message': 'El nombre del experimento no puede estar vacío.'}, status=400)

        experiment.name = name
        experiment.save()

        return JsonResponse({
            'status': 'success',
            'name': experiment.name
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def add_participants_to_experiment(request, pk):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        data = json.loads(request.body)

        participant_id = data.get('participant_id')
        participant_ids = data.get('participant_ids', [])
        if participant_id and not participant_ids:
            participant_ids = [participant_id]

        group_id = data.get('group_id')

        if not isinstance(participant_ids, list) or not participant_ids:
            return JsonResponse({'status': 'error', 'message': 'Debe seleccionar al menos un participante.'}, status=400)

        if not group_id:
            return JsonResponse({'status': 'error', 'message': 'Debe seleccionar un grupo obligatoriamente para este experimento.'}, status=400)

        group = get_object_or_404(ParticipantGroup, pk=group_id)
        if group.experiment_id != experiment.id:
            return JsonResponse({'status': 'error', 'message': 'El grupo seleccionado no pertenece a este experimento.'}, status=400)

        allowed_participant_ids = set(get_user_participants(request.user).values_list('id', flat=True))
        if not all(pid in allowed_participant_ids for pid in participant_ids):
            return JsonResponse({'status': 'error', 'message': 'Uno o más participantes seleccionados no están permitidos.'}, status=403)

        for pid in participant_ids:
            participant = Participant.objects.get(pk=pid)
            if ExperimentParticipant.objects.filter(experiment=experiment, participant=participant).exists():
                return JsonResponse({'status': 'error', 'message': f"El participante '{participant.first_name} {participant.last_name}' ya pertenece a este experimento."}, status=400)

            ExperimentParticipant.objects.create(
                experiment=experiment,
                participant=participant,
                group=group
            )

        return JsonResponse({
            'status': 'success',
            'message': 'Participante agregado exitosamente.'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def add_members_to_experiment(request, pk):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        data = json.loads(request.body)
        member_ids = data.get('member_ids', [])

        if not isinstance(member_ids, list) or not member_ids:
            return JsonResponse({'status': 'error', 'message': 'Debe seleccionar al menos un miembro.'}, status=400)

        # Validar alcance de miembros
        allowed_member_ids = set(get_user_members(request.user).values_list('id', flat=True))
        if not all(mid in allowed_member_ids for mid in member_ids):
            return JsonResponse({'status': 'error', 'message': 'Uno o más miembros seleccionados no están permitidos.'}, status=403)

        experiment.members.add(*member_ids)

        return JsonResponse({
            'status': 'success',
            'message': 'Miembros agregados exitosamente.'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def remove_participant_from_experiment(request, pk, participant_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        participant = get_object_or_404(Participant, pk=participant_id)

        if participant not in experiment.participants.all():
            return JsonResponse({'status': 'error', 'message': 'El participante no está asociado a este experimento.'}, status=400)

        files_to_delete = []

        with transaction.atomic():
            # 1. Consent Files
            consent_qs = ConsentFile.objects.filter(participant=participant, experiment=experiment)
            for cf in consent_qs:
                if cf.file and hasattr(cf.file, 'path'):
                    try:
                        files_to_delete.append(cf.file.path)
                    except Exception:
                        pass
            consent_qs.delete()

            # 2. DICOM Files
            dicom_qs = DicomFile.objects.filter(participant=participant, experiment=experiment)
            for df in dicom_qs:
                if df.file and hasattr(df.file, 'path'):
                    try:
                        files_to_delete.append(df.file.path)
                    except Exception:
                        pass
            dicom_qs.delete()

            # 3. Remove M2M relation
            experiment.participants.remove(participant)

            # 4. Remove participant if no remaining experiments
            if participant.experiments.count() == 0:
                participant.delete()

            # 5. Delete physical files on_commit
            def cleanup_files():
                for filepath in files_to_delete:
                    if filepath and os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception as err:
                            logger.error(f"Error borrando archivo físico {filepath}: {err}")

            transaction.on_commit(cleanup_files)

        return JsonResponse({'status': 'success', 'message': 'Participante quitado del experimento exitosamente.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def remove_member_from_experiment(request, pk, member_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        member = get_object_or_404(Member, pk=member_id)

        if member not in experiment.members.all():
            return JsonResponse({'status': 'error', 'message': 'El miembro no está asociado a este experimento.'}, status=400)

        with transaction.atomic():
            experiment.members.remove(member)
            if member.experiments.count() == 0:
                member.delete()

        return JsonResponse({'status': 'success', 'message': 'Miembro quitado del experimento exitosamente.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)




