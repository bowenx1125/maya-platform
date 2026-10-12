from __future__ import annotations

from typing import Any

from app.main import app


def test_wave0_openapi_security_and_contract_surface() -> None:
    document = app.openapi()
    assert document["servers"] == [{"url": "/api/v1"}]
    assert document["security"] == [{"sessionCookie": []}]
    assert document["components"]["securitySchemes"]["sessionCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "maya_session",
    }
    assert set(document["components"]["schemas"]["CourseDetail"]["required"]) == {
        "id",
        "code",
        "name",
    }
    assert set(document["components"]["schemas"]["GroupDetail"]["required"]) == {
        "id",
        "course_id",
        "name",
    }

    expected: dict[str, tuple[Any, ...]] = {
        "/auth/login": ("post", "login", [], {"200", "401", "403", "413", "429"}),
        "/auth/register": (
            "post",
            "registerStudent",
            [],
            {"201", "403", "409", "413", "422", "429"},
        ),
        "/auth/me": ("get", "getCurrentUser", [{"sessionCookie": []}], {"200", "401"}),
        "/auth/switch": (
            "post",
            "switchDemoIdentity",
            [{"sessionCookie": []}],
            {"200", "403", "404"},
        ),
        "/auth/demo-identities": (
            "get",
            "listDemoIdentities",
            [],
            {"200", "404"},
        ),
        "/auth/quick-login": (
            "post",
            "quickLogin",
            [],
            {"200", "404", "503"},
        ),
        "/auth/logout": ("post", "logout", [{"sessionCookie": []}], {"204"}),
        "/courses": ("get", "listCourses", [{"sessionCookie": []}], {"200"}),
        "/courses/{course_id}": (
            "get",
            "getCourse",
            [{"sessionCookie": []}],
            {"200", "404"},
        ),
        "/courses/{course_id}/groups": (
            "get",
            "listCourseGroups",
            [{"sessionCookie": []}],
            {"200", "404"},
        ),
        "/groups/{group_id}": (
            "get",
            "getGroup",
            [{"sessionCookie": []}],
            {"200", "404"},
        ),
    }
    for path, (method, operation_id, security, statuses) in expected.items():
        operation = document["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert operation["security"] == security
        assert set(operation["responses"]) == statuses
        for status_code in statuses - {"200", "201", "204"}:
            response = operation["responses"][status_code]
            content = response.get("content")
            if content is not None:
                assert content["application/json"]["schema"]["$ref"] == "#/components/schemas/Error"

    login_body = document["paths"]["/auth/login"]["post"]["requestBody"]
    assert login_body["required"] is True
    assert (
        login_body["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/LoginRequest"
    )
    register_body = document["paths"]["/auth/register"]["post"]["requestBody"]
    assert register_body["required"] is True
    assert (
        register_body["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RegisterRequest"
    )
    switch_operation = document["paths"]["/auth/switch"]["post"]
    assert switch_operation["requestBody"]["required"] is True
    switch_schema = switch_operation["requestBody"]["content"]["application/json"]["schema"]
    if "$ref" in switch_schema:
        switch_schema = document["components"]["schemas"][switch_schema["$ref"].rsplit("/", 1)[-1]]
    assert switch_schema["required"] == ["user_id"]
    assert switch_schema["properties"]["user_id"]["format"] == "uuid"

    for path in ("/auth/switch", "/auth/logout"):
        parameters = document["paths"][path]["post"]["parameters"]
        csrf = next(item for item in parameters if item["name"] == "X-CSRF-Token")
        assert csrf["in"] == "header"
        assert csrf["required"] is True
        assert csrf["schema"]["minLength"] == 32
