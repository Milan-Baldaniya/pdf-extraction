from __future__ import annotations

import copy
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# MinerU's bundled OCR dict files target older PP-OCRv3/v4 recognizers. The
# PDF-Extract-Kit bundle ships PP-OCRv5 `.pth` weights whose CTC head expects
# a much larger alphabet (blank + dict + space). Sync dicts from PaddleOCR's
# official HuggingFace inference configs when they are too small.
_OCR_V5_LANGUAGE_PATCHES: dict[str, dict[str, object]] = {
    "ch_lite": {
        "det": "ch_PP-OCRv5_det_infer.pth",
        "rec": "ch_PP-OCRv5_rec_infer.pth",
        "dict": "ppocrv5_dict.txt",
        "out_channels": 18385,
        "hf_repo": "PP-OCRv5_mobile_rec",
    },
    "en": {
        "det": "ch_PP-OCRv5_det_infer.pth",
        "rec": "en_PP-OCRv5_rec_infer.pth",
        "dict": "en_dict.txt",
        "out_channels": 438,
        "hf_repo": "en_PP-OCRv5_mobile_rec",
    },
    "korean": {
        "det": "Multilingual_PP-OCRv3_det_infer.pth",
        "rec": "korean_PP-OCRv5_rec_infer.pth",
        "dict": "korean_dict.txt",
        "out_channels": 11947,
        "hf_repo": "korean_PP-OCRv5_mobile_rec",
    },
    "latin": {
        "det": "ch_PP-OCRv5_det_infer.pth",
        "rec": "latin_PP-OCRv5_rec_infer.pth",
        "dict": "latin_dict.txt",
        "out_channels": 838,
        "hf_repo": "latin_PP-OCRv5_mobile_rec",
    },
    "arabic": {
        "det": "Multilingual_PP-OCRv3_det_infer.pth",
        "rec": "arabic_PP-OCRv5_rec_infer.pth",
        "dict": "arabic_dict.txt",
        "out_channels": 749,
        "hf_repo": "arabic_PP-OCRv5_mobile_rec",
    },
    "cyrillic": {
        "det": "Multilingual_PP-OCRv3_det_infer.pth",
        "rec": "cyrillic_PP-OCRv5_rec_infer.pth",
        "dict": "cyrillic_dict.txt",
        "out_channels": 852,
        "hf_repo": "cyrillic_PP-OCRv5_mobile_rec",
    },
    "devanagari": {
        "det": "Multilingual_PP-OCRv3_det_infer.pth",
        "rec": "devanagari_PP-OCRv5_rec_infer.pth",
        "dict": "devanagari_dict.txt",
        "out_channels": 570,
        "hf_repo": "devanagari_PP-OCRv5_mobile_rec",
    },
    "ta": {
        "det": "Multilingual_PP-OCRv3_det_infer.pth",
        "rec": "ta_PP-OCRv5_rec_infer.pth",
        "dict": "ta_dict.txt",
        "out_channels": 515,
        "hf_repo": "ta_PP-OCRv5_mobile_rec",
    },
    "te": {
        "det": "Multilingual_PP-OCRv3_det_infer.pth",
        "rec": "te_PP-OCRv5_rec_infer.pth",
        "dict": "te_dict.txt",
        "out_channels": 542,
        "hf_repo": "te_PP-OCRv5_mobile_rec",
    },
}

_HF_INFERENCE_URL = (
    "https://huggingface.co/PaddlePaddle/{repo}/raw/main/inference.yml"
)
# CTCLabelDecode prepends `blank` and, with MinerU defaults, appends a space.
_OCR_V5_LABEL_OVERHEAD = 2


def _count_dict_lines(dict_path: Path) -> int:
    if not dict_path.exists():
        return 0
    return len(dict_path.read_text(encoding="utf-8").splitlines())


def _expected_v5_dict_lines(out_channels: int) -> int:
    return int(out_channels) - _OCR_V5_LABEL_OVERHEAD


