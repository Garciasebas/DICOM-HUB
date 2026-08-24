from django import forms
from .models import DicomFile, DicomTag, Experiment, Participant, Member
from .utils import get_user_participants, get_user_members

class ExperimentForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        queryset=Participant.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select-multiple'}),
        required=True,
        error_messages={'required': 'Debe seleccionar al menos un participante.'},
        label='Participantes'
    )
    members = forms.ModelMultipleChoiceField(
        queryset=Member.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select-multiple'}),
        required=True,
        error_messages={'required': 'Debe seleccionar al menos un miembro del equipo.'},
        label='Miembros del Equipo'
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['participants'].queryset = get_user_participants(user)
            self.fields['members'].queryset = get_user_members(user)
        else:
            self.fields['participants'].queryset = Participant.objects.all()
            self.fields['members'].queryset = Member.objects.all()
    
    class Meta:
        model = Experiment
        fields = ['name', 'description']
        labels = {
            'name': 'Nombre del Experimento',
            'description': 'Descripción',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del Experimento'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control experiment-description',
                'placeholder': 'Escriba una descripción del experimento...',
                'rows': 1,
                'maxlength': '300',
                'id': 'id_description'
            }),
        }
        error_messages = {
            'name': {
                'required': 'El nombre del experimento es obligatorio.',
            },
            'description': {
                'required': 'La descripción del experimento es obligatoria.',
            }
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        if not name or not name.strip():
            raise forms.ValidationError("El nombre del experimento es obligatorio.")
        return name.strip()

    def clean_description(self):
        description = self.cleaned_data.get('description', '')
        if not description or not description.strip():
            raise forms.ValidationError("La descripción del experimento es obligatoria.")
        if len(description) > 300:
            raise forms.ValidationError("La descripción del experimento no puede superar los 300 caracteres.")
        return description.strip()

    def clean_participants(self):
        participants = self.cleaned_data.get('participants')
        if not participants or participants.count() == 0:
            raise forms.ValidationError("Debe seleccionar al menos un participante.")
        return participants

    def clean_members(self):
        members = self.cleaned_data.get('members')
        if not members or members.count() == 0:
            raise forms.ValidationError("Debe seleccionar al menos un miembro del equipo.")
        return members

    def save(self, commit=True):
        experiment = super().save(commit=commit)
        if commit:
            experiment.participants.set(self.cleaned_data['participants'])
            experiment.members.set(self.cleaned_data['members'])
        return experiment

class DicomFileForm(forms.ModelForm):
    class Meta:
        model = DicomFile
        fields = ['patient_name']


class ConsentNoteForm(forms.Form):
    consent_file = forms.FileField(label='Seleccionar archivo')

    def clean_consent_file(self):
        file = self.cleaned_data.get('consent_file')
        if file:
            if not file.name.lower().endswith('.pdf'):
                raise forms.ValidationError('Solo se permiten archivos PDF.')
            try:
                file.seek(0)
                header = file.read(5)
                file.seek(0)
                if header != b'%PDF-':
                    raise forms.ValidationError('El archivo seleccionado no es un documento PDF válido.')
            except Exception:
                raise forms.ValidationError('Error al procesar el archivo. Asegúrese de que sea un PDF válido.')
        return file