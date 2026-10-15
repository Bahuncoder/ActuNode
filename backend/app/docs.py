"""API documentation page (W3): Swagger UI from an exact, pinned version; off when login is required.

On a shared lab the page would run third-party script on the lab's origin, so with login required there is no
docs page and no openapi.json. ReDoc is not served."""

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

SWAGGER_UI_VERSION = "5.33.2"
_CDN = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}"
DOCS_URL = "/api/docs"
OPENAPI_URL = "/api/openapi.json"


def app_options(login_required: bool) -> dict:
    """FastAPI() arguments: the built-in docs routes are always off; openapi.json only without login."""
    return {"docs_url": None, "redoc_url": None, "openapi_url": None if login_required else OPENAPI_URL}


def add_docs(app: FastAPI, login_required: bool) -> None:
    if login_required:
        return

    @app.get(DOCS_URL, include_in_schema=False)
    def docs():
        return get_swagger_ui_html(
            openapi_url=OPENAPI_URL,
            title=f"{app.title} - docs",
            swagger_js_url=f"{_CDN}/swagger-ui-bundle.js",
            swagger_css_url=f"{_CDN}/swagger-ui.css",
            swagger_favicon_url="data:,",
        )
