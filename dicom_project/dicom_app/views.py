import pydicom
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models, transaction, connection
from django.db.models import Q
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, CreateView, DeleteView
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
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

        from_experiment_id = self.request.GET.get('from_experiment')
        from_exp = None
        if from_experiment_id:
            try:
                from_experiment_id = int(from_experiment_id)
                user_exps = get_user_experiments(self.request.user)
                if self.object.experiment:
                    if self.object.experiment.pk == from_experiment_id:
                        from_exp = user_exps.filter(pk=from_experiment_id).first()
                else:
                    from_exp = user_exps.filter(pk=from_experiment_id).first()
            except (ValueError, TypeError):
                from_exp = None
        context['from_experiment'] = from_exp

        from_group_id = self.request.GET.get('from_group') or self.request.GET.get('group_id')
        from_group = None
        if from_group_id:
            try:
                from_group_id = int(from_group_id)
                target_experiment = self.object.experiment or context.get('from_experiment')
                if target_experiment and get_user_experiments(self.request.user).filter(pk=target_experiment.pk).exists():
                    from_group = target_experiment.groups.filter(pk=from_group_id).first()
            except (ValueError, TypeError):
                from_group = None
        context['from_group'] = from_group

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
            redirect_url = reverse('dicomfile_detail', kwargs={'pk': self.object.pk})
            query = request.GET.urlencode()
            if query:
                redirect_url = f"{redirect_url}?{query}"
            return redirect(redirect_url)
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
    template_name = 'dicom_app/dicomfile_confirm_delete.html'

    def get_queryset(self):
        return get_user_dicom_files(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from_group_id = self.request.GET.get('from_group') or self.request.POST.get('from_group')
        from_group = None
        if from_group_id and self.object.experiment:
            try:
                from_group_id = int(from_group_id)
                if get_user_experiments(self.request.user).filter(pk=self.object.experiment.pk).exists():
                    from_group = self.object.experiment.groups.filter(pk=from_group_id).first()
            except (ValueError, TypeError):
                from_group = None
        context['from_group'] = from_group

        from_experiment_id = self.request.GET.get('from_experiment') or self.request.POST.get('from_experiment')
        from_experiment = None
        if from_experiment_id:
            try:
                from_experiment_id = int(from_experiment_id)
                user_exps = get_user_experiments(self.request.user)
                if self.object.experiment:
                    if self.object.experiment.pk == from_experiment_id:
                        from_experiment = user_exps.filter(pk=from_experiment_id).first()
                else:
                    from_experiment = user_exps.filter(pk=from_experiment_id).first()
            except (ValueError, TypeError):
                from_experiment = None
        context['from_experiment'] = from_experiment
        return context

    def get_success_url(self):
        # Redirect to the participant's DICOM data page (Datos del Participante)
        if self.object.participant and self.object.experiment:
            base_url = reverse_lazy('participant_experiment_dicoms', kwargs={
                'participant_id': self.object.participant.id,
                'experiment_id': self.object.experiment.id
            })
            from_group_id = self.request.POST.get('from_group') or self.request.GET.get('from_group')
            if from_group_id:
                try:
                    from_group_id = int(from_group_id)
                    if get_user_experiments(self.request.user).filter(pk=self.object.experiment.pk).exists():
                        if self.object.experiment.groups.filter(pk=from_group_id).exists():
                            return f"{base_url}?from_group={from_group_id}"
                except (ValueError, TypeError):
                    pass

            from_exp_id = self.request.POST.get('from_experiment') or self.request.GET.get('from_experiment')
            if from_exp_id:
                try:
                    from_exp_id = int(from_exp_id)
                    if (not self.object.experiment or self.object.experiment.pk == from_exp_id) and get_user_experiments(self.request.user).filter(pk=from_exp_id).exists():
                        return f"{base_url}?from_experiment={from_exp_id}"
                except (ValueError, TypeError):
                    pass

            return str(base_url)
        elif self.object.participant:
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
        context['role_choices'] = Member.ROLE_CHOICES
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
            # 1. Clean legacy table if it exists in DB
            with connection.cursor() as cursor:
                tables = connection.introspection.table_names(cursor)
                if 'dicom_app_participant_experiments' in tables:
                    cursor.execute(
                        "DELETE FROM dicom_app_participant_experiments WHERE experiment_id = %s;",
                        [experiment.pk]
                    )

            # 2. Clean associated ConsentFiles and physical files
            for cf in list(experiment.consent_files.all()):
                if cf.file and hasattr(cf.file, 'path'):
                    try:
                        if os.path.exists(cf.file.path):
                            os.remove(cf.file.path)
                    except OSError:
                        pass
                cf.delete()

            # 3. Clean associated DicomFiles, DicomTags, and physical files
            for df in list(experiment.dicom_files.all()):
                df.tags.all().delete()
                if df.file and hasattr(df.file, 'path'):
                    try:
                        if os.path.exists(df.file.path):
                            os.remove(df.file.path)
                    except OSError:
                        pass
                df.delete()

            # 4. Clean ExperimentParticipant and ParticipantGroup
            experiment.experiment_participants.all().delete()
            experiment.groups.all().delete()

            # 5. Clear ManyToMany relations
            experiment.members.clear()
            experiment.participants.clear()

            # 6. Delete Experiment object
            experiment.delete()

            # NOTE: Participant and User objects are preserved intact.

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

    from_group_id = request.GET.get('from_group') or request.GET.get('group_id')
    from_group = None
    if from_group_id:
        try:
            from_group_id = int(from_group_id)
            from_group = experiment.groups.filter(pk=from_group_id).first()
        except (ValueError, TypeError):
            from_group = None

    return render(request, 'dicom_app/participant_experiment_dicoms.html', {
        'participant': participant,
        'experiment': experiment,
        'group': group,
        'consent_file': consent_file,
        'dicom_files': dicom_files,
        'from_experiment': from_experiment,
        'from_group': from_group,
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
        description = data.get('description', '').strip()

        if not name:
            return JsonResponse({'status': 'error', 'message': 'El nombre del grupo es obligatorio.'}, status=400)

        if ParticipantGroup.objects.filter(experiment=experiment, name__iexact=name).exists():
            return JsonResponse({
                'status': 'error',
                'message': f"Ya existe un grupo llamado '{name}' en este experimento."
            }, status=400)

        group = ParticipantGroup.objects.create(experiment=experiment, name=name, description=description)

        return JsonResponse({
            'status': 'success',
            'id': group.id,
            'name': group.name,
            'description': group.description
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

        if ExperimentParticipant.objects.filter(experiment=experiment, group=group).exists():
            return JsonResponse({
                'status': 'error',
                'message': 'No se puede eliminar el grupo porque contiene participantes asociados.'
            }, status=400)

        group.delete()

        return JsonResponse({
            'status': 'success',
            'message': 'Grupo eliminado exitosamente.',
            'group_id': group_id
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
def group_detail(request, pk, group_id):
    experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
    group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)

    experiment_participants = (
        ExperimentParticipant.objects
        .filter(experiment=experiment, group=group)
        .select_related('participant')
        .order_by('joined_at')
    )

    context = {
        'experiment': experiment,
        'group': group,
        'experiment_participants': experiment_participants,
    }
    return render(request, 'dicom_app/group_detail.html', context)

@require_POST
@login_required
def update_group_name_ajax(request, pk, group_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)
        data = json.loads(request.body)
        name = data.get('name', '').strip()

        if not name:
            return JsonResponse({'status': 'error', 'message': 'El nombre del grupo no puede estar vacío.'}, status=400)

        if ParticipantGroup.objects.filter(experiment=experiment, name__iexact=name).exclude(pk=group.pk).exists():
            return JsonResponse({
                'status': 'error',
                'message': f"Ya existe un grupo llamado '{name}' en este experimento."
            }, status=400)

        group.name = name
        group.save()

        return JsonResponse({
            'status': 'success',
            'name': group.name
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def update_group_description_ajax(request, pk, group_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)
        data = json.loads(request.body)
        description = data.get('description', '').strip()

        group.description = description
        group.save()

        return JsonResponse({
            'status': 'success',
            'description': group.description
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def get_unshared_filepaths_for_deletion(consent_qs, dicom_qs):
    """
    Identifica las rutas de archivos físicos pertenecientes a los querysets de ConsentFile
    y DicomFile dados que NO estén compartidos por ningún otro registro activo en la base de datos.
    """
    cf_ids = set(consent_qs.values_list('id', flat=True)) if consent_qs is not None else set()
    df_ids = set(dicom_qs.values_list('id', flat=True)) if dicom_qs is not None else set()

    files_to_delete = []

    if consent_qs is not None:
        for cf in consent_qs:
            if cf.file and hasattr(cf.file, 'path') and cf.file.name:
                try:
                    rel_name = cf.file.name
                    shared_cf = ConsentFile.objects.exclude(id__in=cf_ids).filter(file=rel_name).exists()
                    shared_df = DicomFile.objects.exclude(id__in=df_ids).filter(file=rel_name).exists()
                    if not shared_cf and not shared_df:
                        files_to_delete.append(cf.file.path)
                except Exception:
                    pass

    if dicom_qs is not None:
        for df in dicom_qs:
            if df.file and hasattr(df.file, 'path') and df.file.name:
                try:
                    rel_name = df.file.name
                    shared_cf = ConsentFile.objects.exclude(id__in=cf_ids).filter(file=rel_name).exists()
                    shared_df = DicomFile.objects.exclude(id__in=df_ids).filter(file=rel_name).exists()
                    if not shared_cf and not shared_df:
                        files_to_delete.append(df.file.path)
                except Exception:
                    pass

    return files_to_delete


def safely_delete_physical_files(file_paths):
    """
    Elimina físicamente los archivos especificados. Si ocurre un error de E/S,
    lanza la excepción para permitir que la transacción de base de datos se revierta.
    """
    for filepath in file_paths:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError as err:
                logger.error(f"Error borrando archivo físico {filepath}: {err}")
                raise err


@require_POST
@login_required
def remove_group_participant_ajax(request, pk, group_id, participant_id):
    try:
        experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
        group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)
        ep = get_object_or_404(ExperimentParticipant, experiment=experiment, group=group, participant_id=participant_id)
        participant = ep.participant

        consent_qs = ConsentFile.objects.filter(participant=participant, experiment=experiment)
        dicom_qs = DicomFile.objects.filter(participant=participant, experiment=experiment)

        files_to_delete = get_unshared_filepaths_for_deletion(consent_qs, dicom_qs)

        with transaction.atomic():
            consent_qs.delete()

            for df in dicom_qs:
                df.tags.all().delete()
            dicom_qs.delete()

            ep.delete()

            safely_delete_physical_files(files_to_delete)

        return JsonResponse({
            'status': 'success',
            'message': 'Participante desvinculado del grupo exitosamente.',
            'participant_id': participant_id
        })
    except Http404:
        raise
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
def add_participant_to_group(request, pk, group_id):
    experiment = get_object_or_404(get_user_experiments(request.user), pk=pk)
    group = get_object_or_404(ParticipantGroup, pk=group_id, experiment=experiment)

    if request.method == 'GET':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('action') == 'search'
        q = request.GET.get('q', '').strip()

        if is_ajax:
            user_participants = get_user_participants(request.user)
            if q:
                q_parts = q.split()
                if len(q_parts) >= 2:
                    qs = user_participants.filter(
                        (Q(first_name__icontains=q_parts[0]) & Q(last_name__icontains=q_parts[1])) |
                        (Q(first_name__icontains=q) | Q(last_name__icontains=q))
                    )
                else:
                    qs = user_participants.filter(
                        Q(first_name__icontains=q) | Q(last_name__icontains=q)
                    )
            else:
                qs = user_participants.all()

            qs = qs.order_by('first_name', 'last_name')[:50]

            participants_list = []
            for p in qs:
                ep = ExperimentParticipant.objects.filter(experiment=experiment, participant=p).first()
                if ep:
                    if ep.group_id == group.id:
                        status_code = 'in_current_group'
                        status_text = 'Ya pertenece a este grupo'
                        other_group_name = None
                    elif ep.group is None:
                        status_code = 'in_experiment_no_group'
                        status_text = 'En el experimento, sin grupo asignado'
                        other_group_name = None
                    else:
                        status_code = 'in_other_group'
                        status_text = f"Asignado al grupo '{ep.group.name}' en este experimento"
                        other_group_name = ep.group.name
                else:
                    status_code = 'not_in_experiment'
                    status_text = 'Disponible para asociar'
                    other_group_name = None

                participants_list.append({
                    'id': p.id,
                    'first_name': p.first_name,
                    'last_name': p.last_name,
                    'status_code': status_code,
                    'status_text': status_text,
                    'other_group_name': other_group_name
                })

            return JsonResponse({'status': 'success', 'participants': participants_list})

        return render(request, 'dicom_app/add_participant_group.html', {
            'experiment': experiment,
            'group': group,
            'form_data': {},
        })

    if request.method == 'POST':
        mode = request.POST.get('mode', 'create')

        if mode == 'create':
            raw_full_name = request.POST.get('full_name', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()

            if not first_name and not last_name and raw_full_name:
                parts = " ".join(raw_full_name.split()).split(' ', 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ''

            birth_date = request.POST.get('birth_date', '').strip() or None
            sex = request.POST.get('sex', '').strip() or None
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            details = request.POST.get('details', '').strip()

            if first_name:
                first_name = " ".join(first_name.split()).title()
            if last_name:
                last_name = " ".join(last_name.split()).title()

            if not first_name or not last_name:
                msg = 'El nombre y el apellido del participante son obligatorios.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)
                return render(request, 'dicom_app/add_participant_group.html', {
                    'experiment': experiment,
                    'group': group,
                    'active_tab': 'create',
                    'form_data': request.POST,
                    'error_msg': msg
                })

            existing_p = Participant.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name
            ).first()
            if existing_p:
                msg = f"Ya existe un participante registrado con el nombre '{first_name} {last_name}'. Si desea asociarlo, utilice la opción 'Agregar participante existente'."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)
                return render(request, 'dicom_app/add_participant_group.html', {
                    'experiment': experiment,
                    'group': group,
                    'active_tab': 'create',
                    'form_data': request.POST,
                    'error_msg': msg
                })

            consent_file_obj = request.FILES.get('consent_file')
            if consent_file_obj:
                if not consent_file_obj.name.lower().endswith('.pdf'):
                    msg = 'La nota de consentimiento debe ser un archivo PDF.'
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'error', 'message': msg}, status=400)
                    messages.error(request, msg)
                    return render(request, 'dicom_app/add_participant_group.html', {
                        'experiment': experiment,
                        'group': group,
                        'active_tab': 'create',
                        'form_data': request.POST,
                        'error_msg': msg
                    })
                try:
                    consent_file_obj.seek(0)
                    header = consent_file_obj.read(5)
                    consent_file_obj.seek(0)
                    if header != b'%PDF-':
                        msg = 'El archivo de consentimiento no es un PDF válido.'
                        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                            return JsonResponse({'status': 'error', 'message': msg}, status=400)
                        messages.error(request, msg)
                        return render(request, 'dicom_app/add_participant_group.html', {
                            'experiment': experiment,
                            'group': group,
                            'active_tab': 'create',
                            'form_data': request.POST,
                            'error_msg': msg
                        })
                except Exception:
                    msg = 'Error al verificar la nota de consentimiento. Asegúrese de que sea un PDF válido.'
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'error', 'message': msg}, status=400)
                    messages.error(request, msg)
                    return render(request, 'dicom_app/add_participant_group.html', {
                        'experiment': experiment,
                        'group': group,
                        'active_tab': 'create',
                        'form_data': request.POST,
                        'error_msg': msg
                    })

            dicom_files = request.FILES.getlist('dicom_files')
            if not dicom_files and request.FILES.get('dicom_file'):
                dicom_files = [request.FILES.get('dicom_file')]

            try:
                with transaction.atomic():
                    subject_id = f"SUB-{uuid.uuid4().hex[:6].upper()}"
                    participant = Participant.objects.create(
                        subject_id=subject_id,
                        first_name=first_name,
                        last_name=last_name,
                        birth_date=birth_date,
                        sex=sex,
                        email=email,
                        phone=phone,
                        details=details
                    )

                    ExperimentParticipant.objects.create(
                        experiment=experiment,
                        participant=participant,
                        group=group
                    )

                    if consent_file_obj:
                        ConsentFile.objects.create(
                            participant=participant,
                            experiment=experiment,
                            file=consent_file_obj,
                            original_filename=consent_file_obj.name,
                            file_size=consent_file_obj.size
                        )

                    processed_count = 0
                    dicom_errors = []
                    for df in dicom_files:
                        if not df.name.lower().endswith('.dcm'):
                            dicom_errors.append(f"Archivo no válido: {df.name}. Solo se permiten archivos DICOM con extensión .dcm.")
                            continue
                        try:
                            process_dicom_file(df, participant=participant, experiment=experiment)
                            processed_count += 1
                        except Exception as e:
                            dicom_errors.append(f"Error procesando {df.name}: {str(e)}")

                if dicom_errors:
                    msg = f"Participante creado. Se procesaron {processed_count} de {len(dicom_files)} archivos DICOM. Errores: {'; '.join(dicom_errors)}"
                    messages.warning(request, msg)
                else:
                    messages.success(request, f"Participante '{participant.first_name} {participant.last_name}' creado y agregado al grupo exitosamente.")

                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'status': 'success',
                        'message': 'Participante creado exitosamente.',
                        'redirect_url': reverse('group_detail', kwargs={'pk': pk, 'group_id': group_id})
                    })
                return redirect('group_detail', pk=pk, group_id=group_id)

            except Exception as e:
                logger.error(f"Error al crear participante: {e}")
                msg = f"Ocurrió un error al guardar el participante: {str(e)}"
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=500)
                messages.error(request, msg)
                return render(request, 'dicom_app/add_participant_group.html', {
                    'experiment': experiment,
                    'group': group,
                    'active_tab': 'create',
                    'form_data': request.POST,
                    'error_msg': msg
                })

        elif mode == 'existing':
            participant_id = request.POST.get('participant_id')
            confirm_move = request.POST.get('confirm_move') in ['true', '1', True]

            if not participant_id:
                msg = "Debe seleccionar un participante de la lista."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect(f"{reverse('add_participant_to_group', kwargs={'pk': pk, 'group_id': group_id})}?tab=existing")

            participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)

            ep = ExperimentParticipant.objects.filter(experiment=experiment, participant=participant).first()

            if ep:
                if ep.group_id == group.id:
                    msg = f"El participante '{participant.first_name} {participant.last_name}' ya pertenece a este grupo."
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'info', 'message': msg})
                    messages.info(request, msg)
                    return redirect('group_detail', pk=pk, group_id=group_id)
                elif ep.group is None:
                    ep.group = group
                    ep.save()
                    msg = f"Participante '{participant.first_name} {participant.last_name}' asignado al grupo '{group.name}'."
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'success', 'message': msg, 'redirect_url': reverse('group_detail', kwargs={'pk': pk, 'group_id': group_id})})
                    messages.success(request, msg)
                    return redirect('group_detail', pk=pk, group_id=group_id)
                else:
                    if not confirm_move:
                        msg = f"El participante '{participant.first_name} {participant.last_name}' ya está asignado al grupo '{ep.group.name}'. Debe confirmar para moverlo."
                        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                            return JsonResponse({
                                'status': 'confirm_required',
                                'participant_id': participant.id,
                                'participant_name': f"{participant.first_name} {participant.last_name}",
                                'old_group_name': ep.group.name,
                                'message': msg
                            })
                        messages.warning(request, msg)
                        return redirect(f"{reverse('add_participant_to_group', kwargs={'pk': pk, 'group_id': group_id})}?confirm_id={participant.id}")
                    else:
                        old_group_name = ep.group.name
                        ep.group = group
                        ep.save()
                        msg = f"Participante '{participant.first_name} {participant.last_name}' movido del grupo '{old_group_name}' al grupo '{group.name}'."
                        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                            return JsonResponse({'status': 'success', 'message': msg, 'redirect_url': reverse('group_detail', kwargs={'pk': pk, 'group_id': group_id})})
                        messages.success(request, msg)
                        return redirect('group_detail', pk=pk, group_id=group_id)
            else:
                ExperimentParticipant.objects.create(
                    experiment=experiment,
                    participant=participant,
                    group=group
                )
                msg = f"Participante '{participant.first_name} {participant.last_name}' agregado al grupo '{group.name}' exitosamente."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'success', 'message': msg, 'redirect_url': reverse('group_detail', kwargs={'pk': pk, 'group_id': group_id})})
                messages.success(request, msg)
                return redirect('group_detail', pk=pk, group_id=group_id)

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
            'birth_date': participant.birth_date.strftime('%d-%m-%Y') if participant.birth_date else None,
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

        allowed_roles = [choice[0] for choice in Member.ROLE_CHOICES]
        if role not in allowed_roles:
            return JsonResponse({'status': 'error', 'message': 'El rol seleccionado no es válido.'}, status=400)

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

        try:
            participant_ids = [int(pid) for pid in participant_ids]
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': 'ID de participante inválido.'}, status=400)

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
        member_id = data.get('member_id')
        member_ids = data.get('member_ids', [])
        if member_id and not member_ids:
            member_ids = [member_id]

        if not isinstance(member_ids, list) or not member_ids:
            return JsonResponse({'status': 'error', 'message': 'Debe seleccionar al menos un miembro.'}, status=400)

        try:
            member_ids = [int(mid) for mid in member_ids]
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': 'ID de miembro inválido.'}, status=400)

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

        consent_qs = ConsentFile.objects.filter(participant=participant, experiment=experiment)
        dicom_qs = DicomFile.objects.filter(participant=participant, experiment=experiment)

        files_to_delete = get_unshared_filepaths_for_deletion(consent_qs, dicom_qs)

        with transaction.atomic():
            consent_qs.delete()

            for df in dicom_qs:
                df.tags.all().delete()
            dicom_qs.delete()

            experiment.participants.remove(participant)

            safely_delete_physical_files(files_to_delete)

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

