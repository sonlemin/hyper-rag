import { MICROCOPY, type KhoaMicrocopy } from "./microcopy";

// Nhãn hiển thị tiếng Việt của hai danh mục mà API trả về dưới dạng khóa
// snake_case: 8 vai slot (`core/slots.py`) và 13 loại nội dung
// (`config/hang-do-nhay.yaml`). Khuôn của `NHAN_VAI` trong `api/phien.ts`:
// khóa lạ hiện **nguyên khóa**, vì một nhãn đoán là một chỗ để UI nói khác với
// dữ liệu mà server trả về.
//
// `tests/test_web_khung.py` nhóm (11) ghim **khóa** của cả hai bảng với nguồn
// của chúng. Ghim khóa chứ không ghim giá trị, và chỗ lệch dưới đây là cố ý.

/** Nhãn 8 vai slot. Khóa đúng bằng `core.slots.SLOT_ROLES`, đúng thứ tự đó.
 *
 *  `remediation` là "hành động khắc phục" theo EXPERIENCE.md (bảng Voice and
 *  Tone: "[hành động khắc phục: che]"), trong khi `core/facts.py` gọi nó là
 *  "cách xử lý". Chỗ lệch một ô đó là **cố ý và cố định**: nhãn ở `core/` đi
 *  thẳng vào `PROMPT_TRICH_XUAT` mà `tests/test_cham_trich_xuat.py` so từng
 *  byte với ba vòng đo đã trả tiền, nên sửa nó là làm hỏng mẫu số của chương 4;
 *  nhãn ở đây là nhãn hiển thị, nguồn chuẩn là EXPERIENCE.md. Đừng "sửa cho
 *  khớp" một trong hai.
 */
export const NHAN_SLOT: Record<string, string> = {
  subject: "chủ thể",
  symptom: "triệu chứng",
  cause: "nguyên nhân",
  condition: "điều kiện",
  remediation: "hành động khắc phục",
  source: "nguồn",
  time: "thời gian",
  owner: "người phụ trách",
};

/** Danh mục 8 vai, **dẫn xuất** từ bảng nhãn chứ không chép lại tám tên.
 *
 *  Thứ tự bằng thứ tự khai của `NHAN_SLOT`, tức bằng `SLOT_ROLES` (test ghim).
 *  Dùng để dựng tập dấu che hợp lệ (`app/dau_che.ts`) và để kiểm hình
 *  `masked_slots` của một citation (`api/hoi_dap.ts`). Hai bản của cùng một
 *  danh mục trong cùng một thư mục là hai bản trôi khỏi nhau ở lần sửa đầu. */
export const VAI_SLOT: readonly string[] = Object.keys(NHAN_SLOT);

export function nhan_slot(vai: string): string {
  return NHAN_SLOT[vai] ?? vai;
}

/** Nhãn 13 loại nội dung. Khóa đúng bằng `ranks` của `config/hang-do-nhay.yaml`.
 *
 *  Không mang hạng độ nhạy và không sắp theo hạng: hạng là dữ liệu của tầng
 *  quyền, còn đây chỉ là chữ hiện trên một hàng nguồn. Mức mà vai hiện tại có
 *  với nguồn nằm ở badge, và nó đến từ `level` của chính citation. */
export const NHAN_LOAI: Record<string, string> = {
  faq: "Hỏi đáp thường gặp",
  tai_lieu_san_pham: "Tài liệu sản phẩm",
  sop: "Quy trình chuẩn",
  troubleshooting: "Hướng dẫn khắc phục",
  runbook: "Quy trình vận hành",
  known_issue: "Lỗi đã biết",
  vong_doi_ticket: "Vòng đời ticket",
  canh_bao: "Cảnh báo giám sát",
  bao_cao_su_co: "Báo cáo sự cố",
  postmortem: "Phân tích sau sự cố",
  log: "Log hệ thống",
  cmdb: "Sổ tài sản CMDB",
  bi_mat_ha_tang: "Bí mật hạ tầng",
};

export function nhan_loai(loai: string): string {
  return NHAN_LOAI[loai] ?? loai;
}

/** Nhãn 3 scope tài liệu. Khóa đúng bằng **hợp** các `scopes:` của mọi
 *  `config/policy-*.yaml`.
 *
 *  Nguồn ghim là bốn bảng chính sách chứ không phải corpus: scope là thành phần
 *  trái của khóa lọc, nên một scope không vai nào chạm tới thì không vai nào có
 *  khóa cho nó, tài liệu của nó là L0 với tất cả, và **không citation nào mang
 *  được nó**. Tập scope hiện được lên một cite-row đúng bằng hợp đó.
 *
 *  Khóa lạ hiện nguyên khóa như hai bảng trên: scope đến từ frontmatter tài
 *  liệu chứ không từ một danh mục đóng ở tầng nạp, nên một space mới nạp một
 *  scope mới thì cite-row hiện `khach_hang_c` chứ không hiện một nhãn đoán. */
export const NHAN_SCOPE: Record<string, string> = {
  noi_bo: "nội bộ",
  khach_hang_a: "khách hàng A",
  khach_hang_b: "khách hàng B",
};

export function nhan_scope(scope: string): string {
  return NHAN_SCOPE[scope] ?? scope;
}

/** Tiền tố khóa microcopy của dòng mô tả vùng quyền một vai: `mo_ta_vai_<vai>`. */
export const TIEN_TO_MO_TA_VAI = "mo_ta_vai_";

/** Dòng mô tả vùng quyền của một vai, hay `null` nếu chưa ai viết cho vai đó.
 *
 *  Hàm thuần và ở đây chứ không trong `MenuXemNhu.tsx`: nó cùng họ với
 *  `NHAN_VAI` và `nhan_slot` (một khóa từ API đổi thành chữ hiển thị, khóa lạ
 *  hiện nguyên khóa), và để nó trong một component `"use client"` buộc trang
 *  mẫu phải import từ `@/khung/MenuXemNhu` để dùng một hàm không liên quan gì
 *  tới component ấy.
 *
 *  Chuỗi tĩnh ở `microcopy.json` chứ không đến từ `GET /auth/vai`: tuyến ấy trả
 *  **chỉ tên vai**, vì một tài khoản demo không cần đọc bảng quyền để bấm một
 *  nút. Chữ "thường" trong cả năm câu là cố ý - mức tiết lộ là hàm của vai ×
 *  loại nội dung × scope (AD-4), không phải một thuộc tính của vai, nên một câu
 *  khẳng định "vai này thấy L2" sẽ sai ngay ở bảng chính sách kế tiếp.
 *
 *  Vai chưa có mô tả hiện **mục không kèm mô tả** thay vì một câu đoán, cùng
 *  luật khóa-lạ-hiện-nguyên-khóa của `nhan_vai`. */
export function mo_ta_vai(vai: string): string | null {
  const khoa = `${TIEN_TO_MO_TA_VAI}${vai}` as KhoaMicrocopy;
  return khoa in MICROCOPY ? MICROCOPY[khoa] : null;
}
