from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import RouteConfig


DEFAULT_API_KEY = "ae99952bf4d24fb893ce33472cb6d605"
TRIPS_ENDPOINT = "https://gateway.apiportal.ns.nl/reisinformatie-api/api/v3/trips"


class NSApiError(RuntimeError):
    """Raised when the NS trip endpoint cannot be queried successfully."""


class NSClient:
    def __init__(
        self,
        api_key: str | None = None,
        language: str = "nl",
        product: str = "OVCHIPKAART_ENKELE_REIS",
        travel_class: int = 2,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("NS_API_SUBSCRIPTION_KEY", DEFAULT_API_KEY)
        self.language = language
        self.product = product
        self.travel_class = str(travel_class)
        self.timeout_seconds = timeout_seconds
        self.ssl_context = _build_ssl_context()

    def fetch_route(self, route: RouteConfig, requested_datetime: datetime) -> dict[str, object]:
        params = {
            "originUicCode": route.origin_uic_code,
            "destinationUicCode": route.destination_uic_code,
            "dateTime": requested_datetime.strftime("%Y-%m-%dT%H:%M:00"),
            "lang": self.language,
            "product": self.product,
            "travelClass": self.travel_class,
        }
        if route.disabled_transport_modalities:
            params["disabledTransportModalities"] = ",".join(route.disabled_transport_modalities)

        request = Request(
            f"{TRIPS_ENDPOINT}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Accept-Language": self.language,
                "Ocp-Apim-Subscription-Key": self.api_key,
                "User-Agent": "ns-status/0.1",
                "X-Caller-Id": "NS Web",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise NSApiError(f"NS API returned HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            if _is_certificate_error(exc) and shutil.which("curl"):
                payload = self._fetch_via_curl(params)
            else:
                raise NSApiError(f"NS API request failed: {exc.reason}") from exc

        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise NSApiError("Unexpected NS API response shape.")
        return parsed

    def _fetch_via_curl(self, params: dict[str, str]) -> str:
        command = [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--get",
            TRIPS_ENDPOINT,
            "-H",
            "Accept: application/json",
            "-H",
            f"Accept-Language: {self.language}",
            "-H",
            f"Ocp-Apim-Subscription-Key: {self.api_key}",
            "-H",
            "User-Agent: ns-status/0.1",
            "-H",
            "X-Caller-Id: NS Web",
        ]
        for key, value in params.items():
            command.extend(["--data-urlencode", f"{key}={value}"])

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            raise NSApiError(f"curl failed: {exc.stderr.strip()}") from exc
        except subprocess.TimeoutExpired as exc:
            raise NSApiError("curl request to NS API timed out.") from exc
        return result.stdout


def _build_ssl_context() -> ssl.SSLContext:
    ca_candidates = [
        os.getenv("NS_STATUS_CA_FILE"),
        os.getenv("SSL_CERT_FILE"),
        "/etc/ssl/cert.pem",
    ]
    for candidate in ca_candidates:
        if candidate and Path(candidate).exists():
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def _is_certificate_error(error: URLError) -> bool:
    reason = getattr(error, "reason", None)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason)
