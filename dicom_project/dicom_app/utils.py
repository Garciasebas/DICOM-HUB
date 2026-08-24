from django.db.models import Q
from .models import Experiment, Participant, Member, DicomFile

def get_user_experiments(user):
    """
    Retorna todos los experimentos si el usuario es admin/staff,
    o únicamente los experimentos creados por el usuario si es investigador.
    """
    if not user or not user.is_authenticated:
        return Experiment.objects.none()
    if user.is_superuser or user.is_staff:
        return Experiment.objects.all()
    return Experiment.objects.filter(created_by=user)

def get_user_participants(user):
    """
    Retorna todos los participantes si el usuario es admin/staff,
    o únicamente los participantes asociados a experimentos del usuario o no asignados.
    Garantiza que un investigador no vea participantes de otros investigadores.
    """
    if not user or not user.is_authenticated:
        return Participant.objects.none()
    if user.is_superuser or user.is_staff:
        return Participant.objects.all()
    return Participant.objects.filter(
        Q(experiments__created_by=user) | Q(experiments__isnull=True)
    ).distinct()

def get_user_members(user):
    """
    Retorna todos los miembros si el usuario es admin/staff,
    o únicamente los miembros asociados a experimentos del usuario o no asignados.
    Garantiza que un investigador no vea miembros de otros investigadores.
    """
    if not user or not user.is_authenticated:
        return Member.objects.none()
    if user.is_superuser or user.is_staff:
        return Member.objects.all()
    return Member.objects.filter(
        Q(experiments__created_by=user) | Q(experiments__isnull=True)
    ).distinct()

def get_user_dicom_files(user):
    """
    Retorna todos los archivos DICOM si el usuario es admin/staff,
    o únicamente los archivos DICOM pertenecientes a experimentos del usuario si es investigador.
    """
    if not user or not user.is_authenticated:
        return DicomFile.objects.none()
    if user.is_superuser or user.is_staff:
        return DicomFile.objects.all()
    return DicomFile.objects.filter(experiment__created_by=user)
