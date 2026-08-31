import os
import json
import shutil
import tempfile
import pydicom
import dicom2nifti
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def normalize_subject_id(index):
    """
    Generates a BIDS-compliant subject ID: sub-01, sub-02, etc.
    """
    return f"sub-{index:02d}"

def detect_modality(ds):
    """
    Detects the modality of a DICOM dataset.
    Returns: (modality_folder, suffix)
    e.g., ('anat', 'T1w'), ('func', 'task-rest_bold'), ('dwi', 'dwi')
    """
    # Default to anat/T1w if unknown
    modality_folder = "anat"
    suffix = "T1w"

    try:
        series_desc = ds.get("SeriesDescription", "").lower()
        image_type = str(ds.get("ImageType", "")).lower()
        modality = ds.get("Modality", "").upper()

        if modality == "MR":
            if "diff" in series_desc or "dwi" in series_desc or "dti" in series_desc:
                modality_folder = "dwi"
                suffix = "dwi"
            elif "bold" in series_desc or "func" in series_desc or "fmri" in series_desc or "rest" in series_desc:
                modality_folder = "func"
                suffix = "task-rest_bold"
            elif "t1" in series_desc or "mprage" in series_desc:
                modality_folder = "anat"
                suffix = "T1w"
            elif "t2" in series_desc:
                modality_folder = "anat"
                suffix = "T2w"
            elif "flair" in series_desc:
                modality_folder = "anat"
                suffix = "FLAIR"
    except Exception as e:
        logger.error(f"Error detecting modality: {e}")

    return modality_folder, suffix

def anonymize_dicom(ds):
    """
    Anonymizes a DICOM dataset in place.
    """
    sensitive_tags = [
        "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
        "InstitutionName", "ReferringPhysicianName", "StudyInstanceUID",
        "SeriesInstanceUID", "AccessionNumber"
    ]

    for tag in sensitive_tags:
        if tag in ds:
            ds.data_element(tag).value = ""

    # Generate new UIDs to ensure anonymity while keeping relationship if needed (though here we just random)
    # For strict BIDS within a session, we might want to keep consistency, but for now random is safer for anonymization.
    ds.StudyInstanceUID = pydicom.uid.generate_uid()
    ds.SeriesInstanceUID = pydicom.uid.generate_uid()
    ds.SOPInstanceUID = pydicom.uid.generate_uid()

    def person_names_callback(ds, elem):
        if elem.VR == "PN":
            elem.value = "anonymous"

    ds.walk(person_names_callback)

    try:
        ds.remove_private_tags()
    except:
        pass

    return ds

