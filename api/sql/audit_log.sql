-- Bảng audit_log (AD-7, AD-16, story 2.2). Idempotent: chạy lại không đổi gì.
--
-- Bảy trường tối thiểu của AD-16 là cột thật để lọc và đánh index; số liệu
-- riêng của từng loại sự kiện (token, model, USD) nằm trong `chi_tiet` jsonb,
-- nên thêm một loại sự kiện (3.6) không phải sửa lược đồ. `thoi_diem` là
-- timestamptz, ghi từ chuỗi ISO-8601 UTC mà `core.audit.thoi_diem_utc` sinh.
CREATE TABLE IF NOT EXISTS audit_log (
    id              bigserial PRIMARY KEY,
    thoi_diem       timestamptz NOT NULL,
    tier            text NOT NULL,
    event           text NOT NULL,
    act             text,
    role            text,
    space           text NOT NULL,
    policy_version  text NOT NULL,
    hyperedge_ids   text[] NOT NULL DEFAULT '{}',
    chi_tiet        jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Đường đọc chính của FR-25/FR-30: tổng theo space và loại sự kiện, theo thời gian.
CREATE INDEX IF NOT EXISTS audit_log_space_event_thoi_diem_idx
    ON audit_log (space, event, thoi_diem);
