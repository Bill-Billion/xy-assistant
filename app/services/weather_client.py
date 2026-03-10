from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from loguru import logger


class WeatherAPIError(RuntimeError):
    """Raised when the upstream天气接口返回错误。"""


@dataclass(slots=True)
class WeatherClientConfig:
    app_code: str
    base_url: str
    timeout: float = 5.0
    verify_ssl: bool = False


class WeatherClient:
    """封装阿里云天气接口的 HTTP 访问。"""

    def __init__(self, config: WeatherClientConfig) -> None:
        self._config = config
        if not self._config.app_code:
            raise ValueError("WeatherClient requires a valid APP Code")

    async def get_forecast(
        self,
        latitude: float,
        longitude: float,
        need_more_day: bool = True,
        need_index: bool = False,
    ) -> Dict[str, Any]:
        """
        获取未来天气及当前天气数据。

        :param latitude: 目标纬度
        :param longitude: 目标经度
        :param need_more_day: 是否获取扩展天数（7~15 天）
        :param need_index: 是否需要生活指数等扩展信息
        """
        params = {
            "lat": f"{latitude:.6f}",
            "lng": f"{longitude:.6f}",
            "needMoreDay": 1 if need_more_day else 0,
            "needIndex": 1 if need_index else 0,
            "needHourData": 0,
            "need3HourForcast": 0,
            "needAlarm": 0,
        }
        headers = {
            "Authorization": f"APPCODE {self._config.app_code}",
        }
        async with httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=headers,
            timeout=self._config.timeout,
            verify=self._config.verify_ssl,
        ) as client:
            response = await client.get("/gps-to-weather", params=params)

        if response.status_code != httpx.codes.OK:
            logger.warning(
                "weather api http error | status={} body={}",
                response.status_code,
                response.text[:200],
            )
            raise WeatherAPIError(f"Weather API HTTP {response.status_code}")

        data: Dict[str, Any] = response.json()
        if data.get("showapi_res_code") != 0:
            error_msg = data.get("showapi_res_error") or "unknown"
            logger.warning("weather api business error", message=error_msg)
            raise WeatherAPIError(f"Weather API error: {error_msg}")

        body: Optional[Dict[str, Any]] = data.get("showapi_res_body")
        if not body or body.get("ret_code") != 0:
            remark = body.get("remark") if isinstance(body, dict) else None
            logger.warning("weather api ret_code invalid", remark=remark)
            raise WeatherAPIError(f"Weather API invalid ret_code: {remark or 'unknown'}")

        return body
