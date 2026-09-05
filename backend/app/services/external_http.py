from __future__ import annotations

import time
import httpx

RETRYABLE_STATUS={408,425,429,500,502,503,504}

class ExternalServiceError(RuntimeError):
    def __init__(self, service:str, message:str, *, status_code:int|None=None):
        super().__init__(f"{service}: {message}")
        self.service=service
        self.status_code=status_code

def request_json(method:str,url:str,*,service:str,headers=None,params=None,json_body=None,timeout=20.0,retries=2):
    last=None
    for attempt in range(retries+1):
        try:
            r=httpx.request(method,url,headers=headers,params=params,json=json_body,timeout=timeout,follow_redirects=True)
            if r.status_code in RETRYABLE_STATUS and attempt<retries:
                time.sleep(0.35*(2**attempt))
                continue
            r.raise_for_status()
            return r.json() if r.content else {}
        except (httpx.TimeoutException,httpx.NetworkError) as exc:
            last=exc
            if attempt<retries:
                time.sleep(0.35*(2**attempt))
                continue
            raise ExternalServiceError(service,f"network error after {retries+1} attempts: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            last=exc
            code=exc.response.status_code
            raise ExternalServiceError(service,f"HTTP {code} for {url}",status_code=code) from exc
    raise ExternalServiceError(service,str(last or "unknown error"))