def extract_bids_metadata(ds):
    """
    Extracts authorized BIDS technical metadata from a DICOM dataset.
    Returns a controlled, predictable dictionary without patient identifying fields.
    """
    metadata = {}
    if ds is None:
        return metadata

    # 1. Manufacturer
    if "Manufacturer" in ds and ds.Manufacturer:
        metadata["Manufacturer"] = str(ds.Manufacturer).strip()

    # 2. ManufacturersModelName
    if "ManufacturerModelName" in ds and ds.ManufacturerModelName:
        metadata["ManufacturersModelName"] = str(ds.ManufacturerModelName).strip()

    # 3. MagneticFieldStrength (float)
    if "MagneticFieldStrength" in ds and ds.MagneticFieldStrength != "":
        try:
            metadata["MagneticFieldStrength"] = float(ds.MagneticFieldStrength)
        except (ValueError, TypeError):
            pass

    # 4. SoftwareVersions (string or list of strings)
    if "SoftwareVersions" in ds and ds.SoftwareVersions:
        val = ds.SoftwareVersions
        if isinstance(val, (list, tuple, pydicom.multival.MultiValue)):
            metadata["SoftwareVersions"] = [str(v).strip() for v in val if str(v).strip()]
        else:
            metadata["SoftwareVersions"] = str(val).strip()

    # 5. ProtocolName
    if "ProtocolName" in ds and ds.ProtocolName:
        metadata["ProtocolName"] = str(ds.ProtocolName).strip()

    # 6. SequenceName
    if "SequenceName" in ds and ds.SequenceName:
        metadata["SequenceName"] = str(ds.SequenceName).strip()

    # 7. MRAcquisitionType
    if "MRAcquisitionType" in ds and ds.MRAcquisitionType:
        metadata["MRAcquisitionType"] = str(ds.MRAcquisitionType).strip()

    # 8. FlipAngle (float)
    if "FlipAngle" in ds and ds.FlipAngle != "":
        try:
            metadata["FlipAngle"] = float(ds.FlipAngle)
        except (ValueError, TypeError):
            pass

    # 9. ScanningSequence (string or list)
    if "ScanningSequence" in ds and ds.ScanningSequence:
        val = ds.ScanningSequence
        if isinstance(val, (list, tuple, pydicom.multival.MultiValue)):
            metadata["ScanningSequence"] = [str(v).strip() for v in val if str(v).strip()]
        else:
            metadata["ScanningSequence"] = str(val).strip()

    # 10. SequenceVariant (string or list)
    if "SequenceVariant" in ds and ds.SequenceVariant:
        val = ds.SequenceVariant
        if isinstance(val, (list, tuple, pydicom.multival.MultiValue)):
            metadata["SequenceVariant"] = [str(v).strip() for v in val if str(v).strip()]
        else:
            metadata["SequenceVariant"] = str(val).strip()

    # 11. RepetitionTime (convert from ms to seconds: float(TR) / 1000.0)
    if "RepetitionTime" in ds and ds.RepetitionTime != "":
        try:
            metadata["RepetitionTime"] = float(ds.RepetitionTime) / 1000.0
        except (ValueError, TypeError):
            pass

    # 12. EchoTime (convert from ms to seconds: float(TE) / 1000.0)
    if "EchoTime" in ds and ds.EchoTime != "":
        try:
            metadata["EchoTime"] = float(ds.EchoTime) / 1000.0
        except (ValueError, TypeError):
            pass

    # 13. PixelSpacing ([float, float])
    if "PixelSpacing" in ds and ds.PixelSpacing:
        try:
            metadata["PixelSpacing"] = [float(x) for x in ds.PixelSpacing]
        except (ValueError, TypeError):
            pass

    # 14. SliceThickness (float)
    if "SliceThickness" in ds and ds.SliceThickness != "":
        try:
            metadata["SliceThickness"] = float(ds.SliceThickness)
        except (ValueError, TypeError):
            pass

    return metadata