@require_POST
@login_required
def delete_participant(request, participant_id):
    """
    Elimina un participante del sistema cuando no tiene asociaciones activas a experimentos.
    Si el participante no pertenece a ningún experimento, elimina también sus archivos
    DICOM y notas de consentimiento asociadas (incluidos registros residuales de experimentos anteriores)
    de forma segura (tanto en BD como físicamente, comprobando que no estén compartidos).
    Conserva intactos los usuarios de Django (auth.User).
    """
    participant = get_object_or_404(get_user_participants(request.user), pk=participant_id)

    # Caso A: El participante pertenece a uno o más experimentos
    if participant.experiment_participants.exists():
        error_msg = "No se puede eliminar este participante porque todavía pertenece a uno o más experimentos. Primero debe eliminar sus asociaciones con los experimentos."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.META.get('HTTP_ACCEPT', ''):
            return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
        messages.error(request, error_msg)
        return redirect('participant_dashboard')

    # Caso B / C: El participante no tiene asociaciones en ningún experimento.
    # Se eliminan los archivos propios y residuales que correspondan, junto con sus
    # metadatos y archivos físicos (siempre que no estén compartidos por otros registros válidos).
    consent_qs = participant.consent_files.all()
    dicom_qs = participant.dicom_files.all()

    files_to_delete = get_unshared_filepaths_for_deletion(consent_qs, dicom_qs)

    try:
        with transaction.atomic():
            # 1. Eliminar ConsentFiles
            consent_qs.delete()

            # 2. Eliminar DicomTags y DicomFiles
            for df in dicom_qs:
                df.tags.all().delete()
            dicom_qs.delete()

            # 3. Eliminar registro del participante
            participant.delete()

            # 4. Eliminar archivos físicos no compartidos (revierte la transacción si falla)
            safely_delete_physical_files(files_to_delete)

    except Exception as e:
        error_msg = f"Ocurrió un error al intentar eliminar el participante: {str(e)}"
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.META.get('HTTP_ACCEPT', ''):
            return JsonResponse({'status': 'error', 'message': error_msg}, status=500)
        messages.error(request, error_msg)
        return redirect('participant_dashboard')

    success_msg = "Participante eliminado correctamente."
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.META.get('HTTP_ACCEPT', ''):
        return JsonResponse({'status': 'success', 'message': success_msg})
    messages.success(request, success_msg)
    return redirect('participant_dashboard')





