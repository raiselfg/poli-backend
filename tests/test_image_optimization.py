from io import BytesIO

import pytest
from PIL import Image
from starlette.datastructures import UploadFile

from app.api.files import check_file
from app.storage.catalog_images import encode_catalog_variants


def test_optimization_resizes_rotated_jpeg_and_removes_metadata():
    source = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Photographer"
    Image.new("RGB", (3200, 1600), "red").save(
        source, format="JPEG", exif=exif, icc_profile=b"test profile"
    )
    variants = encode_catalog_variants(source)

    assert [variant.limit for variant in variants] == [240, 800, 1600]
    assert [(variant.width, variant.height) for variant in variants] == [
        (120, 240),
        (400, 800),
        (800, 1600),
    ]
    for variant in variants:
        with variant.stream as stream:
            output = stream.read()
            assert len(output) == variant.size
            with Image.open(BytesIO(output)) as image:
                assert image.format == "WEBP"
                assert image.size == (variant.width, variant.height)
                assert not image.getexif()
                assert "icc_profile" not in image.info
                assert "xmp" not in image.info


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_optimization_preserves_small_image_and_transparency(image_format):
    source = BytesIO()
    Image.new("RGBA", (12, 8), (255, 0, 0, 0)).save(source, format=image_format)
    for variant in encode_catalog_variants(source):
        with variant.stream as stream, Image.open(stream) as image:
            assert image.format == "WEBP"
            assert image.size == (12, 8)
            assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_optimization_preserves_animation():
    source = BytesIO()
    first = Image.new("RGB", (10, 20), "red")
    second = Image.new("RGB", (10, 20), "blue")
    first.save(
        source, format="WEBP", save_all=True, append_images=[second], duration=[100, 200], loop=2
    )
    for variant in encode_catalog_variants(source):
        with variant.stream as stream, Image.open(stream) as image:
            assert image.n_frames == 2
            assert image.info["loop"] == 2
            image.load()
            assert image.info["duration"] == 100
            image.seek(1)
            image.load()
            assert image.info["duration"] == 200
            assert image.convert("RGB").getpixel((0, 0))[2] > 200


async def test_request_attachment_is_not_optimized():
    source = BytesIO()
    Image.new("RGB", (10, 20), "red").save(source, format="PNG")
    contents = source.getvalue()
    upload = UploadFile(filename="drawing.png", file=BytesIO(contents))

    checked = await check_file(upload, images_only=False)

    assert checked.mime_type == "image/png"
    assert checked.stream.read() == contents
    checked.stream.close()
    await upload.close()


def test_optimization_preserves_palette_transparency():
    source = BytesIO()
    image = Image.new("P", (10, 10), 0)
    image.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    image.save(source, format="PNG", transparency=0)
    for variant in encode_catalog_variants(source):
        with variant.stream as stream, Image.open(stream) as result:
            assert result.convert("RGBA").getpixel((0, 0))[3] == 0
