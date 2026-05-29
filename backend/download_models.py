import os
import time
from huggingface_hub import snapshot_download

models_dir = os.path.join(os.getcwd(), "models", "PDF-Extract-Kit-1.0")
print(f"Downloading MinerU models to: {models_dir}")

max_retries = 10
for i in range(max_retries):
    try:
        snapshot_download(
            repo_id="opendatalab/PDF-Extract-Kit-1.0",
            local_dir=models_dir,
            local_dir_use_symlinks=False,
            resume_download=True
        )
        print("\nModel download complete!")
        break
    except Exception as e:
        print(f"Download interrupted: {e}. Retrying {i+1}/{max_retries}...")
        time.sleep(5)

import json
home_dir = os.path.expanduser("~")
config_path = os.path.join(home_dir, "magic-pdf.json")

config_data = {
    "models-dir": models_dir,
    "device-mode": "cpu",
    "layoutreader-model-dir": os.path.join(models_dir, "layoutreader")
}

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(config_data, f, indent=4)
print(f"magic-pdf.json has been configured at: {config_path}")
