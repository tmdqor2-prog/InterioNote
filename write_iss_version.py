"""
v3.5.2 — 인스톨러 빌드 직전에 호출.
app/version.json 의 "version" 값을 읽어서 InterioNoteSetup.iss 가 #include 하는
version_for_iss.iss 파일을 생성한다. 결과는 한 줄:

    #define MyAppVersion "3.5.2"

이렇게 하면 .iss 와 version.json 사이의 버전 불일치(예: 인스톨러가 3.0.0,
zip 이 3.5.2)가 원천 차단됨.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    vj = here / "app" / "version.json"
    if not vj.exists():
        print(f"[write_iss_version] ERROR: {vj} not found", file=sys.stderr)
        return 1
    try:
        data = json.loads(vj.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[write_iss_version] ERROR: invalid JSON — {e}", file=sys.stderr)
        return 2
    version = (data.get("version") or "").strip()
    if not version:
        print("[write_iss_version] ERROR: version field empty", file=sys.stderr)
        return 3

    out = here / "version_for_iss.iss"
    out.write_text(f'#define MyAppVersion "{version}"\n', encoding="utf-8")
    print(f"[write_iss_version] OK  {out.name}  →  {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
