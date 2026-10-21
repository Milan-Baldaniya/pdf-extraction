import json
import os
import time
from pathlib import Path

from huggingface_hub import snapshot_download

backend_dir = Path(__file__).resolve().parent
models_dir = backend_dir / "models" / "PDF-Extract-Kit-1.0"
layoutreader_dir = models_dir / "models" / "ReadingOrder" / "layout_reader"

# This snapshot contains the v3/v4 OCR weights required by magic-pdf 1.3.3,
# plus the bundled reading-order model. Later snapshots remove those OCR
# weights and replace them with incompatible v5 recognizers.
model_revision = "966ef6d0780a1b54937d759b337a1aaafb11f259"
model_patterns = [
    "models/Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt",
    "models/MFD/YOLO/yolo_v8_ft.pt",
    "models/MFR/unimernet_hf_small_2503/*",
    "models/OCR/paddleocr_torch/*.pth",
    "models/ReadingOrder/layout_reader/*",
]

print(f"Downloading MinerU models to: {models_dir}")

max_retries = 10
for i in range(max_retries):
    try:
        snapshot_download(
            repo_id="opendatalab/PDF-Extract-Kit-1.0",
            revision=model_revision,
            local_dir=str(models_dir),
            allow_patterns=model_patterns,
            ignore_patterns=["*PP-OCRv5*"],
            max_workers=4,
        )
        print("\nModel download complete!")
        break
    except Exception as e:
        if i == max_retries - 1:
            raise RuntimeError("MinerU model download failed; rerun to resume.") from e
        print(f"Download interrupted: {e}. Retrying {i + 1}/{max_retries}...")
        time.sleep(5)

if not layoutreader_dir.exists():
    raise FileNotFoundError(
        f"Expected MinerU reading-order model folder was not found: {layoutreader_dir}"
    )

home_dir = Path(os.path.expanduser("~"))
config_path = home_dir / "magic-pdf.json"

config_data = {
    "models-dir": str(models_dir / "models"),
    "device-mode": "cpu",
    "layoutreader-model-dir": str(layoutreader_dir),
    "layout-config": {
        "model": "doclayout_yolo",
    },
    "ocr-config": {
        "model": "paddle",
    },
    "formula-config": {
        "mfd_model": "yolo_v8_mfd",
        "mfr_model": "unimernet_small",
        "enable": False,
    },
    "table-config": {
        "model": "rapid_table",
        "enable": True,
        "max_time": 400,
    },
}

with config_path.open("w", encoding="utf-8") as f:
    json.dump(config_data, f, indent=4)

print(f"magic-pdf.json has been configured at: {config_path}")