def _fetch_v5_character_dict(hf_repo: str) -> list[str]:
    url = _HF_INFERENCE_URL.format(repo=hf_repo)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = yaml.safe_load(response.read().decode("utf-8")) or {}
    except (OSError, urllib.error.URLError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Failed to download OCR dict from {url}: {exc}") from exc

    postprocess = payload.get("PostProcess")
    if not isinstance(postprocess, dict):
        raise RuntimeError(f"OCR dict config missing PostProcess section in {url}")

    character_dict = postprocess.get("character_dict")
    if not isinstance(character_dict, list) or not character_dict:
        raise RuntimeError(f"OCR dict config missing character_dict in {url}")

    return [str(character) for character in character_dict]


def _sync_v5_dict_file(
    *,
    dict_dir: Path,
    dict_name: str,
    out_channels: int,
    hf_repo: str,
) -> bool:
    dict_path = dict_dir / dict_name
    expected_lines = _expected_v5_dict_lines(out_channels)
    current_lines = _count_dict_lines(dict_path)
    if current_lines == expected_lines:
        return False

    logger.warning(
        "OCR dict %s has %s entries but PP-OCRv5 expects %s; syncing from %s.",
        dict_name,
        current_lines,
        expected_lines,
        hf_repo,
    )
    characters = _fetch_v5_character_dict(hf_repo)
    if len(characters) != expected_lines:
        raise RuntimeError(
            f"Downloaded OCR dict for {hf_repo} has {len(characters)} entries, "
            f"expected {expected_lines} for out_channels={out_channels}."
        )

    dict_dir.mkdir(parents=True, exist_ok=True)
    dict_path.write_text("\n".join(characters) + "\n", encoding="utf-8")
    logger.info("Updated MinerU OCR dict %s from PaddleOCR %s.", dict_name, hf_repo)
    return True


_UNIMERNET_FORWARD_PATCH_MARKER = "cache_position: Optional[torch.LongTensor] = None,"
_UNIMERNET_PAST_KV_PATCH_MARKER = "past_key_values_length = _mineru_past_key_values_length(past_key_values)"


def _patch_unimernet_transformers_compat(package_root: Path) -> bool:
    """Allow UniMerNet to run with newer transformers generation kwargs."""
    modeling_path = (
        package_root
        / "model"
        / "sub_modules"
        / "mfr"
        / "unimernet"
        / "unimernet_hf"
        / "unimer_mbart"
        / "modeling_unimer_mbart.py"
    )
    if not modeling_path.exists():
        return False

    text = modeling_path.read_text(encoding="utf-8")
    changed = False

    if _UNIMERNET_FORWARD_PATCH_MARKER not in text:
        needle = (
            "        count_gt: Optional[torch.LongTensor] = None,\n"
            "    ) -> Union[Tuple, CausalLMOutputWithCrossAttentions]:"
        )
        replacement = (
            "        count_gt: Optional[torch.LongTensor] = None,\n"
            "        cache_position: Optional[torch.LongTensor] = None,\n"
            "        **kwargs,\n"
            "    ) -> Union[Tuple, CausalLMOutputWithCrossAttentions]:"
        )
        if needle not in text:
            logger.warning("UniMerNet compatibility patch point was not found in %s", modeling_path)
            return False
        text = text.replace(needle, replacement, 1)
        changed = True

    if _UNIMERNET_PAST_KV_PATCH_MARKER not in text:
        helper = '''

def _mineru_past_key_values_length(past_key_values) -> int:
    if past_key_values is None:
        return 0
    try:
        return past_key_values[0][0].shape[2]
    except (AttributeError, IndexError, TypeError):
        get_seq_length = getattr(past_key_values, "get_seq_length", None)
        if callable(get_seq_length):
            return int(get_seq_length())
        return 0

'''
        old_line = (
            "        past_key_values_length = past_key_values[0][0].shape[2] "
            "if past_key_values is not None else 0"
        )
        if old_line not in text:
            logger.warning("UniMerNet past_key_values patch point was not found in %s", modeling_path)
            return False
        if "def _mineru_past_key_values_length" not in text:
            text = text.replace(
                "class UnimerMBartDecoderWrapper(UnimerMBartPreTrainedModel):",
                helper + "class UnimerMBartDecoderWrapper(UnimerMBartPreTrainedModel):",
                1,
            )
        text = text.replace(
            old_line,
            "        past_key_values_length = _mineru_past_key_values_length(past_key_values)",
            1,
        )
        changed = True

    if not changed:
        return True

    modeling_path.write_text(text, encoding="utf-8")
    logger.info("Patched UniMerNet for transformers cache/cache_position compatibility.")
    return True


def ensure_mineru_ocr_resource_compat(
    *,
    formula_enabled: bool = False,
    table_enabled: bool = True,
) -> dict[str, bool]:
    """Patch MinerU OCR resource YAMLs to match the locally installed v5 OCR weights.

    Some magic-pdf/MinerU builds ship OCR resource mappings that still point
    Devanagari and several other languages to older v3/v4 recognizer configs,
    while the downloaded PDF-Extract-Kit model bundle only contains v5 `.pth`
    checkpoints. That mismatch causes `BaseModel.load_state_dict()` failures.
    """
    config_path = Path.home() / "magic-pdf.json"
    if not config_path.exists():
        return {
            "formula_enabled": False,
            "table_enabled": bool(table_enabled),
        }

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read magic-pdf config from %s: %s", config_path, exc)
        return {
            "formula_enabled": False,
            "table_enabled": bool(table_enabled),
        }

    models_dir_raw = config.get("models-dir")
    if not isinstance(models_dir_raw, str) or not models_dir_raw.strip():
        return {
            "formula_enabled": False,
            "table_enabled": bool(table_enabled),
        }

    models_dir = Path(models_dir_raw)
    ocr_models_dir = models_dir / "OCR" / "paddleocr_torch"
    if not ocr_models_dir.exists():
        return {
            "formula_enabled": False,
            "table_enabled": bool(table_enabled),
        }

    effective_formula_enabled = False
    package_root: Path | None = None
    try:
        import magic_pdf  # type: ignore

        package_root = Path(magic_pdf.__file__).resolve().parent
        if formula_enabled:
            logger.warning(
                "MinerU formula parsing remains disabled in CPU mode because the "
                "bundled UniMerNet model is incompatible with transformers %s. "
                "Text, table, and layout extraction are unaffected.",
                __import__("transformers").__version__,
            )
    except Exception as exc:
        logger.warning("Unable to import magic_pdf for MinerU compatibility patch: %s", exc)

    desired_runtime_config = {
        "models-dir": str(models_dir),
        "device-mode": str(config.get("device-mode") or "cpu"),
        "layoutreader-model-dir": str(
            Path(
                config.get("layoutreader-model-dir")
                or models_dir / "ReadingOrder" / "layout_reader"
            )
        ),
        "layout-config": {
            "model": "doclayout_yolo",
        },
        "ocr-config": {
            "model": "paddle",
        },
        "formula-config": {
            "mfd_model": "yolo_v8_mfd",
            "mfr_model": "unimernet_small",
            "enable": effective_formula_enabled,
        },
        "table-config": {
            "model": "rapid_table",
            "enable": bool(table_enabled),
            "max_time": 400,
        },
    }
    if any(config.get(key) != value for key, value in desired_runtime_config.items()):
        config.update(desired_runtime_config)
        config_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
        logger.info("Patched magic-pdf.json runtime config for local MinerU execution.")

    if package_root is None:
        return {
            "formula_enabled": effective_formula_enabled,
            "table_enabled": bool(table_enabled),
        }

    resources_dir = (
        package_root
        / "model"
        / "sub_modules"
        / "ocr"
        / "paddleocr2pytorch"
        / "pytorchocr"
        / "utils"
        / "resources"
    )
    models_config_path = resources_dir / "models_config.yml"
    arch_config_path = resources_dir / "arch_config.yaml"

    if not models_config_path.exists() or not arch_config_path.exists():
        return {
            "formula_enabled": effective_formula_enabled,
            "table_enabled": bool(table_enabled),
        }

    try:
        models_config = yaml.safe_load(models_config_path.read_text(encoding="utf-8")) or {}
        arch_config = yaml.safe_load(arch_config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        logger.warning("Failed to read MinerU OCR resource files: %s", exc)
        return {
            "formula_enabled": effective_formula_enabled,
            "table_enabled": bool(table_enabled),
        }

    lang_map = models_config.setdefault("lang", {})
    v5_template = arch_config.get("ch_PP-OCRv5_rec_infer")
    if not isinstance(v5_template, dict):
        logger.warning("MinerU OCR v5 template was not found in arch_config.yaml")
        return {
            "formula_enabled": effective_formula_enabled,
            "table_enabled": bool(table_enabled),
        }

    models_changed = False
    arch_changed = False
    dict_changed = False
    dict_dir = resources_dir / "dict"

    for language, patch in _OCR_V5_LANGUAGE_PATCHES.items():
        rec_name = str(patch["rec"])
        if not (ocr_models_dir / rec_name).exists():
            continue

        desired_entry = {
            "det": str(patch["det"]),
            "rec": rec_name,
            "dict": str(patch["dict"]),
        }
        if lang_map.get(language) != desired_entry:
            lang_map[language] = desired_entry
            models_changed = True

        arch_key = Path(rec_name).stem
        desired_arch = copy.deepcopy(v5_template)
        desired_arch["Head"]["out_channels_list"]["CTCLabelDecode"] = int(
            patch["out_channels"]
        )
        if arch_config.get(arch_key) != desired_arch:
            arch_config[arch_key] = desired_arch
            arch_changed = True

        hf_repo = patch.get("hf_repo")
        if isinstance(hf_repo, str) and hf_repo:
            try:
                if _sync_v5_dict_file(
                    dict_dir=dict_dir,
                    dict_name=str(patch["dict"]),
                    out_channels=int(patch["out_channels"]),
                    hf_repo=hf_repo,
                ):
                    dict_changed = True
            except RuntimeError as exc:
                logger.error(
                    "Failed to sync OCR dict for %s (%s): %s",
                    language,
                    patch["dict"],
                    exc,
                )

    if models_changed:
        models_config_path.write_text(
            yaml.safe_dump(models_config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("Patched MinerU OCR models_config.yml for local v5 checkpoints.")

    if arch_changed:
        arch_config_path.write_text(
            yaml.safe_dump(arch_config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("Patched MinerU OCR arch_config.yaml for local v5 checkpoints.")

    if dict_changed:
        logger.info("Patched MinerU OCR character dictionaries for PP-OCRv5.")

    return {
        "formula_enabled": effective_formula_enabled,
        "table_enabled": bool(table_enabled),
    }
