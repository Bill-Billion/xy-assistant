import pytest

from app.services.weather_service import GeoPoint, WeatherAPIError, WeatherService


class DummyWeatherClient:
    def __init__(self, payload=None, *, raises=None):
        self._payload = payload or {}
        self._raises = raises
        self.called = False

    async def get_forecast(self, latitude, longitude, need_more_day=True, need_index=False):
        self.called = True
        if self._raises:
            raise self._raises
        return self._payload


@pytest.fixture()
def base_settings():
    return type(
        "Settings",
        (),
        {
            "weather_api_enabled": True,
            "weather_api_app_code": "dummy",
            "weather_api_base_url": "https://ali-weather.showapi.com",
            "weather_api_timeout": 5.0,
            "weather_api_verify_ssl": False,
            "weather_default_city": "长沙市",
            "weather_default_lat": 28.22778,
            "weather_default_lon": 112.93886,
            "weather_cache_ttl": 60,
            "weather_geo_cache_ttl": 60,
            "weather_llm_enabled": False,
            "weather_llm_confidence_threshold": 0.6,
            "weather_llm_low_confidence_threshold": 0.3,
            "weather_broadcast_llm_enabled": False,
        },
    )()


async def fake_geocode(self, location: str):  # type: ignore[override]
    return GeoPoint(name=location, latitude=30.67, longitude=104.06)


@pytest.mark.asyncio
async def test_fetch_uses_llm_summary_without_api(monkeypatch, base_settings):
    client = DummyWeatherClient()
    service = WeatherService(base_settings, client=client, llm_client=None)
    monkeypatch.setattr(WeatherService, "_geocode", fake_geocode)

    llm_info = {
        "location": "武汉市",
        "location_confidence": 0.92,
        "target_date": "2025-11-03",
        "target_date_text": "下周一",
        "target_date_confidence": 0.88,
        "needs_realtime_data": False,
    }
    summary = "武汉市下周一预计多云，气温9~20℃，东南微风。"

    context = await service.fetch(
        llm_info=llm_info,
        summary=summary,
        needs_realtime=False,
        query="武汉下周一天气怎么样",
    )

    assert context is not None
    assert context.summary == summary
    assert context.location == "武汉市"
    assert client.called is False
    detail = context.to_function_detail()
    assert detail["location"] == "武汉市"
    assert detail["needs_realtime_data"] is False


@pytest.mark.asyncio
async def test_fetch_calls_api_when_needed(monkeypatch, base_settings):
    payload = {
        "time": "20251027120000",
        "now": {"weather": "多云", "temperature": "19", "sd": "60%"},
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
        "ret_code": 0,
    }
    client = DummyWeatherClient(payload)
    service = WeatherService(base_settings, client=client, llm_client=None)
    monkeypatch.setattr(WeatherService, "_geocode", fake_geocode)

    llm_info = {
        "location": "成都",
        "location_confidence": 0.9,
        "target_date": "2025-10-27",
        "target_date_text": "今天",
        "target_date_confidence": 0.9,
        "needs_realtime_data": True,
    }

    context = await service.fetch(
        llm_info=llm_info,
        summary="成都市今天多云，气温14~22℃。",
        needs_realtime=True,
        query="成都今天天气怎么样",
    )

    assert client.called is True
    assert context is not None
    detail = context.to_function_detail()
    assert detail["location_source"] in {"llm", "llm_low"}
    assert detail["forecast"]


@pytest.mark.asyncio
async def test_fetch_api_failure_returns_fallback(monkeypatch, base_settings):
    client = DummyWeatherClient(raises=WeatherAPIError("fail"))
    service = WeatherService(base_settings, client=client, llm_client=None)
    monkeypatch.setattr(WeatherService, "_geocode", fake_geocode)

    llm_info = {
        "location": "上海市",
        "location_confidence": 0.4,
        "target_date": "2025-10-29",
        "needs_realtime_data": True,
    }

    context = await service.fetch(
        llm_info=llm_info,
        summary="上海将有凉爽微风。",
        needs_realtime=True,
        query="上海后天会下雨吗",
    )

    assert context is not None
    assert context.llm_metadata.get("api_failed") is True
    assert context.summary == "上海将有凉爽微风。"
    assert client.called is True
