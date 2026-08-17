import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_rapidocr() -> bool:
    try:
        import onnxruntime  # type: ignore
        from rapidocr import RapidOCR  # type: ignore

        print(f"onnxruntime ok: {onnxruntime.__version__}")
        print("rapidocr import ok")
        RapidOCR()
        print("rapidocr init ok")
        return True
    except Exception as exc:
        print(f"rapidocr failed: {exc}")
        return False


def check_tesseract() -> bool:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # noqa: F401

        version = pytesseract.get_tesseract_version()
        print(f"tesseract ok: {version}")
        return True
    except Exception as exc:
        print(f"tesseract failed: {exc}")
        return False


if __name__ == "__main__":
    rapidocr_ok = check_rapidocr()
    tesseract_ok = check_tesseract()
    if not rapidocr_ok and not tesseract_ok:
        raise SystemExit(1)
