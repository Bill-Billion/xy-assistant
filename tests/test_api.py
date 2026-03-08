import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse, FunctionAnalysis
from app.services.service_container import get_command_service


class DummyService:
    async def handle_command(self, payload: CommandRequest) -> CommandResponse:
        return CommandResponse(
            code=200,
            msg="测试回复",
            sessionId=payload.session_id or "session",
            function_analysis=FunctionAnalysis(
                result="小雅通话",
                target="张三",
                confidence=0.9,
                need_clarify=False,
            ),
        )


def get_dummy_service():
    return DummyService()


@pytest.fixture()
def client():
    app.dependency_overrides[get_command_service] = get_dummy_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_command_service, None)


def test_command_endpoint_returns_expected_structure(client: TestClient):
    response = client.post(
        "/api/command",
        json={"sessionId": "abc", "query": "我想联系家人"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["function_analysis"]["result"] == "小雅通话"
    assert data["function_analysis"]["target"] == "张三"
