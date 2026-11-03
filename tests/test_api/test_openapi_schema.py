from services.nexus_api.main import app


def test_api_openapi_schema_generates_for_all_routers() -> None:
    schema = app.openapi()

    assert "/api/strategies/{strategy_id}/mql5" in schema["paths"]
