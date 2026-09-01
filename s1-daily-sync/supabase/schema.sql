-- Supabase(Postgres)에서 실행하세요: 프로젝트 대시보드 > SQL Editor > New query
-- 엑셀의 컬럼 구조를 몰라도 되도록, 각 행을 JSONB로 "그대로" 저장합니다.

create table if not exists attendance_raw (
  id bigint generated always as identity primary key,
  synced_at timestamptz not null default now(),
  source_file text,
  row jsonb not null
);

-- row 안의 값으로 검색/정렬할 때 유용한 인덱스
create index if not exists idx_attendance_raw_row on attendance_raw using gin (row);
create index if not exists idx_attendance_raw_synced_at on attendance_raw (synced_at desc);

-- Row Level Security 활성화
alter table attendance_raw enable row level security;

-- 1) 서버(GitHub Actions, service_role 키)는 항상 전체 접근 가능 (RLS와 무관하게 우회됨) -> 별도 정책 불필요

-- 2) 브라우저(익명 anon 키)에서는 "읽기만" 허용 -> 뷰어 페이지(web/index.html)에서 조회할 때 사용
create policy "allow anon read"
  on attendance_raw
  for select
  to anon
  using (true);

-- 익명 사용자는 쓰기/수정/삭제 불가 (정책을 만들지 않으면 기본적으로 차단됨)
