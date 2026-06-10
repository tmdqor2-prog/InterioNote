"""
Phase 8D — 인앱 빠른 업데이트 zip 생성기.

build-installer.bat 끝에서 호출. 산출물:
    Output\\InterioNote-update-<version>.zip

zip 안 구조:
    app/                          ← 모든 Python 코드
    app/static/                   ← HTML/JS/CSS
    InterioNote.py                ← 진입점
    update_manifest.json          ← 호환성 메타데이터

PyInstaller 의 _internal/, models_cache/, data/, venv/ 등은 절대 포함 안 함.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# config.py 에서 APP_VERSION 가져오기
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from app.config import APP_VERSION  # noqa: E402


# 빠른 업데이트로 적용할 수 있는 최소 앱 버전.
# 의존성(pip 패키지) 변경이 있는 릴리스 또는 helper 메커니즘 자체 변경 시
# 이 값을 올려서 옛 사용자가 자동으로 풀 인스톨러를 받게 만든다.
# v3.0.0: users 테이블 신규, PyJWT 추가, passlib 제거, 로그인 미들웨어 추가.
# 이전 버전 클라이언트는 DB 스키마 + pip 패키지 변경으로 빠른 업데이트 불가 → 풀 인스톨러 필요.
MIN_APP_VERSION = "3.0.0"


def collect_files() -> list[tuple[Path, str]]:
    """zip 에 들어갈 (실제경로, zip 내부경로) 목록.

    v2.4.2 변경: PyInstaller 가 _internal/app/ 에 푸는 데이터 파일만 zip 에 포함.
    Python 소스 (.py) 는 PYZ 안에 컴파일되어 있어서 robocopy 로 못 바꿈 →
    포함해도 효과 없으므로 제외. version.json 과 static/ 만 포함.
    """
    pairs: list[tuple[Path, str]] = []

    app_dir = HERE / "app"

    # app/version.json (단일 진실)
    version_json = app_dir / "version.json"
    if version_json.exists():
        pairs.append((version_json, "app/version.json"))

    # app/static/* (HTML/JS/CSS — 실제 교체 가능한 데이터)
    static_dir = app_dir / "static"
    if static_dir.exists():
        for p in static_dir.rglob("*"):
            if p.is_file():
                arcname = str(p.relative_to(HERE)).replace("\\", "/")
                pairs.append((p, arcname))

    return pairs


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out_dir = HERE / "Output"
    out_dir.mkdir(exist_ok=True)
    zip_path = out_dir / f"InterioNote-update-{APP_VERSION}.zip"

    print(f"[build_update_zip] target version: {APP_VERSION}")
    print(f"[build_update_zip] min_app_version: {MIN_APP_VERSION}")

    pairs = collect_files()
    print(f"[build_update_zip] collecting {len(pairs)} files...")

    # 임시: zip 만들기 전에 manifest 생성 (file 목록은 빌드 후 채움)
    manifest = {
        "version": APP_VERSION,
        "min_app_version": MIN_APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(pairs),
    }

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in pairs:
            z.write(src, arcname=arc)
        # 마지막에 manifest 도 zip 안에 넣음
        z.writestr("update_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    size = zip_path.stat().st_size
    digest = sha256_of(zip_path)

    print(f"[build_update_zip] OK")
    print(f"  path:   {zip_path}")
    print(f"  size:   {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
    print(f"  sha256: {digest}")

    # 외부 manifest (GitHub Release 페이지에서 미리 보기용) 도 같이
    external_manifest = {**manifest, "size_bytes": size, "sha256": digest, "asset_name": zip_path.name}
    ext_manifest_path = out_dir / f"update-manifest-{APP_VERSION}.json"
    ext_manifest_path.write_text(
        json.dumps(external_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  manifest: {ext_manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
