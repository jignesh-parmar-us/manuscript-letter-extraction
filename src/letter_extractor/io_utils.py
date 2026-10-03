"""Folder scanning and image load/save (Unicode-safe, metadata preserving).

All file access goes through Pillow, never cv2.imread/imwrite: OpenCV's file functions fail on
non-ASCII Windows paths, which matters for manuscript file names.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, JpegImagePlugin

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

_FORMAT_BY_EXT = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
    ".tif": "TIFF", ".tiff": "TIFF", ".bmp": "BMP",
}


class FolderError(Exception):
    """Raised for an unusable input / output folder (reported to the user)."""


@dataclass
class ImageMeta:
    format: str = "PNG"
    dpi: Optional[Tuple[float, float]] = None
    icc_profile: Optional[bytes] = None
    exif: Optional[bytes] = None
    qtables: Optional[dict] = None
    subsampling: Optional[int] = None
    notes: List[str] = field(default_factory=list)


def natural_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def scan_folder(folder: Path) -> Tuple[List[Path], List[Path]]:
    """Return (images, ignored_files). Not recursive. Sorted naturally (page2 before page10)."""
    images, ignored = [], []
    for p in folder.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        (images if p.suffix.lower() in SUPPORTED_EXTENSIONS else ignored).append(p)
    return sorted(images, key=natural_key), sorted(ignored, key=natural_key)


def validate_folders(input_dir: Path, output_dir: Path, create_output: bool = True) -> None:
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise FolderError(f"Input folder does not exist or is not a folder: {input_dir}")
    if input_dir.resolve() == output_dir.resolve():
        raise FolderError("Input and output folder must be different (originals are never overwritten).")
    if create_output:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise FolderError(f"Cannot create output folder {output_dir}: {e}") from e
    if output_dir.exists() and not output_dir.is_dir():
        raise FolderError(f"Output path is not a folder: {output_dir}")


def load_image(path: Path) -> Tuple[np.ndarray, ImageMeta]:
    """Load an image as 8-bit RGB (H x W x 3) plus the metadata needed to save it identically."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in _FORMAT_BY_EXT:
        raise ValueError(f"Unsupported image type: {path.suffix}")
    with Image.open(path) as im:
        im.load()
        meta = ImageMeta(format=_FORMAT_BY_EXT[ext])
        dpi = im.info.get("dpi")
        if dpi:
            try:
                meta.dpi = (float(dpi[0]), float(dpi[1]))
            except (TypeError, ValueError, IndexError):
                pass
        meta.icc_profile = im.info.get("icc_profile")
        try:
            exif = im.getexif()
            if len(exif):
                meta.exif = exif.tobytes()
        except Exception:  # damaged EXIF must never block processing
            pass
        if meta.format == "JPEG":
            q = getattr(im, "quantization", None)
            if q:
                meta.qtables = {k: list(v) for k, v in q.items()}
            try:
                s = JpegImagePlugin.get_sampling(im)
                if s is not None and s >= 0:
                    meta.subsampling = s
            except Exception:
                pass
        mode = im.mode
        if mode == "RGB":
            rgb = np.asarray(im)
        elif mode in ("I;16", "I;16L", "I;16B", "I"):
            a = np.asarray(im).astype(np.float32)
            a = a / (257.0 if a.max() > 255 else 1.0)
            rgb = np.repeat(np.clip(a, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
            meta.notes.append(f"converted from {mode} to 8-bit RGB")
        else:
            rgb = np.asarray(im.convert("RGB"))
            meta.notes.append(f"converted from {mode} to RGB")
    return np.ascontiguousarray(rgb), meta


def save_image(rgb: np.ndarray, path: Path, meta: ImageMeta) -> None:
    """Save in the same format as the input, keeping DPI / ICC / EXIF and (JPEG) the original
    quantization tables and chroma subsampling so recompression loss stays minimal."""
    path = Path(path)
    im = Image.fromarray(rgb, "RGB")
    kw: dict = {}
    if meta.dpi:
        kw["dpi"] = meta.dpi
    if meta.icc_profile:
        kw["icc_profile"] = meta.icc_profile
    if meta.format == "JPEG":
        if meta.exif:
            kw["exif"] = meta.exif
        if meta.qtables:
            kw["qtables"] = meta.qtables
            if meta.subsampling is not None:
                kw["subsampling"] = meta.subsampling
        else:
            kw["quality"] = 95
        im.save(path, "JPEG", **kw)
    elif meta.format == "PNG":
        if meta.exif:
            kw["exif"] = meta.exif
        im.save(path, "PNG", **kw)
    elif meta.format == "TIFF":
        kw["compression"] = "tiff_lzw"
        im.save(path, "TIFF", **kw)
    else:
        kw.pop("icc_profile", None)
        im.save(path, "BMP", **kw)
