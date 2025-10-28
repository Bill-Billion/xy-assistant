import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.weather_service import GeoPoint, WeatherService
from app.services.command_service import _evaluate_weather_condition
from app.utils.time_utils import EAST_EIGHT


class DummyWeatherClient:
    def __init__(self, payload):
        self._payload = payload

    async def get_forecast(self, latitude, longitude, need_more_day=True, need_index=False):
        return self._payload


@pytest.mark.asyncio
async def test_weather_service_fetch_summary(monkeypatch):
    settings = SimpleNamespace(
        weather_api_enabled=True,
        weather_api_app_code="dummy",
        weather_api_base_url="https://ali-weather.showapi.com",
        weather_api_timeout=5.0,
        weather_api_verify_ssl=False,
        weather_default_city="长沙市",
        weather_default_lat=28.22778,
        weather_default_lon=112.93886,
        weather_cache_ttl=60,
        weather_geo_cache_ttl=60,
    )

    payload = {
        "time": "20251027120000",
        "now": {
            "weather": "多云",
            "temperature": "19",
            "sd": "60%",
        },
        "f1": {
            "day": "20251027",
            "day_weather": "多云",
            "night_weather": "小雨",
            "day_air_temperature": "22",
            "night_air_temperature": "14",
            "day_wind_direction": "西南风",
            "day_wind_power": "0-3级 <5.4m/s",
            "night_wind_direction": "东南风",
            "night_wind_power": "0-3级 <5.4m/s",
            "jiangshui": "10%",
        },
        "f2": {
            "day": "20251028",
            "day_weather": "小雨",
            "night_weather": "小雨",
            "day_air_temperature": "20",
            "night_air_temperature": "13",
            "day_wind_direction": "东北风",
            "day_wind_power": "0-3级 <5.4m/s",
            "night_wind_direction": "东南风",
            "night_wind_power": "0-3级 <5.4m/s",
            "jiangshui": "80%",
        },
        "ret_code": 0,
    }

    service = WeatherService(settings, client=DummyWeatherClient(payload), llm_client=None)

    async def fake_geocode(self, location: str):  # type: ignore[override]
        return GeoPoint(name=location, latitude=30.67, longitude=104.06)

    monkeypatch.setattr(WeatherService, "_geocode", fake_geocode)

    context = await service.fetch("成都今天天气怎么样")
    assert context is not None
    assert "成都" in context.summary
    detail = context.to_function_detail()
    assert detail["forecast"][0]["date"] == "2025-10-27"
    assert detail["forecast"][0]["daytime"] == "多云"
    flags = context.derived_flags
    assert flags["target_day"]["has_rain"] is True
    judgement, evidence = _evaluate_weather_condition("sunny", context)
    assert judgement == "no"
    judgement_rain, evidence_rain = _evaluate_weather_condition("rain", context)
    assert judgement_rain == "yes"
    assert evidence_rain

    # 查询中仅包含时间表达时应回退到默认城市
    fallback_context = await service.fetch("这周日天气怎么样")
    assert fallback_context is not None
    assert fallback_context.location == settings.weather_default_city
    assert fallback_context.location_source == "default"

    # 同时含有城市与时间表达时应识别城市
    city_context = await service.fetch("长沙这周日天气怎么样")
    assert city_context is not None
    assert city_context.location == "长沙市"
    assert city_context.location_source == "rule"
    assert city_context.to_function_detail()["location_source"] == "rule"


def test_extract_location_variants():
    settings = SimpleNamespace(
        weather_api_enabled=False,
        weather_api_app_code=None,
        weather_api_base_url="https://ali-weather.showapi.com",
        weather_api_timeout=5.0,
        weather_api_verify_ssl=False,
        weather_default_city="长沙市",
        weather_default_lat=28.22778,
        weather_default_lon=112.93886,
        weather_cache_ttl=60,
        weather_geo_cache_ttl=60,
    )
    service = WeatherService(settings, client=None, llm_client=None)
    assert service._extract_location("成都明天天气如何") == "成都市"
    assert service._extract_location("今天天气怎么样") is None
    assert service._extract_location("北京的天气") == "北京市"
    assert service._extract_location("武汉3天后会下雨吗") == "武汉市"


class DummyLLMClient:
    def __init__(self, responses):
        if isinstance(responses, list):
            self._responses = list(responses)
        else:
            self._responses = [responses]

    async def chat(self, system_prompt, messages, response_format=None):
        if not self._responses:
            raise AssertionError("No more dummy responses available")
        return ("", self._responses.pop(0))


@pytest.mark.asyncio
async def test_weather_service_llm_fallback(monkeypatch):
    settings = SimpleNamespace(
        weather_api_enabled=True,
        weather_api_app_code="dummy",
        weather_api_base_url="https://ali-weather.showapi.com",
        weather_api_timeout=5.0,
        weather_api_verify_ssl=False,
        weather_default_city="长沙市",
        weather_default_lat=28.22778,
        weather_default_lon=112.93886,
        weather_cache_ttl=60,
        weather_geo_cache_ttl=60,
        weather_llm_enabled=True,
        weather_llm_confidence_threshold=0.6,
    )

    payload = {
        "time": "20251027120000",
        "now": {"weather": "晴", "temperature": "20", "sd": "50%"},
        "f1": {
            "day": "20251027",
            "day_weather": "晴",
            "night_weather": "晴",
            "day_air_temperature": "23",
            "night_air_temperature": "15",
            "day_wind_direction": "西南风",
            "day_wind_power": "0-3级 <5.4m/s",
            "night_wind_direction": "西南风",
            "night_wind_power": "0-3级 <5.4m/s",
            "jiangshui": "5%",
        },
        "ret_code": 0,
    }

    llm_client = DummyLLMClient(
        {
            "city": "上海",
            "province": "",
            "country": "中国",
            "datetime": "本周日",
            "confidence": 0.9,
        }
    )
    service = WeatherService(settings, client=DummyWeatherClient(payload), llm_client=llm_client)

    async def fake_geocode(self, location: str):  # type: ignore[override]
        return GeoPoint(name=location, latitude=31.2304, longitude=121.4737)

    monkeypatch.setattr(WeatherService, "_geocode", fake_geocode)
    monkeypatch.setattr(WeatherService, "_extract_location", lambda self, _: None)

    context = await service.fetch("这周日去上海玩天气怎么样？")
    assert context is not None
    assert context.location == "上海市"
    assert context.location_source == "llm"
    detail = context.to_function_detail()
    assert detail["location_source"] == "llm"
    assert detail["llm_metadata"]["location"]["city"] == "上海"


