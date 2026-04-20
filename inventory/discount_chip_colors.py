from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import transaction

from .models import DiscountChipSetting

DEFAULT_DISCOUNT_CHIP_PALETTE: tuple[str, ...] = (
    "#1E88E5",
    "#43A047",
    "#FB8C00",
    "#8E24AA",
    "#E53935",
    "#00897B",
    "#5E35B1",
    "#3949AB",
    "#6D4C41",
    "#039BE5",
    "#7CB342",
    "#F4511E",
    "#546E7A",
    "#C2185B",
    "#FDD835",
)
DEFAULT_NEUTRAL_DISCOUNT_COLOR = "#9E9E9E"


@dataclass(frozen=True)
class ResolvedDiscountChip:
    label: str
    color: str


def _normalize_discount_key(discount_code: str | None) -> str:
    if not discount_code:
        return ""
    return str(discount_code).strip().casefold()


def _normalize_palette(values: Iterable[str]) -> list[str]:
    palette: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if not candidate:
            continue
        if not candidate.startswith("#"):
            candidate = f"#{candidate}"
        palette.append(candidate.upper())
    return palette


def _get_or_create_discount_chip_setting() -> DiscountChipSetting:
    setting = DiscountChipSetting.objects.order_by("id").first()
    if setting:
        return setting
    return DiscountChipSetting.objects.create()


def _ensure_discount_color_mapping(discount_keys: Iterable[str]) -> dict[str, str]:
    normalized_keys = sorted({key for key in discount_keys if key})
    if not normalized_keys:
        return {}

    with transaction.atomic():
        setting = _get_or_create_discount_chip_setting()
        palette = _normalize_palette(setting.palette or DEFAULT_DISCOUNT_CHIP_PALETTE)
        if not palette:
            palette = list(DEFAULT_DISCOUNT_CHIP_PALETTE)

        mapping = {
            _normalize_discount_key(key): str(value).upper()
            for key, value in (setting.discount_color_map or {}).items()
            if _normalize_discount_key(key)
        }
        used_colors = {color for color in mapping.values() if color}

        changed = False
        for key in normalized_keys:
            if key in mapping:
                continue
            available_color = next((color for color in palette if color not in used_colors), None)
            mapping[key] = available_color or DEFAULT_NEUTRAL_DISCOUNT_COLOR
            if available_color:
                used_colors.add(available_color)
            changed = True

        if changed:
            setting.discount_color_map = mapping
            setting.save(update_fields=["discount_color_map", "updated_at"])

        return mapping


def resolve_discount_chip_colors(discounts: Iterable) -> list[ResolvedDiscountChip]:
    """Resolve stable chip colors for discount objects.

    Colors are keyed by discount code and persisted in `DiscountChipSetting`.
    """

    normalized: list[tuple[str, str]] = []
    seen_labels: set[str] = set()

    for discount in discounts:
        label = str(getattr(discount, "name", "") or "").strip()
        if not label:
            continue
        normalized_label = label.casefold()
        if normalized_label in seen_labels:
            continue
        seen_labels.add(normalized_label)

        discount_code = getattr(discount, "code", "")
        normalized.append((label, _normalize_discount_key(discount_code)))

    mapping = _ensure_discount_color_mapping(key for _label, key in normalized)

    chips: list[ResolvedDiscountChip] = []
    for label, key in normalized:
        color = mapping.get(key) if key else None
        chips.append(ResolvedDiscountChip(label=label, color=color or DEFAULT_NEUTRAL_DISCOUNT_COLOR))
    return chips
