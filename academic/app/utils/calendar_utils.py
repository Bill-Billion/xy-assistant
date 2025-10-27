from __future__ import annotations

from datetime import datetime
from typing import Optional

from lunar_python import Solar

from app.utils.time_utils import EAST_EIGHT


def get_lunar_info(date: datetime) -> Optional[dict[str, str]]:
    """基于 lunar_python 获取农历、节气、黄历等信息。"""
    try:
        localized = date.astimezone(EAST_EIGHT)
        solar = Solar.fromYmd(localized.year, localized.month, localized.day)
        lunar = solar.getLunar()
        return {
            "solar_date": solar.toFullString(),
            "lunar_date": lunar.toString(),
            "gan_zhi": f"{lunar.getYearInGanZhi()}年{lunar.getMonthInGanZhi()}月{lunar.getDayInGanZhi()}日",
            "festival": lunar.getFestival(),
            "jie_qi": lunar.getJieQi(),
            "yi": ",".join(lunar.getDayYi() or []),
            "ji": ",".join(lunar.getDayJi() or []),
            "solar_terms": ",".join(filter(None, [lunar.getPrevJieQi(), lunar.getNextJieQi()])),
        }
    except Exception:  # noqa: BLE001
        return None


def format_lunar_summary(info: Optional[dict[str, str]]) -> Optional[str]:
    if not info:
        return None
    parts: list[str] = []
    parts.append(info.get("lunar_date", ""))
    if info.get("jie_qi"):
        parts.append(f"节气：{info['jie_qi']}")
    if info.get("festival"):
        parts.append(f"节日：{info['festival']}")
    if info.get("yi"):
        parts.append(f"宜：{info['yi']}")
    if info.get("ji"):
        parts.append(f"忌：{info['ji']}")
    return "；".join(filter(None, parts)) or None