@pytest.mark.asyncio
async def test_weather_service_llm_date(monkeypatch):
    settings = SimpleNamespace(
        weather_api_enabled=True,
        weather_api_app_code="dummy",
        weather_api_base_url="https://ali-weather.showapi.com",
        weather_api_timeout=5.0,
        weather_api_verify_ssl=False,
        weather_default_city="长沙市",
        weather_default_lat=28.22778,
        weather_default_lon=112.93886,
        weather_cache_ttl=60,
        weather_geo_cache_ttl=60,
        weather_llm_enabled=True,
        weather_llm_confidence_threshold=0.6,
    )

    payload = {
        "time": "20251027120000",
        "now": {"weather": "多云", "temperature": "21", "sd": "55%"},
        "f1": {
            "day": "20251027",
            "day_weather": "多云",
            "night_weather": "晴",
            "day_air_temperature": "24",
            "night_air_temperature": "16",
            "day_wind_direction": "东风",
            "day_wind_power": "0-3级 <5.4m/s",
            "night_wind_direction": "东北风",
            "night_wind_power": "0-3级 <5.4m/s",
            "jiangshui": "20%",
        },
        "f2": {
            "day": "20251028",
            "day_weather": "晴",
            "night_weather": "晴",
            "day_air_temperature": "25",
            "night_air_temperature": "17",
            "day_wind_direction": "东北风",
            "day_wind_power": "0-3级 <5.4m/s",
            "night_wind_direction": "东北风",
            "night_wind_power": "0-3级 <5.4m/s",
            "jiangshui": "10%",
        },
        "ret_code": 0,
    }

    fixed_now = datetime(2025, 10, 27, 9, 0, tzinfo=EAST_EIGHT)
    llm_client = DummyLLMClient(
        [
            {
                "resolved_date": "2025年10月30日",
                "confidence": 0.85,
                "reason": "基于当前日期推算三天后。",
            }
        ]
    )
    service = WeatherService(settings, client=DummyWeatherClient(payload), llm_client=llm_client)

    monkeypatch.setattr(WeatherService, "_extract_location", lambda self, _: None)

    async def fake_location_llm(self, query):
        return None

    monkeypatch.setattr(WeatherService, "_extract_location_with_llm", fake_location_llm)
    monkeypatch.setattr("app.services.weather_service.now_e8", lambda: fixed_now)

    context = await service.fetch("三天后是什么天气")
    assert context is not None
    assert context.target_date_source == "llm"
    assert context.target_date.isoformat() == "2025-10-30"
    metadata = context.to_function_detail()["llm_metadata"]
    assert metadata["date"]["resolved_date"] == "2025-10-30"


@pytest.mark.asyncio
async def test_weather_service_llm_low_confidence(monkeypatch):
    settings = SimpleNamespace(
        weather_api_enabled=True,
        weather_api_app_code="dummy",
        weather_api_base_url="https://ali-weather.showapi.com",
        weather_api_timeout=5.0,
        weather_api_verify_ssl=False,
        weather_default_city="长沙市",
        weather_default_lat=28.22778,
        weather_default_lon=112.93886,
        weather_cache_ttl=60,
        weather_geo_cache_ttl=60,
        weather_llm_enabled=True,
        weather_llm_confidence_threshold=0.6,
        weather_llm_low_confidence_threshold=0.3,
    )

    payload = {
        "time": "20251027120000",
        "now": {"weather": "多云", "temperature": "21", "sd": "55%"},
        "f1": {
            "day": "20251027",
            "day_weather": "多云",
            "night_weather": "晴",
            "day_air_temperature": "24",
            "night_air_temperature": "16",
            "day_wind_direction": "东风",
            "day_wind_power": "0-3级 <5.4m/s",
            "night_wind_direction": "东北风",
            "night_wind_power": "0-3级 <5.4m/s",
            "jiangshui": "20%",
        },
        "ret_code": 0,
    }

    llm_client = DummyLLMClient(
        {
            "city": "武汉",
            "province": "湖北",
            "country": "中国",
            "datetime": "三天后",
            "confidence": 0.45,
        }
    )
    service = WeatherService(settings, client=DummyWeatherClient(payload), llm_client=llm_client)

    async def fake_geocode(self, location: str):  # type: ignore[override]
        return GeoPoint(name=location, latitude=30.5928, longitude=114.3055)

    monkeypatch.setattr(WeatherService, "_geocode", fake_geocode)
    monkeypatch.setattr(WeatherService, "_extract_location", lambda self, _: None)

    context = await service.fetch("武汉3天后会下雨吗")
    assert context is not None
    assert context.location == "武汉市"
    assert context.location_source == "llm_low"
    detail = context.to_function_detail()
    assert detail["location_source"] == "llm_low"
