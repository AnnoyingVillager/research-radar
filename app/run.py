from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.crypto import ensure_self_signed_certificate


def main() -> None:
    settings = get_settings()
    ssl_certfile = None
    ssl_keyfile = None
    if settings.tls_enabled:
        certificate, private_key = ensure_self_signed_certificate(
            settings.tls_cert_path,
            settings.tls_key_path,
            settings.tls_hostnames,
        )
        ssl_certfile = str(certificate)
        ssl_keyfile = str(private_key)
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


if __name__ == "__main__":
    main()

