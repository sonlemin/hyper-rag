-- Hai bảng break-glass của ERD (AD-7, FR-20, story 5.1). Idempotent: chạy lại
-- không đổi gì. Chạy **sau** `users.sql` vì `act` khóa ngoại về `users(account)`
-- - chủ của một yêu cầu là một tài khoản thật, không phải một chuỗi tự do.
-- Khóa ngoại **cố ý không có ON DELETE**: `api/tai_khoan.py::dong_bo` không bao
-- giờ xóa tài khoản, và gỡ một tài khoản là một thao tác có chủ đích phải tự
-- xử lý hàng chờ và grant của nó, không phải một phép xóa dây chuyền im lặng.
--
-- `breakglass_requests` là hàng chờ của owner. `act`/`role`/`space` chép từ
-- **ngữ cảnh quyền** lúc xin, không từ thân request: yêu cầu bind cặp
-- (tài khoản, vai), và 5.2 sẽ cấp grant cho đúng cặp đó; `role` là **ảnh chụp**
-- lúc xin, không đối chiếu lại với seed về sau. `scope`/`content_type`
-- tách từ khóa quyền của hyperedge, `nhom_duyet` tra từ bảng nhóm phụ trách
-- của chính adapter graph (cùng bảng sinh dấu che `[owner:<nhóm>]`). `k` và
-- `thoi_han_phut` chép hai hằng của `core/break_glass.py` vào từng hàng để
-- người duyệt thấy đúng con số sẽ có hiệu lực, kể cả khi hằng đổi sau này.
-- `ly_do` là văn bản tự do của người xin và **chỉ ở đây**, không vào
-- `audit_log`. `ly_do_tu_choi` và `xu_ly_boi` để null, 5.2 điền.
CREATE TABLE IF NOT EXISTS breakglass_requests (
    id              text PRIMARY KEY,
    act             text NOT NULL REFERENCES users(account),
    role            text NOT NULL,
    space           text NOT NULL,
    hyperedge_id    text NOT NULL,
    scope           text NOT NULL,
    content_type    text NOT NULL,
    nhom_duyet      text NOT NULL,
    ly_do           text NOT NULL,
    k               integer NOT NULL,
    thoi_han_phut   integer NOT NULL,
    trang_thai      text NOT NULL,
    tao_luc         timestamptz NOT NULL,
    cap_nhat        timestamptz NOT NULL,
    ly_do_tu_choi   text,
    xu_ly_boi       text
);

-- Luật trùng tầng kho: một tài khoản chỉ có **một** yêu cầu đang chờ cho một
-- hyperedge, bất kể vai. Index một phần trên `trang_thai = 'cho_duyet'` nên
-- yêu cầu đã hủy/duyệt/từ chối không chặn xin lại; phép kiểm trước insert ở
-- `api/break_glass.py` cho cùng mã lỗi, index này bắt ca hai request chen nhau.
-- Tên index là hằng `api.break_glass.INDEX_CHO_DUYET`: chỉ vi phạm mang đúng
-- tên này mới được đọc thành 409 "đang chờ".
CREATE UNIQUE INDEX IF NOT EXISTS breakglass_requests_cho_duyet_idx
    ON breakglass_requests (act, hyperedge_id)
    WHERE trang_thai = 'cho_duyet';

-- Đường đọc "yêu cầu của tôi", mới nhất trước.
CREATE INDEX IF NOT EXISTS breakglass_requests_act_tao_luc_idx
    ON breakglass_requests (act, tao_luc DESC);

-- Hàng chờ của owner (5.2): yêu cầu đang chờ theo nhóm duyệt, cũ nhất trước.
CREATE INDEX IF NOT EXISTS breakglass_requests_nhom_duyet_cho_idx
    ON breakglass_requests (nhom_duyet, tao_luc)
    WHERE trang_thai = 'cho_duyet';

-- `breakglass_grants` dựng ở story này để phép kiểm "grant còn hạn" đứng lên
-- và để 5.2 có chỗ ghi; **không có đường ghi nào** ở 5.1 ngoài helper của bộ
-- test. Grant bind cặp (`act`, `role`): ở vai khác nó ngủ (5.3), nên phép kiểm
-- trùng của đường xin so cả `role`. `hyperedge_ids` là mảng vì grant duyệt có
-- thể phủ k hyperedge lân cận (hôm nay k = 0, mảng đúng một phần tử).
-- `request_id` null cho phép grant cấp chủ động không qua yêu cầu (5.2).
-- **Một nguồn giờ cho `expires_at`, và đó là giờ của Postgres** (quyết định
-- chốt ở 5.1, ADR-019): phép kiểm "grant còn hạn" của 5.1 so `expires_at >
-- now()`, nên 5.2 phải ghi `expires_at` bằng chính đồng hồ ấy ngay trong câu
-- INSERT (`now() + make_interval(mins => $n)`), không tính ở tiến trình `api`
-- rồi truyền vào - hai đồng hồ là một grant sống theo máy này mà chết theo máy
-- kia. `tao_luc DEFAULT now()` cùng nguồn.
CREATE TABLE IF NOT EXISTS breakglass_grants (
    id              text PRIMARY KEY,
    request_id      text REFERENCES breakglass_requests(id),
    act             text NOT NULL REFERENCES users(account),
    role            text NOT NULL,
    space           text NOT NULL,
    hyperedge_ids   text[] NOT NULL,
    expires_at      timestamptz NOT NULL,
    cap_boi         text NOT NULL,
    tao_luc         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS breakglass_grants_act_role_expires_idx
    ON breakglass_grants (act, role, expires_at);
