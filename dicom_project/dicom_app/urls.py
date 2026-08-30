from django.urls import path
from .views import (
    DicomFileDetailView,
    DicomFileDeleteView,
    export_experiment_to_bids,
    dashboard,
    participant_dashboard,
    experiment_success,
    ExperimentCreateView,
    ExperimentDetailView,
    ExperimentDeleteView,
    ParticipantDetailView,
    upload_consent_note,
    view_consent_note,
    upload_participant_dicom,
    participant_experiments,
    participant_experiment_dicoms,
    dicom_image_view,
    create_participant_ajax,
    create_member_ajax,
    update_experiment_description,
    update_experiment_name,
    add_participants_to_experiment,
    add_members_to_experiment,
    remove_participant_from_experiment,
    remove_member_from_experiment,
    create_group_ajax,
    assign_participant_group_ajax,
    get_group_participants_ajax,
    delete_group_ajax
)

from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='login', permanent=False), name='home'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', dashboard, name='dashboard'),
    path('participant-dashboard/', participant_dashboard, name='participant_dashboard'),
    path('experiment/new/', ExperimentCreateView.as_view(), name='experiment_create'),
    path('experiment/success/', experiment_success, name='experiment_success'),
    path('experiment/<int:pk>/', ExperimentDetailView.as_view(), name='experiment_detail'),
    path('experiment/<int:pk>/delete/', ExperimentDeleteView.as_view(), name='experiment_delete'),
    path('experiment/<int:experiment_id>/export_bids/', export_experiment_to_bids, name='export_experiment_to_bids'),
    path('participant/<int:pk>/', ParticipantDetailView.as_view(), name='participant_detail'),
    path('participants/', participant_dashboard, name='participant_list'),
    path('participant/<int:participant_id>/experiments/', participant_experiments, name='participant_experiments'),
    path('participant/<int:participant_id>/experiments/<int:experiment_id>/', participant_experiment_dicoms, name='participant_experiment_dicoms'),
    
    # File upload URLs
    path('experiment/<int:experiment_id>/participant/<int:participant_id>/upload-consent/', upload_consent_note, name='upload_consent_note'),
    path('participant/<int:participant_id>/experiment/<int:experiment_id>/consent-note/', view_consent_note, name='view_consent_note'),
    path('experiment/<int:experiment_id>/participant/<int:participant_id>/upload-dicom/', upload_participant_dicom, name='upload_participant_dicom'),

    path('<int:pk>/', DicomFileDetailView.as_view(), name='dicomfile_detail'),
    path('<int:dicom_id>/image/', dicom_image_view, name='dicom_image_view'),
    path('dicomfile/<int:pk>/delete/', DicomFileDeleteView.as_view(), name='dicomfile_delete'),
    
    # AJAX URLs
    path('ajax/participant/create/', create_participant_ajax, name='create_participant_ajax'),
    path('ajax/member/create/', create_member_ajax, name='create_member_ajax'),
    path('experiment/<int:pk>/update_description/', update_experiment_description, name='update_experiment_description'),
    path('experiment/<int:pk>/update_name/', update_experiment_name, name='update_experiment_name'),
    path('experiment/<int:pk>/groups/create/', create_group_ajax, name='create_group_ajax'),
    path('experiment/<int:pk>/groups/<int:group_id>/participants/', get_group_participants_ajax, name='get_group_participants_ajax'),
    path('experiment/<int:pk>/groups/<int:group_id>/delete/', delete_group_ajax, name='delete_group_ajax'),
    path('experiment/<int:pk>/assign_group/', assign_participant_group_ajax, name='assign_participant_group_ajax'),
    path('experiment/<int:pk>/add_participants/', add_participants_to_experiment, name='add_participants_to_experiment'),
    path('experiment/<int:pk>/add_members/', add_members_to_experiment, name='add_members_to_experiment'),
    path('experiment/<int:pk>/remove_participant/<int:participant_id>/', remove_participant_from_experiment, name='remove_participant_from_experiment'),
    path('experiment/<int:pk>/remove_member/<int:member_id>/', remove_member_from_experiment, name='remove_member_from_experiment'),
]