def convert_dicom_to_nifti(dicom_path, output_dir, output_basename):
    """
    Converts a single DICOM file (or series) to NIfTI.
    
    Args:
        dicom_path: Path to the original DICOM file.
        output_dir: Pathlib Path to the output directory (e.g., .../sub-01/anat).
        output_basename: Base name for the output file (e.g., sub-01_T1w).
        
    Returns:
        Tuple of (nifti_path, json_path) or (None, None) if failed.
    """
    temp_convert_dir = tempfile.mkdtemp()
    temp_dicom_dir = tempfile.mkdtemp()
    
    generated_nifti = None
    generated_json = None
    
    try:
        # 1. Read Original DICOM & Extract BIDS Technical Metadata BEFORE Anonymization
        raw_ds = pydicom.dcmread(dicom_path)
        bids_metadata = extract_bids_metadata(raw_ds)

        # 2. Anonymize dataset for conversion
        ds = anonymize_dicom(raw_ds)
        
        # 3. Save anonymized dataset to temp directory
        temp_dicom_path = os.path.join(temp_dicom_dir, 'image.dcm')
        ds.save_as(temp_dicom_path)
        
        # 4. Try Convert using dicom2nifti first
        logger.info(f"Converting {dicom_path} to NIfTI...")
        try:
            dicom2nifti.convert_directory(temp_dicom_dir, temp_convert_dir, compression=True, reorient=True)
        except Exception as e:
            logger.warning(f"dicom2nifti failed: {e}, trying fallback method...")
        
        # 5. Find generated files
        nifti_files = list(Path(temp_convert_dir).glob("*.nii.gz"))
        
        if nifti_files:
            # Move NIfTI file
            source_nifti = nifti_files[0]
            dest_nifti = output_dir / f"{output_basename}.nii.gz"
            shutil.move(str(source_nifti), str(dest_nifti))
            generated_nifti = dest_nifti
            logger.info(f"Generated NIfTI: {dest_nifti}")
            
            # Write controlled BIDS JSON sidecar
            dest_json = output_dir / f"{output_basename}.json"
            with open(dest_json, 'w', encoding='utf-8') as f:
                json.dump(bids_metadata, f, indent=4, ensure_ascii=False)
            generated_json = dest_json
            
            logger.info(f"Generated JSON: {generated_json}")
        else:
            # Fallback: Use nibabel for single-slice DICOMs
            logger.warning(f"dicom2nifti produced no output, using fallback conversion...")
            dest_nifti = output_dir / f"{output_basename}.nii.gz"
            
            import numpy as np
            import nibabel as nib
            
            if "PixelData" in ds:
                image = ds.pixel_array
                if image.ndim >= 2:
                    affine = np.eye(4)
                    nii = nib.Nifti1Image(image, affine)
                    nib.save(nii, str(dest_nifti))
                    generated_nifti = dest_nifti
                    logger.info(f"Fallback conversion successful: {dest_nifti}")
                    
                    # Write controlled BIDS JSON sidecar
                    dest_json = output_dir / f"{output_basename}.json"
                    with open(dest_json, 'w', encoding='utf-8') as f:
                        json.dump(bids_metadata, f, indent=4, ensure_ascii=False)
                    generated_json = dest_json
                else:
                    logger.error(f"Image has invalid dimensions: {image.ndim}")
            else:
                logger.error(f"DICOM has no PixelData")
            
    except Exception as e:
        logger.error(f"Conversion error for {dicom_path}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        shutil.rmtree(temp_convert_dir, ignore_errors=True)
        shutil.rmtree(temp_dicom_dir, ignore_errors=True)
        
    return generated_nifti, generated_json

def calculate_age(birth_date, ref_date):
    """
    Calculates age in years between birth_date and ref_date.
    Returns 'n/a' if birth_date or ref_date is None or if age is negative.
    """
    if not birth_date or not ref_date:
        return 'n/a'

    if hasattr(ref_date, 'date'):
        ref_date = ref_date.date()

    if hasattr(birth_date, 'date'):
        birth_date = birth_date.date()

    age = ref_date.year - birth_date.year
    if (ref_date.month, ref_date.day) < (birth_date.month, birth_date.day):
        age -= 1

    return str(age) if age >= 0 else 'n/a'

def create_dataset_description(base_dir, experiment=None):
    """
    Creates dataset_description.json using metadata from the experiment.
    """
    name = experiment.name if (experiment and experiment.name) else "My Dataset"

    authors = []
    if experiment:
        # 1. Obtener miembros/investigadores del experimento (Member)
        members = list(experiment.members.all()) if hasattr(experiment, 'members') else []
        if members:
            for m in members:
                full_name = f"{m.first_name} {m.last_name}".strip()
                if full_name and full_name not in authors:
                    authors.append(full_name)

        # 2. Si no hay miembros asociados, usar el usuario creador del experimento
        if not authors and hasattr(experiment, 'created_by') and experiment.created_by:
            creator_name = experiment.created_by.get_full_name().strip() or experiment.created_by.username
            if creator_name and creator_name not in authors:
                authors.append(creator_name)

    if not authors:
        authors = ["DICOM HUB User"]

    # Licencia por defecto "CC-BY-4.0" (para mantener compatibilidad BIDS).
    # NOTA: La licencia podrá configurarse si en futuras fases se añade un campo de licencia a Experiment.
    data = {
        "Name": name,
        "BIDSVersion": "1.8.0",
        "DatasetType": "raw",
        "Authors": authors,
        "GeneratedBy": [
            {
                "Name": "DICOM-HUB",
                "Description": "Exportación automática de datos DICOM al estándar BIDS"
            }
        ],
        "License": "CC-BY-4.0"
    }
    with open(base_dir / "dataset_description.json", 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def create_participants_tsv(base_dir, participants_data):
    """
    Creates participants.tsv
    participants_data: list of dicts with 'participant_id', 'age', 'sex', 'group'
    """
    tsv_path = base_dir / "participants.tsv"
    with open(tsv_path, 'w', encoding='utf-8') as f:
        f.write("participant_id\tage\tsex\tgroup\n")
        for p in participants_data:
            age_val = p.get('age') if p.get('age') is not None else 'n/a'
            sex_val = p.get('sex') if p.get('sex') is not None else 'n/a'
            group_val = p.get('group') if p.get('group') is not None else 'n/a'
            f.write(f"{p['participant_id']}\t{age_val}\t{sex_val}\t{group_val}\n")
