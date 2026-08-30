from django.db import models
from django.contrib.auth.models import User

class Experiment(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default='Active')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='created_experiments',
        null=True,
        blank=True
    )

    def __str__(self):
        return self.name

class Participant(models.Model):
    SEX_CHOICES = (
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
    )

    subject_id = models.CharField(max_length=100, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    birth_date = models.DateField(null=True, blank=True, verbose_name="Fecha de nacimiento")
    sex = models.CharField(max_length=1, choices=SEX_CHOICES, null=True, blank=True, verbose_name="Sexo")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    details = models.TextField(blank=True)
    experiments = models.ManyToManyField(
        Experiment,
        through='ExperimentParticipant',
        related_name='participants',
        blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['first_name', 'last_name'],
                name='unique_participant_first_last_name'
            )
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class ParticipantGroup(models.Model):
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name='groups'
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['experiment', 'name'],
                name='unique_group_name_per_experiment'
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.experiment.name})"

class ExperimentParticipant(models.Model):
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name='experiment_participants'
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='experiment_participants'
    )
    group = models.ForeignKey(
        ParticipantGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='experiment_participants'
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['experiment', 'participant'],
                name='unique_participant_per_experiment'
            )
        ]

    def __str__(self):
        group_str = f" - Group: {self.group.name}" if self.group else ""
        return f"{self.participant} in {self.experiment}{group_str}"

class Member(models.Model):
    ROLE_CHOICES = [
        ('Líder Científico/a', 'Líder Científico/a'),
        ('Co-investigador/a', 'Co-investigador/a'),
        ('Investigador/a Posdoctoral', 'Investigador/a Posdoctoral'),
        ('Coordinador/a de Investigación', 'Coordinador/a de Investigación'),
        ('Coordinador/a Clínico', 'Coordinador/a Clínico'),
        ('Neurólogo/a', 'Neurólogo/a'),
        ('Técnico/a en Neuroimagen', 'Técnico/a en Neuroimagen'),
        ('Ingeniero/a Biomédico/a', 'Ingeniero/a Biomédico/a'),
        ('Especialista en Procesamiento de Imágenes', 'Especialista en Procesamiento de Imágenes'),
        ('Asistente de Investigación', 'Asistente de Investigación'),
        ('Bioestadístico/a o Científico/a de Datos', 'Bioestadístico/a o Científico/a de Datos'),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, choices=ROLE_CHOICES)
    email = models.EmailField(blank=True)
    experiments = models.ManyToManyField(Experiment, related_name='members', blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['first_name', 'last_name'],
                name='unique_member_first_last_name'
            )
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.role}"

class ConsentFile(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='consent_files')
    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name='consent_files')
    file = models.FileField(upload_to='consent_notes/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255)
    file_size = models.IntegerField()
    upload_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Consent for {self.participant} - {self.experiment} ({self.upload_date.strftime('%Y-%m-%d')})"

class DicomFile(models.Model):
    id = models.AutoField(primary_key=True)
    participant = models.ForeignKey(Participant, on_delete=models.SET_NULL, null=True, blank=True, related_name='dicom_files')
    experiment = models.ForeignKey(Experiment, on_delete=models.SET_NULL, null=True, blank=True, related_name='dicom_files')
    patient_name = models.CharField(max_length=255)
    file = models.FileField(upload_to='dicoms/raw/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    upload_date = models.DateTimeField(auto_now_add=True)
    is_anonymized = models.BooleanField(default=False)

    def __str__(self):
        return f"DICOM File for {self.patient_name} uploaded on {self.upload_date}"

class DicomTag(models.Model):
    dicom_file = models.ForeignKey(DicomFile, on_delete=models.CASCADE, related_name='tags')
    tag = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    vr = models.CharField(max_length=10)  # Value Representation
    value = models.TextField()

    def __str__(self):
        return f"{self.tag}: {self.description}"