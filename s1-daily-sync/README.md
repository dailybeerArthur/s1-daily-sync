# S1(SESP) 근태 데이터 매일 자동 동기화

s1esp.com 관리자사이트에서 근태(출퇴근) 엑셀을 매일 새벽 자동으로 다운로드해서,
새로 만든 백엔드(Supabase)로 **원본 그대로** 전송하는 시스템입니다.

```
[s1esp.com 로그인] → [근태 메뉴 → 엑셀 다운로드] → [엑셀을 JSON으로 변환]
        → [Supabase에 그대로 저장] → [web/index.html 에서 조회]
                     ↑
      GitHub Actions가 매일 새벽 자동 실행
```

## 왜 이 구성인가요?

- **GitHub Actions**: 서버를 따로 두지 않아도, 정해진 시간에 자동으로 스크립트를 실행해주는 무료 클라우드 스케줄러입니다.
- **Supabase**: 코드 없이 몇 분 만에 데이터베이스 + API가 준비되는 무료 서비스입니다. "새로 만들 프로그램"의 저장소 역할을 합니다.
- **Playwright**: 실제 브라우저처럼 s1esp.com에 로그인해서 클릭까지 대신 해주는 자동화 도구입니다.

## 0. 시작 전에 꼭 확인하세요

- 이 자동화는 **회사 계정으로 관리자사이트에 로그인해서 데이터를 내려받는** 방식입니다. 회사 정보보안 정책상 자동 로그인/크롤링이 허용되는지 담당 부서(IT/보안팀)에 먼저 확인하시는 걸 권합니다.
- 로그인 아이디/비밀번호는 **절대 코드나 채팅에 직접 입력하지 마시고**, 아래 안내대로 GitHub Secrets(암호화 저장소)에만 넣어주세요.

## 1. Supabase 설정 (5분)

