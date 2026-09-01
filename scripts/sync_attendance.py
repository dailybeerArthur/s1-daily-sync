#!/usr/bin/env python3
"""
S1(SESP) 근태(출퇴근) 기록을 매일 자동으로 가져와 백엔드(Supabase)로 전송하는 스크립트.

동작 순서:
  1. s1esp.com 관리자사이트에 로그인
  2. 근태/출퇴근 메뉴로 이동
  3. 엑셀 다운로드 버튼 클릭 -> 파일 다운로드
  4. 엑셀 파일을 그대로(컬럼 구조 무관) 읽어서 각 행을 JSON으로 변환
  5. 백엔드 API(Supabase REST)로 그대로 전송

이 스크립트는 환경변수로 동작을 설정합니다 (.env.example 참고).
로그인 아이디/비밀번호는 절대 코드에 하드코딩하지 말고, 환경변수/GitHub Secrets로만 넣으세요.

** 중요 **
- 로그인 후 실제 메뉴 구조(사이드바 텍스트, 다운로드 버튼 위치 등)는 회사마다/버전마다 다를 수 있습니다.
- 처음 실행할 때는 반드시 DEBUG=1 로 실행해서 스크린샷(screenshots/ 폴더)을 확인하고,
  S1_MENU_TEXT / S1_DOWNLOAD_BUTTON_TEXT 값을 실제 화면에 맞게 조정하세요.
"""

import os
import sys
import glob
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# 설정값 (환경변수로 오버라이드 가능)
# ---------------------------------------------------------------------------
S1_BASE_URL = os.environ.get("S1_BASE_URL", "https://s1esp.com")
S1_USERNAME = os.environ.get("S1_USERNAME")
S1_PASSWORD = os.environ.get("S1_PASSWORD")

# 로그인 후 근태/출퇴근 기록이 있는 메뉴를 찾기 위한 텍스트(부분 일치, 여러 후보 콤마로 구분 가능)
S1_MENU_TEXT_CANDIDATES = os.environ.get(
    "S1_MENU_TEXT", "근태,출퇴근,출입근태,근태관리"
).split(",")

# 엑셀 다운로드 버튼을 찾기 위한 텍스트(부분 일치, 여러 후보 콤마로 구분 가능)
S1_DOWNLOAD_TEXT_CANDIDATES = os.environ.get(
    "S1_DOWNLOAD_BUTTON_TEXT", "엑셀,다운로드,Excel,엑셀다운로드"
).split(",")

BACKEND_API_URL = os.environ.get("BACKEND_API_URL")  # 예: https://xxxx.supabase.co/rest/v1/attendance_raw
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY")  # Supabase service_role key

DEBUG = os.environ.get("DEBUG", "0") == "1"
DOWNLOAD_DIR = Path("downloads")
SCREENSHOT_DIR = Path("screenshots")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("s1-sync")


def kst_today_str() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d")


def shot(page, name: str):
    """디버그용 스크린샷 저장 (DEBUG=1 일 때만)"""
    if not DEBUG:
        return
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    log.info(f"[debug] 스크린샷 저장: {path}")


def find_and_click_by_text(page, candidates, timeout_ms=8000):
    """여러 후보 텍스트 중 화면에 보이는 첫 요소를 클릭. 못 찾으면 None 반환."""
    for text in candidates:
        text = text.strip()
        if not text:
            continue
        locator = page.get_by_text(text, exact=False).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.click()
            log.info(f"클릭 성공: '{text}'")
            return text
        except PWTimeout:
            continue
    return None


