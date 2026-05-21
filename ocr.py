import time
from config import log

_ocr_available = False
_ocr_instance = None
_ocr_import_error = None

try:
    import pytesseract
    from PIL import Image
    _ocr_available = True
    log.info("OCR 引擎已加载: pytesseract")
except ImportError as exc:
    _ocr_import_error = str(exc)
    log.info("pytesseract 未安装，OCR 功能不可用 (pip install pytesseract)")


def is_available() -> bool:
    return _ocr_available


def get_error() -> str:
    return _ocr_import_error or ""


def extract_text(image) -> str:
    if not _ocr_available:
        return ""
    try:
        from PIL import Image as _PILImg
        if not isinstance(image, _PILImg.Image):
            img = _PILImg.fromarray(image)
        else:
            img = image
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip()
    except Exception as exc:
        log.warning("OCR 识别失败: %s", exc)
        return ""
