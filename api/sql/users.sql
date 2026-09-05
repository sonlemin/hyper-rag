-- Bảng users (AD-7, SPINE :223, story 3.1). Idempotent: chạy lại không đổi gì.
--
-- Trạng thái ứng dụng chỉ ở Postgres. `config/tai-khoan.yaml` là *nguồn*, bảng
-- này là nơi trạng thái sống: `api/tai_khoan.py` đồng bộ một chiều từ file
-- xuống bảng lúc khởi động, và Epic 5 (breakglass_requests/grants) cùng
-- `audit_log` khóa ngoại về `account` chứ không về một dòng YAML.
--
-- `account` là khóa chính vì nó là `real_account` của ngữ cảnh quyền (AD-3) và
-- `sub` của JWT: một tài khoản hai dòng là hai câu trả lời cho cùng một người
-- hỏi. `mat_khau_hash` là bcrypt nguyên văn (60 ký tự), không bao giờ có cột
-- nào cho mật khẩu thô.
--
-- `group_name` dùng chung danh mục giá trị với slot `owner` của hyperedge
-- (SPINE :223) và với `config/nhom-phu-trach.yaml`. Nó **không** vào khóa lọc
-- và không quyết định ai đọc được gì; quyền vẫn là vai × loại nội dung × scope
-- (AD-4). Không có ràng buộc khóa ngoại sang bảng nhóm vì bảng nhóm là file
-- YAML chứ không phải một bảng.
--
-- `demo` và `admin` là hai cột riêng, không phải hai mức của một cột (spine
-- :105): Admin là vai quản trị của PRD 1.5, tài khoản demo là tài khoản trình
-- diễn. Mặc định `false` ở cả hai, đúng chiều fail-closed.
CREATE TABLE IF NOT EXISTS users (
    account         text PRIMARY KEY,
    mat_khau_hash   text NOT NULL,
    role            text NOT NULL,
    group_name      text NOT NULL,
    khong_gian      text NOT NULL,
    demo            boolean NOT NULL DEFAULT false,
    admin           boolean NOT NULL DEFAULT false,
    cap_nhat        timestamptz NOT NULL DEFAULT now()
);
