"""Cria um dataset DICOM fake para testes rápidos da UI/PDF/ZIP."""

import os
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    SecondaryCaptureImageStorage,
    generate_uid,
)

DEFAULT_STORE = Path(os.getenv("STORE_DIR", Path(__file__).parent / "storage")).resolve()


def _create_sample_image(width: int = 640, height: int = 480) -> np.ndarray:
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    xv, yv = np.meshgrid(x, y)
    gradient = ((xv + yv) / 2.0) * 255.0
    circle = ((xv - 0.5) ** 2 + (yv - 0.5) ** 2) < 0.15
    gradient[circle] = 255
    return gradient.astype(np.uint8)


def _save_preview(pixels: np.ndarray, preview_path: Path) -> None:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).convert("RGB").save(preview_path, format="PNG", optimize=True)


def _build_dataset(pixels: np.ndarray) -> FileDataset:
    now = datetime.now()
    study_uid = generate_uid(prefix="1.2.826.0.1.3680043.10.511.")
    series_uid = generate_uid(prefix="1.2.826.0.1.3680043.10.511.")
    sop_uid = generate_uid(prefix="1.2.826.0.1.3680043.10.511.")

    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationGroupLength = 0
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset("fake.dcm", {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.PatientName = "Paciente^Teste"
    ds.PatientID = "LOGIQE_DEMO"
    ds.StudyDescription = "Estudo de demonstração"
    ds.StudyDate = now.strftime("%Y%m%d")
    ds.SeriesDate = now.strftime("%Y%m%d")
    ds.ContentDate = now.strftime("%Y%m%d")
    ds.StudyTime = now.strftime("%H%M%S")
    ds.SeriesTime = now.strftime("%H%M%S")
    ds.Modality = "OT"
    ds.Manufacturer = "LILI"
    ds.BodyPartExamined = "SKIN"
    ds.InstanceNumber = 1

    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()

    return ds


def main() -> None:
    pixels = _create_sample_image()
    ds = _build_dataset(pixels)

    year, month, day = ds.StudyDate[:4], ds.StudyDate[4:6], ds.StudyDate[6:8]
    study_dir = DEFAULT_STORE / year / month / day / ds.StudyInstanceUID
    series_dir = study_dir / ds.SeriesInstanceUID
    series_dir.mkdir(parents=True, exist_ok=True)

    dicom_path = series_dir / f"{ds.SOPInstanceUID}.dcm"
    ds.save_as(dicom_path, write_like_original=False)

    preview_path = series_dir / "previews" / "i00001_0001.png"
    _save_preview(ds.pixel_array, preview_path)

    print("Estudo fake criado em:")
    print(study_dir)
    print("Estudo UID:", ds.StudyInstanceUID)
    print("Série UID:", ds.SeriesInstanceUID)
    print("Instância:", dicom_path.name)


if __name__ == "__main__":
    main()