1. [supabase.com](https://supabase.com) 무료 가입 → New Project 생성
2. 프로젝트 생성 후 왼쪽 메뉴 **SQL Editor** → New query 에서 `supabase/schema.sql` 내용을 붙여넣고 실행
3. 왼쪽 메뉴 **Settings → API** 에서 아래 3개 값을 메모해두세요
   - `Project URL` (예: `https://abcd1234.supabase.co`)
   - `anon public` 키 (뷰어 페이지용, 읽기 전용)
   - `service_role` 키 (자동화 스크립트용, 절대 공개 노출 금지)

## 2. GitHub 저장소 만들기

1. GitHub에 새 저장소 생성 (Private 권장 — 회사 데이터가 들어가므로)
2. 이 폴더(`s1-daily-sync`) 전체를 그 저장소에 업로드/푸시

```bash
cd s1-daily-sync
git init
git add .
git commit -m "S1 근태 자동 동기화"
git branch -M main
git remote add origin <본인 저장소 URL>
git push -u origin main
```

## 3. GitHub Secrets 등록 (자동 로그인 정보)

저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에서 아래 항목을 등록하세요.

| Secret 이름 | 값 |
|---|---|
| `S1_USERNAME` | s1esp.com 관리자 로그인 아이디 |
| `S1_PASSWORD` | s1esp.com 관리자 로그인 비밀번호 |
| `BACKEND_API_URL` | `https://<Project URL>/rest/v1/attendance_raw` |
| `BACKEND_API_KEY` | Supabase의 **service_role** 키 |

같은 화면의 **Variables** 탭에서 (선택, 필요시만) 아래도 등록할 수 있습니다.

| Variable 이름 | 값 | 언제 필요한가 |
|---|---|---|
| `S1_MENU_TEXT` | 예: `근태,출퇴근` | 근태 메뉴 이름이 기본값과 다를 때 |
| `S1_DOWNLOAD_BUTTON_TEXT` | 예: `엑셀,다운로드` | 다운로드 버튼 텍스트가 다를 때 |

## 4. 첫 실행은 반드시 "로컬 테스트"로 먼저 해보세요

로그인 후 근태 메뉴/다운로드 버튼의 실제 이름은 회사마다 다를 수 있어서,
스크립트에는 가장 흔한 이름들(`근태`, `출퇴근`, `엑셀`, `다운로드` 등)을 기본값으로 넣어뒀습니다.
실제 화면과 다르면 조정이 필요할 수 있으니, 아래처럼 본인 컴퓨터에서 먼저 확인해보세요.

```bash
cd s1-daily-sync
python -m venv .venv && source .venv/bin/activate   # Windows는 .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# .env 파일을 열어서 실제 아이디/비밀번호/Supabase 정보를 채워넣으세요

export $(cat .env | xargs)   # Windows는 별도 방법 필요 (또는 python-dotenv 사용)
export HEADLESS=0            # 브라우저 창을 직접 보면서 확인
python scripts/sync_attendance.py
```

- 성공하면: `downloads/` 폴더에 엑셀 파일이 생기고, Supabase `attendance_raw` 테이블에 데이터가 쌓입니다.
- 실패하면: `screenshots/` 폴더의 스크린샷을 열어서 어느 단계에서 막혔는지 확인하고,
  `.env`의 `S1_MENU_TEXT` / `S1_DOWNLOAD_BUTTON_TEXT` 값을 실제 화면에 맞게 수정한 뒤 다시 실행하세요.

## 5. 자동 실행 켜기

로컬 테스트가 성공하면 끝입니다. GitHub Actions가 매일 **KST 06:00**에 자동으로 실행됩니다
(`.github/workflows/daily-sync.yml`의 `cron` 값으로 시간을 바꿀 수 있어요 — UTC 기준이라 KST보다 9시간 빼서 넣으면 됩니다).

- 저장소 → **Actions** 탭에서 실행 기록/성공 여부를 확인할 수 있습니다.
- 지금 바로 테스트하고 싶다면 Actions 탭 → 왼쪽 워크플로 선택 → **Run workflow** 버튼으로 즉시 실행할 수 있습니다.
- 실패하면 스크린샷이 Actions 실행 결과의 "Artifacts"에 자동 첨부됩니다.

## 6. 결과 확인 (뷰어 페이지)

`web/index.html`을 열어 아래 두 값을 본인 것으로 바꾸면, 매일 쌓인 데이터를 표로 볼 수 있습니다.

```js
const SUPABASE_URL = "https://YOUR_PROJECT.supabase.co";
const SUPABASE_ANON_KEY = "YOUR_ANON_PUBLIC_KEY"; // service_role 아님, 공개돼도 되는 읽기전용 키
```

이 파일은 더블클릭으로 열어도 되고, GitHub Pages/Netlify/Vercel에 올리면 웹 주소로도 볼 수 있습니다.
원하시면 이후에 Supabase 값을 알려주실 때 제가 이 페이지를 정식 대시보드(공유 가능한 링크)로 만들어드릴 수도 있어요.

## 7. 나중에 DailyHub와 연결하고 싶다면

지금은 별도 저장소(Supabase)에 데이터를 쌓는 구조지만, 나중에 DailyHub 대시보드에도 반영하고 싶으시면
DailyHub를 만든 분에게 "Supabase의 `attendance_raw` 테이블 데이터를 어떻게 가져다 쓸 수 있는지" 문의하시면 됩니다
(DailyHub 쪽에서 이 Supabase REST API를 그대로 호출해서 읽어가는 방식이 가장 간단합니다).

## 파일 구성

```
s1-daily-sync/
├── README.md                          # 이 문서
├── requirements.txt                   # 파이썬 패키지 목록
├── .env.example                       # 로컬 테스트용 환경변수 예시
├── scripts/
│   └── sync_attendance.py             # 핵심 자동화 스크립트
├── supabase/
│   └── schema.sql                     # Supabase 테이블 생성 SQL
├── web/
│   └── index.html                     # 동기화 결과를 보여주는 간단한 뷰어
└── .github/workflows/
    └── daily-sync.yml                 # 매일 자동 실행 설정 (GitHub Actions)
```
