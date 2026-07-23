import httpx

from .retry import RetryExhausted, retry_async

_TRANSIENT_STATUS_CODES = {502, 503, 504, 429}


class OlostepAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class OlostepClient:
    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.olostep.com/v1",
        max_attempts: int = 3,
        timeout: float = 120.0,
        sleep_fn=None,
    ):
        self._api_key = api_key
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._timeout = timeout
        self._sleep_fn = sleep_fn

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, json_body: dict) -> dict:
        async def attempt():
            response = await self._http_client.post(
                f"{self._base_url}{path}",
                json=json_body,
                headers=self._headers(),
                timeout=self._timeout,
            )
            if response.status_code in _TRANSIENT_STATUS_CODES:
                raise OlostepAPIError(
                    f"transient Olostep API error: {response.status_code}",
                    status_code=response.status_code,
                )
            if response.status_code >= 400:
                body = response.json()
                error = body.get("error")
                if isinstance(error, dict):
                    message = error.get("message", "Olostep API error")
                    code = error.get("code")
                elif isinstance(error, str):
                    message = error
                    code = None
                else:
                    message = "Olostep API error"
                    code = None
                raise OlostepAPIError(message, status_code=response.status_code, code=code)
            return response.json()

        def _should_retry(exc: Exception) -> bool:
            if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
                return True
            return isinstance(exc, OlostepAPIError) and exc.status_code in _TRANSIENT_STATUS_CODES

        try:
            return await retry_async(
                attempt,
                max_attempts=self._max_attempts,
                should_retry=_should_retry,
                sleep_fn=self._sleep_fn,
            )
        except RetryExhausted as exc:
            raise OlostepAPIError("Olostep API error: retries exhausted") from exc
        except httpx.HTTPError as exc:
            raise OlostepAPIError(f"Olostep API network error: {exc}") from exc

    async def create_map(self, url: str, exclude_urls: list[str] | None = None) -> list[str]:
        body = {"url": url}
        if exclude_urls:
            body["exclude_urls"] = exclude_urls

        urls: list[str] = []
        cursor = None
        while True:
            request_body = dict(body)
            if cursor:
                request_body["cursor"] = cursor
            data = await self._post("/maps", request_body)
            urls.extend(data.get("urls", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        return urls

    async def scrape(self, url: str) -> tuple[int, str]:
        data = await self._post("/scrapes", {"url_to_scrape": url, "formats": ["html"]})
        result = data.get("result", {})
        html = result.get("html_content", "")
        status_code = result.get("page_metadata", {}).get("status_code")
        return status_code, html
