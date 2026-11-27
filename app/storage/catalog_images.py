from contextlib import ExitStack
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile
from typing import BinaryIO

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

CATALOG_IMAGE_SIZES = (240, 800, 1600)
CATALOG_IMAGE_MIME = "image/webp"
CATALOG_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


class InvalidCatalogImageError(Exception):
    pass


@dataclass
class CatalogImageVariant:
    limit: int
    stream: BinaryIO
    size: int
    width: int
    height: int


def encode_catalog_variants(stream: BinaryIO) -> list[CatalogImageVariant]:
    variants = []
    with ExitStack() as outputs:
        try:
            stream.seek(0)
            with Image.open(stream) as source, ExitStack() as frames_to_close:
                frames = {limit: [] for limit in CATALOG_IMAGE_SIZES}
                loop = source.info.get("loop", 0)
                durations = []
                for frame in ImageSequence.Iterator(source):
                    with ImageOps.exif_transpose(frame) as oriented:
                        mode = (
                            "RGBA"
                            if ("A" in oriented.getbands() or "transparency" in oriented.info)
                            else "RGB"
                        )
                        with oriented.convert(mode) as image:
                            for limit, resized_frames in frames.items():
                                resized = frames_to_close.enter_context(image.copy())
                                resized.thumbnail((limit, limit), Image.Resampling.LANCZOS)
                                resized.info.clear()
                                resized_frames.append(resized)
                    durations.append(frame.info.get("duration", 0))

                for limit, resized_frames in frames.items():
                    output = outputs.enter_context(SpooledTemporaryFile(max_size=1024 * 1024))
                    first, *rest = resized_frames
                    options = {"format": "WEBP", "quality": 80}
                    if rest:
                        options.update(
                            save_all=True, append_images=rest, duration=durations, loop=loop
                        )
                    first.save(output, **options)
                    size = output.tell()
                    output.seek(0)
                    variants.append(CatalogImageVariant(limit, output, size, *first.size))
        except OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError:
            raise InvalidCatalogImageError from None
        outputs.pop_all()
    return variants
