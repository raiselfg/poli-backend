from io import BytesIO

import pytest
from PIL import Image
from starlette.datastructures import UploadFile

from app.api.files import CheckedFile, check_file, optimize_catalog_image


def make_checked(data: bytes, filename: str, mime_type: str) -> CheckedFile:
    return CheckedFile(BytesIO(data), filename, mime_type, len(data))


def test_optimization_resizes_rotated_jpeg_and_removes_metadata():
    source = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Photographer"
    Image.new("RGB", (3200, 1600), "red").save(
        source, format="JPEG", exif=exif, icc_profile=b"test profile"
    )
    checked = make_checked(source.getvalue(), "photo.jpg", "image/jpeg")
    original_stream = checked.stream

    optimize_catalog_image(checked)

    assert original_stream.closed
    assert checked.original_name == "photo.jpg"
    assert checked.mime_type == "image/webp"
    assert (checked.width, checked.height) == (800, 1600)
    output = checked.stream.read()
    assert len(output) == checked.size
    with Image.open(BytesIO(output)) as image:
        assert image.format == "WEBP"
        assert image.size == (800, 1600)
        assert not image.getexif()
        assert "icc_profile" not in image.info
        assert "xmp" not in image.info
    checked.stream.close()


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_optimization_preserves_small_image_and_transparency(image_format):
    source = BytesIO()
    Image.new("RGBA", (12, 8), (255, 0, 0, 0)).save(source, format=image_format)
    checked = make_checked(source.getvalue(), "photo.png", "image/png")

    optimize_catalog_image(checked)

    with Image.open(checked.stream) as image:
        assert image.format == "WEBP"
        assert image.size == (12, 8)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0
    checked.stream.close()


def test_optimization_preserves_animation():
    source = BytesIO()
    first = Image.new("RGB", (10, 20), "red")
    second = Image.new("RGB", (10, 20), "blue")
    first.save(
        source, format="WEBP", save_all=True, append_images=[second], duration=[100, 200], loop=2
    )
    checked = make_checked(source.getvalue(), "animation.webp", "image/webp")

    optimize_catalog_image(checked)

    with Image.open(checked.stream) as image:
        assert image.n_frames == 2
        assert image.info["loop"] == 2
        image.load()
        assert image.info["duration"] == 100
        image.seek(1)
        image.load()
        assert image.info["duration"] == 200
        assert image.convert("RGB").getpixel((0, 0))[2] > 200
    checked.stream.close()


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
    checked = make_checked(source.getvalue(), "image.png", "image/png")

    optimize_catalog_image(checked)

    with Image.open(checked.stream) as result:
        assert result.convert("RGBA").getpixel((0, 0))[3] == 0
    checked.stream.close()
