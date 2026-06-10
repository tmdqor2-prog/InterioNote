"""
v3.5.3 — GitHub 자동 릴리스 업로드 헬퍼.

사용:
    py -3.12 release_to_github.py

전제:
    1. gh CLI 설치 + 인증 (gh auth login) 한 번 완료
    2. build-installer.bat 로 Output\\ 산출물 생성 완료
    3. git remote 설정 완료 (origin = github)

자동 처리:
    - app/version.json 의 version 읽기
    - git tag v{version} 생성·푸시
    - Output\\ 의 산출물 + 릴리스 노트 업로드
    - app/version.json 의 changelog[0] 항목을 릴리스 노트로 변환
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def fail(msg: str) -> None:
    print(f"\n[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=capture, text=True, cwd=str(HERE))


def check_prerequisites() -> tuple[str, dict]:
    if shutil.which("gh") is None:
        fail(
            "gh CLI 가 설치되지 않았습니다. https://cli.github.com/ 에서 설치 후\n"
            "        cmd 에서 'gh auth login' 한 번 실행해 주세요."
        )
    # gh 인증 확인
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r.returncode != 0:
        fail(
            "gh CLI 가 인증되지 않았습니다. cmd 에서 'gh auth login' 실행 후\n"
            "        브라우저 인증을 완료해 주세요."
        )

    # version.json 로드
    vj = HERE / "app" / "version.json"
    if not vj.exists():
        fail(f"{vj} 가 없습니다.")
    data = json.loads(vj.read_text(encoding="utf-8"))
    version = (data.get("version") or "").strip()
    if not version:
        fail("version.json 에 version 필드가 비어 있습니다.")

    # changelog 첫 항목 (이번 버전)
    cl = data.get("changelog") or []
    entry = next((c for c in cl if c.get("version") == version), None)
    if entry is None:
        fail(f"changelog 에 version='{version}' 항목이 없습니다.")

    return version, entry


def render_release_notes(version: str, entry: dict) -> str:
    """version.json 의 changelog 항목을 GitHub 릴리스 양식으로 변환."""
    title = entry.get("title", "")
    items = entry.get("items") or []

    # ✨ 새 기능 vs 🔧 버그 픽스 자동 분류
    feature_emojis = ("✨", "🆕", "🖥", "👤", "📱", "📦", "🤖", "🔐", "📞", "💬", "🔍", "📊", "🎨", "📋", "💰", "🧱", "🗓", "🚀", "📥", "📂", "📁", "🌗", "⚙️", "📌", "🟢", "🟡", "🔴", "🤝", "🏷", "⭐", "📄", "🔁", "🎯", "🐢", "🐇", "❓", "✏️", "🪟", "🔔")
    bug_emojis = ("🐛", "🔧", "🛠")

    features = []
    bugs = []
    for it in items:
        if not isinstance(it, str):
            continue
        if it.startswith("🔧 안정성 개선") or it.startswith("🔧 프로그램 안정성 개선") or it.startswith("🔧 시스템 호환성 개선"):
            continue  # 마지막에 따로 추가
        is_bug = any(it.startswith(e) for e in bug_emojis)
        if is_bug:
            bugs.append(it)
        else:
            features.append(it)

    parts = [f"## 🆕 v{version} — {title}", ""]
    if features:
        parts.append("### ✨ 새 기능 / 개선")
        for f in features:
            # 첫 단어를 굵게 만들기 (—이 있으면 그 앞부분)
            if " — " in f:
                head, tail = f.split(" — ", 1)
                parts.append(f"- **{head}** — {tail}")
            else:
                parts.append(f"- {f}")
        parts.append("")
    if bugs:
        parts.append("### 🔧 버그 픽스")
        for b in bugs:
            if " — " in b:
                head, tail = b.split(" — ", 1)
                parts.append(f"- **{head}** — {tail}")
            else:
                parts.append(f"- {b}")
        parts.append("")
    parts.extend([
        "### 📥 설치",
        f"- **신규 설치**: `InterioNoteSetup-{version}.exe` 다운로드 → 더블클릭",
        "- **기존 사용자**: 앱 설정 → 📦 업데이트 확인 → ✨ 빠른 업데이트 (또는 인스톨러 다시 실행)",
        "",
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
    ])
    return "\n".join(parts)


def main() -> int:
    print("=" * 60)
    print(" InterioNote — GitHub Release 자동 업로드")
    print("=" * 60)
    print()

    version, entry = check_prerequisites()
    print(f"[INFO] 대상 버전: v{version}")
    print(f"[INFO] 제목: {entry.get('title', '')}")
    print()

    # 산출물 확인
    out = HERE / "Output"
    setup_exe = out / f"InterioNoteSetup-{version}.exe"
    update_zip = out / f"InterioNote-update-{version}.zip"
    update_manifest = out / f"update-manifest-{version}.json"

    missing = [str(p) for p in (setup_exe, update_zip, update_manifest) if not p.exists()]
    if missing:
        fail("아래 산출물이 없습니다 — build-installer.bat 를 먼저 실행해 주세요:\n        " + "\n        ".join(missing))

    print(f"[INFO] 인스톨러: {setup_exe.name} ({setup_exe.stat().st_size / (1024*1024):.1f} MB)")
    print(f"[INFO] 업데이트 zip: {update_zip.name} ({update_zip.stat().st_size / (1024*1024):.2f} MB)")
    print(f"[INFO] 매니페스트: {update_manifest.name}")
    print()

    # 릴리스 노트 생성
    notes_path = HERE / f"release_notes_{version}.md"
    notes_path.write_text(render_release_notes(version, entry), encoding="utf-8")
    print(f"[INFO] 릴리스 노트 생성: {notes_path.name}")
    print()

    # git push (tag 포함)
    print("[STEP 1/3] git push origin main...")
    run(["git", "push", "origin", "main"])

    print(f"\n[STEP 2/3] git tag v{version}...")
    # 태그가 이미 있으면 무시
    r = subprocess.run(["git", "tag", "-l", f"v{version}"], capture_output=True, text=True, cwd=str(HERE))
    if r.stdout.strip():
        print(f"  (태그 v{version} 이미 존재 → 푸시만)")
    else:
        run(["git", "tag", f"v{version}"])
    run(["git", "push", "origin", f"v{version}"], check=False)  # 이미 있으면 실패해도 OK

    # gh release create
    print(f"\n[STEP 3/3] gh release create v{version}...")
    # 이미 존재하면 실패. 그러면 assets 만 추가
    create_cmd = [
        "gh", "release", "create", f"v{version}",
        str(setup_exe), str(update_zip), str(update_manifest),
        "--title", f"v{version}",
        "--notes-file", str(notes_path),
    ]
    r = subprocess.run(create_cmd, cwd=str(HERE), capture_output=True, text=True)
    if r.returncode == 0:
        print(r.stdout.strip())
    else:
        # 이미 있으면 upload 만 시도
        if "already exists" in (r.stderr or "") or "already_exists" in (r.stdout or ""):
            print(f"  (릴리스 v{version} 이미 존재 → 자산만 업로드)")
            run([
                "gh", "release", "upload", f"v{version}",
                str(setup_exe), str(update_zip), str(update_manifest),
                "--clobber",
            ])
        else:
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            fail("gh release create 실패")

    print()
    print("=" * 60)
    print(f" 완료: https://github.com/tmdqor2-prog/InterioNote/releases/tag/v{version}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
