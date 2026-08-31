import io
import json
import zipfile
import datetime
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
import numpy as np
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant, DicomFile, Member
)
from dicom_app.bids_utils import calculate_age

def get_zip_bytes(response):
    if hasattr(response, 'streaming_content'):
        return b''.join(response.streaming_content)
    return response.content

def create_mock_dicom_file(patient_name="TEST"):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.PatientName = patient_name
    ds.PatientID = "12345"
    ds.Modality = "MR"
    ds.SeriesDescription = "T1w MPRAGE"

    ds.Rows = 32
    ds.Columns = 32
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    arr = np.zeros((32, 32), dtype=np.uint16)
    ds.PixelData = arr.tobytes()

    bio = io.BytesIO()
    pydicom.dcmwrite(bio, ds, write_like_original=False)
    return bio.getvalue()

class BIDSExportTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='bids_user', first_name='Juan', last_name='Docent', password='password123')
        self.client.force_login(self.user)

        self.exp1 = Experiment.objects.create(
            name="Estudio BIDS Alfa",
            description="Alfa",
            created_by=self.user
        )
        self.exp1.created_at = datetime.datetime(2026, 8, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.exp1.save()

        self.group_control = ParticipantGroup.objects.create(experiment=self.exp1, name="Control")
        self.group_exper = ParticipantGroup.objects.create(experiment=self.exp1, name="Experimental")

    def test_01_participant_id_format(self):
        """1. participant_id mantiene formato sub-01, sub-02, etc."""
        p1 = Participant.objects.create(subject_id="SUBJ-BIDS-1", first_name="Ana", last_name="Perez")
        p2 = Participant.objects.create(subject_id="SUBJ-BIDS-2", first_name="Bruno", last_name="Diaz")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p1)
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p2)

        url = reverse('export_experiment_to_bids', args=[self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            content = z.read("my_dataset/participants.tsv").decode('utf-8')
            self.assertIn("sub-01", content)
            self.assertIn("sub-02", content)

    def test_02_group_exports_participant_group_name(self):
        """2. group exporta correctamente el nombre del ParticipantGroup."""
        p1 = Participant.objects.create(subject_id="SUBJ-BIDS-G1", first_name="Carlos", last_name="Ruiz")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p1, group=self.group_control)

        url = reverse('export_experiment_to_bids', args=[self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            content = z.read("my_dataset/participants.tsv").decode('utf-8')
            self.assertIn("Control", content)

    def test_03_04_05_06_sex_export_mappings(self):
        """3, 4, 5, 6. M, F, O y None se exportan como M, F, O y n/a respectivamente."""
        p_m = Participant.objects.create(subject_id="SUBJ-M", first_name="Mario", last_name="Bros", sex='M')
        p_f = Participant.objects.create(subject_id="SUBJ-F", first_name="Fiona", last_name="Apple", sex='F')
        p_o = Participant.objects.create(subject_id="SUBJ-O", first_name="Alex", last_name="Other", sex='O')
        p_none = Participant.objects.create(subject_id="SUBJ-NONE", first_name="Sin", last_name="Sexo", sex=None)

        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p_m)
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p_f)
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p_o)
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p_none)

        url = reverse('export_experiment_to_bids', args=[self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            content = z.read("my_dataset/participants.tsv").decode('utf-8')
            lines = content.strip().split("\n")

            self.assertIn("\tM\t", lines[1])
            self.assertIn("\tF\t", lines[2])
            self.assertIn("\tO\t", lines[3])
            self.assertIn("\tn/a\t", lines[4])

    def test_07_08_birth_date_age_calculation(self):
        """7 & 8. birth_date válida calcula edad; birth_date None produce age = n/a."""
        p_valid = Participant.objects.create(
            subject_id="SUBJ-VALID-AGE",
            first_name="Pedro",
            last_name="Alvarez",
            birth_date=datetime.date(1998, 8, 10)
        )
        p_no_age = Participant.objects.create(
            subject_id="SUBJ-NO-AGE",
            first_name="Pablo",
            last_name="Marmol",
            birth_date=None
        )
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p_valid)
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p_no_age)

        url = reverse('export_experiment_to_bids', args=[self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            content = z.read("my_dataset/participants.tsv").decode('utf-8')
            lines = content.strip().split("\n")
            self.assertTrue(lines[1].startswith("sub-01\t28\t"))
            self.assertTrue(lines[2].startswith("sub-02\tn/a\t"))

    def test_09_group_none_produces_na(self):
        """9. group None produce group = n/a."""
        p = Participant.objects.create(subject_id="SUBJ-NO-GRP", first_name="No", last_name="Group")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p, group=None)

        url = reverse('export_experiment_to_bids', args=[self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            content = z.read("my_dataset/participants.tsv").decode('utf-8')
            self.assertIn("sub-01\tn/a\tn/a\tn/a", content)

    def test_10_same_participant_different_experiments_different_groups(self):
        """10. Un mismo participante en dos experimentos diferentes utiliza el grupo de cada experimento."""
        exp2 = Experiment.objects.create(name="Estudio BIDS Beta", created_by=self.user)
        group_exp2 = ParticipantGroup.objects.create(experiment=exp2, name="Placebo")

        p = Participant.objects.create(subject_id="SUBJ-MULTI", first_name="Maria", last_name="Sol")

        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p, group=self.group_control)
        ExperimentParticipant.objects.create(experiment=exp2, participant=p, group=group_exp2)

        res1 = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res1))) as z1:
            tsv1 = z1.read("my_dataset/participants.tsv").decode('utf-8')
            self.assertIn("Control", tsv1)
            self.assertNotIn("Placebo", tsv1)

        res2 = self.client.get(reverse('export_experiment_to_bids', args=[exp2.pk]))
        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res2))) as z2:
            tsv2 = z2.read("my_dataset/participants.tsv").decode('utf-8')
            self.assertIn("Placebo", tsv2)
            self.assertNotIn("Control", tsv2)

    def test_11_birthday_boundary_calculation(self):
        """11. Verificar correctamente el límite de cumpleaños."""
        ref_date = datetime.date(2026, 8, 30)

        bdate_past = datetime.date(1998, 8, 10)
        self.assertEqual(calculate_age(bdate_past, ref_date), '28')

        bdate_same = datetime.date(1998, 8, 30)
        self.assertEqual(calculate_age(bdate_same, ref_date), '28')

        bdate_future = datetime.date(1998, 12, 10)
        self.assertEqual(calculate_age(bdate_future, ref_date), '27')

    def test_12_multiple_dicom_files_per_participant_converted_and_exported(self):
        """12. Si un participante tiene 2 o más archivos DICOM, todos se convierten y aparecen en la exportación BIDS."""
        p1 = Participant.objects.create(subject_id="SUBJ-DCM-1", first_name="Juan", last_name="Perez", birth_date=datetime.date(1990, 1, 1), sex='M')
        p2 = Participant.objects.create(subject_id="SUBJ-DCM-2", first_name="Ana", last_name="Lopez")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p1, group=self.group_control)
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p2, group=self.group_exper)

        # Attach 2 DICOM files to p1
        dcm_data1 = create_mock_dicom_file("Juan 1")
        df1 = DicomFile.objects.create(participant=p1, experiment=self.exp1, patient_name="Juan 1")
        df1.file.save("test1.dcm", ContentFile(dcm_data1))

        dcm_data2 = create_mock_dicom_file("Juan 2")
        df2 = DicomFile.objects.create(participant=p1, experiment=self.exp1, patient_name="Juan 2")
        df2.file.save("test2.dcm", ContentFile(dcm_data2))

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            namelist = z.namelist()

            # Verify root BIDS files
            self.assertIn("my_dataset/participants.tsv", namelist)
            self.assertIn("my_dataset/dataset_description.json", namelist)

            # Verify DICOM converted NIfTI & JSON files for p1
            self.assertIn("my_dataset/sub-01/anat/sub-01_acq-01_T1w.nii.gz", namelist)
            self.assertIn("my_dataset/sub-01/anat/sub-01_acq-01_T1w.json", namelist)
            self.assertIn("my_dataset/sub-01/anat/sub-01_acq-02_T1w.nii.gz", namelist)
            self.assertIn("my_dataset/sub-01/anat/sub-01_acq-02_T1w.json", namelist)

            # Verify participants.tsv content
            tsv_content = z.read("my_dataset/participants.tsv").decode('utf-8')
            lines = tsv_content.strip().split("\n")
            self.assertIn("sub-01\t36\tM\tControl", lines[1])
            self.assertIn("sub-02\tn/a\tn/a\tExperimental", lines[2])

    def test_13_dataset_description_fields(self):
        """13. dataset_description.json usa el nombre real del experimento, BIDSVersion 1.8.0, DatasetType raw y GeneratedBy DICOM-HUB."""
        p = Participant.objects.create(subject_id="SUBJ-DESC-1", first_name="Laura", last_name="Rios")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p)

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            desc_bytes = z.read("my_dataset/dataset_description.json")
            desc = json.loads(desc_bytes.decode('utf-8'))

            self.assertEqual(desc["Name"], "Estudio BIDS Alfa")
            self.assertEqual(desc["BIDSVersion"], "1.8.0")
            self.assertEqual(desc["DatasetType"], "raw")
            self.assertEqual(desc["License"], "CC-BY-4.0")
            self.assertEqual(desc["GeneratedBy"], [
                {
                    "Name": "DICOM-HUB",
                    "Description": "Exportación automática de datos DICOM al estándar BIDS"
                }
            ])

    def test_14_dataset_description_authors_from_members(self):
        """14. Authors utiliza la lista de miembros reales del experimento (Member) cuando existen."""
        m1 = Member.objects.create(first_name="Dr. Roberto", last_name="Gomez", role="Líder Científico/a")
        m2 = Member.objects.create(first_name="Dra. Lucia", last_name="Mendez", role="Co-investigador/a")
        m1.experiments.add(self.exp1)
        m2.experiments.add(self.exp1)

        p = Participant.objects.create(subject_id="SUBJ-DESC-2", first_name="Sofia", last_name="Perez")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p)

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            desc = json.loads(z.read("my_dataset/dataset_description.json").decode('utf-8'))
            self.assertIn("Dr. Roberto Gomez", desc["Authors"])
            self.assertIn("Dra. Lucia Mendez", desc["Authors"])

    def test_15_dataset_description_authors_fallback_to_creator(self):
        """15. Authors utiliza el usuario creador del experimento si no hay miembros (Member) asociados."""
        p = Participant.objects.create(subject_id="SUBJ-DESC-3", first_name="Mateo", last_name="Torres")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p)

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            desc = json.loads(z.read("my_dataset/dataset_description.json").decode('utf-8'))
            self.assertIn("Juan Docent", desc["Authors"])

    def test_16_bids_json_sidecar_technical_metadata_and_conversions(self):
        """16. El JSON sidecar incluye metadatos técnicos DICOM, convierte ms a s, y excluye datos identificativos."""
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage
        file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
        file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

        ds = Dataset()
        ds.file_meta = file_meta
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

        # Identifying tags (MUST BE EXCLUDED IN JSON SIDECAR)
        ds.PatientName = "SECRET PATIENT"
        ds.PatientID = "12345678"
        ds.PatientBirthDate = "19900101"
        ds.PatientSex = "M"
        ds.InstitutionName = "SECRET HOSPITAL"

        # Technical MRI metadata
        ds.Modality = "MR"
        ds.SeriesDescription = "T1w MPRAGE"
        ds.Manufacturer = "SIEMENS"
        ds.ManufacturerModelName = "Prisma"
        ds.MagneticFieldStrength = "3.0"
        ds.SoftwareVersions = "syngo MR D13D"
        ds.ProtocolName = "localizer"
        ds.SequenceName = "*fl2d1"
        ds.MRAcquisitionType = "2D"
        ds.FlipAngle = "20"
        ds.ScanningSequence = "GR"
        ds.SequenceVariant = "SP"
        ds.RepetitionTime = "8.6"   # ms -> convert to 0.0086 s
        ds.EchoTime = "4.0"         # ms -> convert to 0.004 s
        ds.PixelSpacing = ["0.5", "0.5"]
        ds.SliceThickness = "7.0"

        # Pixel data for valid image
        ds.Rows = 32
        ds.Columns = 32
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        arr = np.zeros((32, 32), dtype=np.uint16)
        ds.PixelData = arr.tobytes()

        bio = io.BytesIO()
        pydicom.dcmwrite(bio, ds, write_like_original=False)

        p = Participant.objects.create(subject_id="SUBJ-META-1", first_name="Hugo", last_name="Boss")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p)

        df = DicomFile.objects.create(participant=p, experiment=self.exp1, patient_name="SECRET PATIENT")
        df.file.save("test_meta.dcm", ContentFile(bio.getvalue()))

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            sidecar_bytes = z.read("my_dataset/sub-01/anat/sub-01_acq-01_T1w.json")
            sidecar = json.loads(sidecar_bytes.decode('utf-8'))

            # Check technical metadata
            self.assertEqual(sidecar.get("Manufacturer"), "SIEMENS")
            self.assertEqual(sidecar.get("ManufacturersModelName"), "Prisma")
            self.assertEqual(sidecar.get("MagneticFieldStrength"), 3.0)
            self.assertEqual(sidecar.get("SoftwareVersions"), "syngo MR D13D")
            self.assertEqual(sidecar.get("ProtocolName"), "localizer")
            self.assertEqual(sidecar.get("SequenceName"), "*fl2d1")
            self.assertEqual(sidecar.get("MRAcquisitionType"), "2D")
            self.assertEqual(sidecar.get("FlipAngle"), 20.0)
            self.assertEqual(sidecar.get("ScanningSequence"), "GR")
            self.assertEqual(sidecar.get("SequenceVariant"), "SP")

            # Check unit conversions
            self.assertAlmostEqual(sidecar.get("RepetitionTime"), 0.0086, places=6)
            self.assertAlmostEqual(sidecar.get("EchoTime"), 0.004, places=6)
            self.assertEqual(sidecar.get("PixelSpacing"), [0.5, 0.5])
            self.assertEqual(sidecar.get("SliceThickness"), 7.0)

            # Ensure NO identifying patient fields present
            self.assertNotIn("PatientName", sidecar)
            self.assertNotIn("PatientID", sidecar)
            self.assertNotIn("PatientBirthDate", sidecar)
            self.assertNotIn("PatientSex", sidecar)
            self.assertNotIn("InstitutionName", sidecar)

    def test_17_bids_json_sidecar_independent_acquisitions(self):
        """17. Dos adquisiciones diferentes generan JSONs independientes con sus propios metadatos."""
        p = Participant.objects.create(subject_id="SUBJ-MULTI-ACQ", first_name="Clara", last_name="Z")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p)

        def make_dcm(tr, te, seq_name):
            file_meta = FileMetaDataset()
            file_meta.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage
            file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
            file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

            ds = Dataset()
            ds.file_meta = file_meta
            ds.is_little_endian = True
            ds.is_implicit_VR = False
            ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
            ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

            ds.Modality = "MR"
            ds.SeriesDescription = "T1w MPRAGE"
            ds.RepetitionTime = str(tr)
            ds.EchoTime = str(te)
            ds.SequenceName = seq_name

            ds.Rows = 16
            ds.Columns = 16
            ds.BitsAllocated = 16
            ds.BitsStored = 16
            ds.HighBit = 15
            ds.PixelRepresentation = 0
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.PixelData = np.zeros((16, 16), dtype=np.uint16).tobytes()

            bio = io.BytesIO()
            pydicom.dcmwrite(bio, ds, write_like_original=False)
            return bio.getvalue()

        # Acq 1: TR=8.6ms, TE=4.0ms
        df1 = DicomFile.objects.create(participant=p, experiment=self.exp1, patient_name="ACQ1")
        df1.file.save("acq1.dcm", ContentFile(make_dcm(8.6, 4.0, "seq1")))

        # Acq 2: TR=2000ms, TE=30ms
        df2 = DicomFile.objects.create(participant=p, experiment=self.exp1, patient_name="ACQ2")
        df2.file.save("acq2.dcm", ContentFile(make_dcm(2000.0, 30.0, "seq2")))

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            s1 = json.loads(z.read("my_dataset/sub-01/anat/sub-01_acq-01_T1w.json").decode('utf-8'))
            s2 = json.loads(z.read("my_dataset/sub-01/anat/sub-01_acq-02_T1w.json").decode('utf-8'))

            self.assertAlmostEqual(s1["RepetitionTime"], 0.0086, places=6)
            self.assertAlmostEqual(s1["EchoTime"], 0.004, places=6)
            self.assertEqual(s1["SequenceName"], "seq1")

            self.assertAlmostEqual(s2["RepetitionTime"], 2.0, places=6)
            self.assertAlmostEqual(s2["EchoTime"], 0.03, places=6)
            self.assertEqual(s2["SequenceName"], "seq2")

    def test_18_bids_json_sidecar_missing_metadata_handles_gracefully(self):
        """18. Metadatos ausentes no provocan error ni escriben valores inventados."""
        p = Participant.objects.create(subject_id="SUBJ-MINIMAL", first_name="Min", last_name="Imal")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=p)

        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage
        file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
        file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

        ds = Dataset()
        ds.file_meta = file_meta
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.Modality = "MR"
        ds.SeriesDescription = "T1w"

        ds.Rows = 16
        ds.Columns = 16
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = np.zeros((16, 16), dtype=np.uint16).tobytes()

        bio = io.BytesIO()
        pydicom.dcmwrite(bio, ds, write_like_original=False)

        df = DicomFile.objects.create(participant=p, experiment=self.exp1, patient_name="MINIMAL")
        df.file.save("minimal.dcm", ContentFile(bio.getvalue()))

        res = self.client.get(reverse('export_experiment_to_bids', args=[self.exp1.pk]))
        self.assertEqual(res.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(get_zip_bytes(res))) as z:
            sidecar = json.loads(z.read("my_dataset/sub-01/anat/sub-01_acq-01_T1w.json").decode('utf-8'))
            self.assertEqual(sidecar, {})  # Should be empty dict since no technical tags present

