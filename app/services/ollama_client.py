"""
Ollama HTTP 클라이언트 (Phase 4).

Ollama 가 로컬 127.0.0.1:11434 에 떠 있다는 전제.
- /api/tags   : 모델 목록
- /api/generate (stream=false) : 프롬프트 → 응답
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app import config

log = logging.getLogger("ollama")


class OllamaError(Exception):
    """Ollama 호출 실패."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = None,
        timeout_sec: float = None,
    ):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.timeout_sec = timeout_sec or float(config.OLLAMA_TIMEOUT_SEC)

    # --------- health / list ---------
    def list_models(self) -> List[Dict[str, Any]]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            r.raise_for_status()
        except Exception as e:
            raise OllamaError(f"Ollama 에 연결할 수 없습니다 ({self.base_url}): {type(e).__name__}: {e}")
        data = r.json()
        return data.get("models") or []

    def is_model_available(self, model: str) -> bool:
        try:
            for m in self.list_models():
                if m.get("name") == model or m.get("model") == model:
                    return True
        except OllamaError:
            return False
        return False

    # --------- generate ---------
    def generate(
        self,
        *,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        format_json: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        /api/generate 호출 (stream=False).
        반환: {"response": "...", "eval_count": int, "total_duration": ns, ...}
        """
        body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system
        if format_json:
            body["format"] = "json"
        # sane defaults
        default_opts = {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_ctx": 8192,
            "num_predict": 2048,
        }
        if options:
            default_opts.update(options)
        body["options"] = default_opts

        try:
            r = httpx.post(
                f"{self.base_url}/api/generate",
                json=body,
                timeout=self.timeout_sec,
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise OllamaError(
                f"Ollama HTTP {e.response.status_code}: {e.response.text[:400]}"
            )
        except Exception as e:
            raise OllamaError(f"Ollama 호출 실패: {type(e).__name__}: {e}")
        return r.json()


_singleton: Optional[OllamaClient] = None


def get_client() -> OllamaClient:
    global _singleton
    if _singleton is None:
        _singleton = OllamaClient()
    return _singleton
