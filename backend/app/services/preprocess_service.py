from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..schemas.inference import PreprocessSettings, Roi


def crop_roi(image: Image.Image, roi: Roi | dict | None) -> Image.Image:
    if roi is None:
        return image
    value = roi.model_dump() if hasattr(roi, "model_dump") else roi
    width, height = image.size
    left = round(value["x"] * width)
    top = round(value["y"] * height)
    right = round((value["x"] + value["width"]) * width)
    bottom = round((value["y"] + value["height"]) * height)
    return image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))


def apply(image: Image.Image, settings: PreprocessSettings | dict) -> Image.Image:
    value = settings if isinstance(settings, PreprocessSettings) else PreprocessSettings.model_validate(settings)
    result = image.convert("RGB")
    if value.grayscale:
        result = ImageOps.grayscale(result).convert("RGB")
    if value.brightness != 1.0:
        result = ImageEnhance.Brightness(result).enhance(value.brightness)
    if value.contrast != 1.0:
        result = ImageEnhance.Contrast(result).enhance(value.contrast)
    if value.clahe:
        result = ImageOps.equalize(ImageOps.grayscale(result)).convert("RGB")
    if value.sharpen:
        result = result.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=2))
    if value.binary:
        gray = ImageOps.grayscale(result)
        result = gray.point(lambda pixel: 255 if pixel >= value.threshold else 0).convert("RGB")
    if value.invert:
        result = ImageOps.invert(result)
    if value.resize:
        target_width = value.resize
        target_height = max(1, round(result.height * target_width / result.width))
        result = result.resize((target_width, target_height), Image.Resampling.LANCZOS)
    return result