def login(page):
    log.info(f"로그인 페이지 접속: {S1_BASE_URL}")
    page.goto(S1_BASE_URL, wait_until="domcontentloaded")

    if not S1_USERNAME or not S1_PASSWORD:
        raise RuntimeError(
            "S1_USERNAME / S1_PASSWORD 환경변수가 설정되지 않았습니다. "
            "GitHub Secrets 또는 .env 파일을 확인하세요."
        )

    # 실제 로그인 폼 placeholder 기준 (2026-09 기준 확인됨)
    page.get_by_placeholder("아이디").fill(S1_USERNAME)
    page.get_by_placeholder("패스워드").fill(S1_PASSWORD)
    shot(page, "01_login_filled")

    page.get_by_role("button", name="로그인").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    shot(page, "02_after_login")

    # 로그인 실패 감지 (로그인 폼이 여전히 보이면 실패로 간주)
    if page.get_by_placeholder("패스워드").count() > 0 and page.get_by_placeholder("패스워드").is_visible():
        raise RuntimeError("로그인에 실패한 것 같습니다. 아이디/비밀번호를 확인하세요.")

    log.info("로그인 성공")


def go_to_attendance_menu(page):
    clicked = find_and_click_by_text(page, S1_MENU_TEXT_CANDIDATES)
    if not clicked:
        shot(page, "03_menu_not_found")
        raise RuntimeError(
            "근태/출퇴근 메뉴를 찾지 못했습니다. "
            "S1_MENU_TEXT 환경변수에 실제 메뉴 이름을 지정해주세요 "
            "(스크린샷: screenshots/03_menu_not_found.png 참고, DEBUG=1로 재실행)"
        )
    page.wait_for_load_state("networkidle", timeout=15000)
    shot(page, "04_attendance_menu")


def download_excel(page) -> Path:
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    with page.expect_download(timeout=20000) as download_info:
        clicked = find_and_click_by_text(page, S1_DOWNLOAD_TEXT_CANDIDATES)
        if not clicked:
            shot(page, "05_download_button_not_found")
            raise RuntimeError(
                "엑셀 다운로드 버튼을 찾지 못했습니다. "
                "S1_DOWNLOAD_BUTTON_TEXT 환경변수를 확인하세요 "
                "(스크린샷: screenshots/05_download_button_not_found.png 참고)"
            )
    download = download_info.value
    save_path = DOWNLOAD_DIR / f"attendance_{kst_today_str()}.xlsx"
    download.save_as(str(save_path))
    log.info(f"엑셀 다운로드 완료: {save_path}")
    return save_path


def excel_to_records(xlsx_path: Path) -> list[dict]:
    """엑셀을 그대로 읽어서 [{컬럼명: 값, ...}, ...] 형태로 변환 (헤더는 1행으로 가정)."""
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    records = []
    for row in rows[1:]:
        if row is None or all(v is None for v in row):
            continue
        record = {}
        for header, value in zip(headers, row):
            if isinstance(value, datetime):
                value = value.isoformat()
            record[header] = value
        records.append(record)
    return records


def send_to_backend(records: list[dict], source_file: str):
    if not BACKEND_API_URL or not BACKEND_API_KEY:
        log.warning(
            "BACKEND_API_URL / BACKEND_API_KEY가 설정되지 않아 전송을 건너뜁니다. "
            "로컬 테스트용으로 downloads/ 폴더의 파일만 확인하세요."
        )
        return

    payload = [
        {
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "source_file": source_file,
            "row": record,
        }
        for record in records
    ]

    headers = {
        "apikey": BACKEND_API_KEY,
        "Authorization": f"Bearer {BACKEND_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    resp = requests.post(BACKEND_API_URL, headers=headers, data=json.dumps(payload), timeout=30)
    if resp.status_code >= 300:
        raise RuntimeError(f"백엔드 전송 실패 ({resp.status_code}): {resp.text[:500]}")

    log.info(f"백엔드 전송 완료: {len(records)}건")


def main():
    with sync_playwright() as p:
        # headless=False로 두면 로컬에서 직접 눈으로 보며 디버깅할 수 있습니다.
        # GitHub Actions 등 서버 환경에서는 항상 headless=True로 강제합니다.
        headless = os.environ.get("HEADLESS", "1") == "1"
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            login(page)
            go_to_attendance_menu(page)
            xlsx_path = download_excel(page)
            records = excel_to_records(xlsx_path)
            log.info(f"엑셀에서 {len(records)}건의 행을 읽었습니다.")
            send_to_backend(records, source_file=xlsx_path.name)
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"동기화 실패: {e}")
        sys.exit(1)
