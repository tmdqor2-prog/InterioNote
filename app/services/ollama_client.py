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
    """로컬 Ollama (127.0.0.1:11434) 싱글톤 클라이언트."""
    global _singleton
    if _singleton is None:
        _singleton = OllamaClient()
    return _singleton


# ─── v3.5.2: 사용자별 원격 Ollama 분기 + 자동 폴백 ──────────────────────────

def get_client_for_user(username: Optional[str]) -> OllamaClient:
    """
    사용자별 Ollama 클라이언트.
    - username 의 ollama_remote_url 이 설정돼 있으면 → 원격 클라이언트
    - 비어 있으면 → 로컬 클라이언트 (다른 사용자는 영향 없음)

    실제 호출 실패 시의 폴백은 호출자(generate_with_fallback) 가 처리.
    """
    if username:
        try:
            from app.services import auth_service  # 순환 import 방지: 함수 내부 import
            url = auth_service.get_user_ollama_url(username)
            if url:
                return OllamaClient(base_url=url)
        except Exception as e:
            log.warning(f"get_user_ollama_url 실패 ({username}): {e} — 로컬로 폴백")
    return get_client()


def generate_with_fallback(
    username: Optional[str],
    *,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    format_json: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    원격 Ollama 우선 → 연결 실패 시 로컬 자동 폴백.
    응답 dict 에 '_used_endpoint' 키를 추가해 어느 쪽이 쓰였는지 표시.
    """
    primary = get_client_for_user(username)
    is_remote = (primary.base_url != get_client().base_url)
    try:
        resp = primary.generate(
            model=model, prompt=prompt, system=system,
            format_json=format_json, options=options,
        )
        resp["_used_endpoint"] = "remote" if is_remote else "local"
        return resp
    except OllamaError as e:
        if not is_remote:
            raise  # 이미 로컬인데 실패 → 그대로 에러
        # 원격 실패 → 로컬로 한 번 더 시도
        log.warning(f"원격 Ollama 실패 ({primary.base_url}): {e} — 로컬로 폴백")
        local = get_client()
        resp = local.generate(
            model=model, prompt=prompt, system=system,
            format_json=format_json, options=options,
        )
        resp["_used_endpoint"] = "local_fallback"
        resp["_remote_error"] = str(e)
        return resp


def test_remote_url(url: str) -> Dict[str, Any]:
    """
    설정 화면 '연결 테스트' 버튼용. 짧은 타임아웃으로 ping + 모델 목록 조회.
    반환: {ok, models, error?, latency_ms}
    """
    import time
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return {"ok": False, "error": "URL 이 비어 있습니다."}
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        return {"ok": False, "error": "URL 은 http:// 또는 https:// 로 시작해야 합니다."}
    try:
        t0 = time.monotonic()
        r = httpx.get(f"{cleaned}/api/tags", timeout=4.0)
        r.raise_for_status()
        latency = int((time.monotonic() - t0) * 1000)
        data = r.json()
        models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        return {"ok": True, "models": models, "latency_ms": latency, "url": cleaned}
    except httpx.TimeoutException:
        return {"ok": False, "error": "연결 시간 초과 (4초). 데스크톱이 켜져 있고 OLLAMA_HOST=0.0.0.0:11434 환경변수가 설정됐는지 확인하세요."}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"연결 실패 — 데스크톱이 응답하지 않습니다. Tailscale 연결 상태와 방화벽을 확인하세요. ({e})"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
