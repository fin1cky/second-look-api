"""Modal deployment entrypoint. Deploy with: modal deploy modal_app.py"""

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]", "httpx", "pydantic")
    .add_local_dir("app", remote_path="/root/app")
)

app = modal.App("second-look-api", image=image)


@app.function()
@modal.asgi_app()
def fastapi_app():
    from app.main import app as web_app

    return web_app
