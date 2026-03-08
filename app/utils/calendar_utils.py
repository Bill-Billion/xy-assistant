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
        festivals = []
        try:
            festivals = list(lunar.getFestivals() or [])
        except Exception:  # noqa: BLE001
            festivals = []
        try:
            festivals.extend(list(lunar.getOtherFestivals() or []))
        except Exception:  # noqa: BLE001
            pass
        festival_text = ",".join([f for f in festivals if f])
        jie_qi = lunar.getJieQi()
        jie_qi_text = str(jie_qi) if jie_qi else ""
        prev_term = lunar.getPrevJieQi()
        next_term = lunar.getNextJieQi()
        solar_terms_text = ",".join(
            [t for t in [str(prev_term) if prev_term else "", str(next_term) if next_term else ""] if t]
        )
        return {
            "solar_date": solar.toFullString(),
            "lunar_date": lunar.toString(),
            "gan_zhi": f"{lunar.getYearInGanZhi()}年{lunar.getMonthInGanZhi()}月{lunar.getDayInGanZhi()}日",
            "festival": festival_text,
            "jie_qi": jie_qi_text,
            "yi": ",".join(lunar.getDayYi() or []),
            "ji": ",".join(lunar.getDayJi() or []),
            "solar_terms": solar_terms_text,
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
