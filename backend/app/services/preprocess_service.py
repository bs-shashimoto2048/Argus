from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..schemas.inference import PreprocessSettings, Roi

# 前処理Previewの出力サイズの安全上限(Issue #81)。
# resizeは「横幅」指定で、縦はROIの縦横比のまま拡大する(縦 = crop高さ × resize / crop幅)。ROIが細いほど縦が爆発的に増え、
# 例えばROI幅2%(UIの最小値)×resize 4096では4096×116,413px(RGB 1.4GB)を確保し、JPEG保存に失敗(422)した後も
# 例外のtracebackが巨大画像を保持してRSSが1.5GB前後のまま残った(隔離再現で確認)。確保する前にサイズを検証して弾く。
# 総pixel数: resizeの上限(横4096、schemaのle=4096)の正方形 = 4096×4096。16:9のフレーム全体(4096×2304)や4:3(4096×3072)も収まり、
# 通常のROI・resizeでは拒否されない。拒否されるのは横幅に対して縦が極端に長いROIだけ。
MAX_PREVIEW_PIXELS = 4096 * 4096
# libjpegが扱える辺の上限(65,500)。これを超えるとJPEG保存で必ず失敗する。
MAX_PREVIEW_DIMENSION = 65500


class PreviewTooLargeError(ValueError):
    """前処理Previewの出力サイズが安全上限を超える。"""


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


def output_size(source_size: tuple[int, int], settings: PreprocessSettings | dict) -> tuple[int, int]:
    """apply()が生成する画像のサイズ(width, height)を、画像を確保せずに計算する(resizeの式はapply()と同じ)。"""
    value = settings if isinstance(settings, PreprocessSettings) else PreprocessSettings.model_validate(settings)
    width, height = source_size
    if value.resize:
        return value.resize, max(1, round(height * value.resize / width))
    return width, height


def ensure_preview_size(source_size: tuple[int, int], settings: PreprocessSettings | dict) -> tuple[int, int]:
    """出力サイズが上限内であることを、resizeを実行する前に検証する。超過ならPreviewTooLargeError。"""
    width, height = output_size(source_size, settings)
    if width * height > MAX_PREVIEW_PIXELS or max(width, height) > MAX_PREVIEW_DIMENSION:
        raise PreviewTooLargeError(
            f"前処理Previewの出力サイズ({width}x{height}px)が上限を超えます。ROIの幅を広げるか、Resize widthを小さくしてください"
            f"(上限: {MAX_PREVIEW_PIXELS // 1_000_000}百万画素、1辺{MAX_PREVIEW_DIMENSION}px)"
        )
    return width, height


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
