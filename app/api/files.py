import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.schemas.request import MAX_REQUEST_FILE_SIZE as MAX_REQUEST_FILE_SIZE

Image.MAX_IMAGE_PIXELS = None

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_REQUEST_FILES = 3
MAX_REQUEST_NOTE_FILES = 5
IMAGE_TYPES = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class InvalidFileError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


@dataclass
class CheckedFile:
    stream: BinaryIO
    original_name: str
    mime_type: str
    size: int
    width: int | None = None
    height: int | None = None


def inspect_file(
    file: BinaryIO, name: str, images_only: bool
) -> tuple[str, int | None, int | None]:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in IMAGE_TYPES:
        try:
            with Image.open(file) as image:
                if image.format != IMAGE_TYPES[suffix]:
                    raise InvalidFileError
                width, height = image.size
                image.verify()
                return IMAGE_MIMES[image.format], width, height
        except OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError:
            raise InvalidFileError from None
    if images_only:
        raise InvalidFileError
    file.seek(0)
    prefix = file.read(1024)
    if suffix == ".pdf" and prefix.startswith(b"%PDF-"):
        return "application/pdf", None, None
    if suffix == ".dwg" and re.match(rb"^AC10[0-9]{2}", prefix):
        return "application/acad", None, None
    if suffix == ".dxf" and (
        prefix.startswith(b"AutoCAD Binary DXF\r\n\x1a\0")
        or re.match(rb"\s*0\s*\r?\n\s*SECTION\s*\r?\n", prefix)
    ):
        return "application/dxf", None, None
    if suffix == ".docx":
        try:
            file.seek(0)
            with zipfile.ZipFile(file) as archive:
                if {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                    return (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        None,
                        None,
                    )
        except OSError, zipfile.BadZipFile:
            pass
    raise InvalidFileError


async def check_file(
    upload: UploadFile, *, images_only: bool, max_size: int = MAX_FILE_SIZE
) -> CheckedFile:
    name = PurePosixPath((upload.filename or "").replace("\\", "/")).name
    if not name or len(name) > 255 or any(ord(char) < 32 for char in name):
        raise InvalidFileError
    stream = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    size = 0
    try:
        while chunk := await upload.read(64 * 1024):
            size += len(chunk)
            if size > max_size:
                raise FileTooLargeError
            stream.write(chunk)
        if size == 0:
            raise InvalidFileError
        stream.seek(0)
        mime_type, width, height = await run_in_threadpool(inspect_file, stream, name, images_only)
        stream.seek(0)
        return CheckedFile(stream, name, mime_type, size, width, height)
    except BaseException:
        stream.close()
        raise
