// Cửa duy nhất của tuyến hỏi đáp phía `web/` (story 4.3). Hợp đồng với `api/`
// khai thành hằng ở đây rồi `tests/test_web_khung.py` ghim từng cái với chính
// nguồn `api/hoi_dap.py` và `api/main.py` - cùng khuôn mà 4.2 ghim ba trường
// đăng nhập, và vì cùng một lý do: e2e mock trọn tuyến nên nó xanh với bất kỳ
// tên nào, còn phía `api/` không biết `web/` gửi gì.

import { goi, LoiApi } from "./goi";

/** Mã của **client** cho một thân 200 sai lược đồ envelope; không phải mã của
 *  `api/` (cùng loại với `MA_MANG` của `goi.ts`).
 *
 *  Mã riêng chứ không dùng lại `MANG`: hai nguyên nhân khác hẳn nhau và người
 *  đọc `data-ma-loi` phải phân biệt được - `MANG` là không tới được máy chủ hay
 *  thân không phải JSON (proxy trả HTML), còn `ENVELOPE_LA` là máy chủ trả lời
 *  nhưng lược đồ đã trôi. Cùng tinh thần với việc 4.2 tách hai nghĩa của 401
 *  bằng mã chứ không chỉ bằng status. */
export const MA_ENVELOPE_LA = "ENVELOPE_LA";

/** Tuyến hỏi đáp (`@cua_dong.post` của `api/main.py`), cần Bearer. */
export const TUYEN_HOI_DAP = "/hoi-dap";

/** Trường **duy nhất** của thân request. `ThanHoiDap` khai `extra="forbid"`,
 *  nên một tên lệch là 422 cho mọi câu hỏi chứ không phải một lỗi lẻ. */
export const TRUONG_CAU_HOI = "cau_hoi";

/** Năm khóa cấp một của envelope, thứ tự AD-8 (`api.hoi_dap.KHOA_ENVELOPE`). */
export const KHOA_ENVELOPE = ["answer", "refused", "citations", "graph", "meta"] as const;

/** Ba trường của `meta`, tập đóng (`api.hoi_dap.KHOA_META`). */
export const KHOA_META = ["role", "space", "policy_version"] as const;

/** Sáu khóa đóng của một citation (`adapters.trich_dan.KHOA_TRICH_DAN`).
 *
 *  Story 4.3 chỉ **đếm** `citations`; khai đủ sáu ở đây để 4.4 lắp cite-row vào
 *  mà không phải đổi hợp đồng, và không component nào của 4.3 đọc quá `length`. */
export const KHOA_TRICH_DAN = [
  "id",
  "level",
  "scope",
  "content_type",
  "masked_slots",
  "owner_group",
] as const;

/** Hai mức mà một citation mang được. L0 **không có mặt**: hyperedge L0 vắng
 *  khỏi ngữ cảnh ngay ở tầng lọc, nên không có id nào để tra. */
export type MucTietLo = "L1" | "L2";

export type TrichDan = {
  id: string;
  level: MucTietLo;
  scope: string;
  content_type: string;
  masked_slots: string[];
  owner_group: string | null;
};

export type MetaLuot = {
  role: string;
  space: string;
  policy_version: string;
};

export type DoThi = {
  nodes: unknown[];
  edges: unknown[];
};

export type Envelope = {
  /** `null` ở lượt từ chối (AD-8); câu người dùng đọc là `MICROCOPY.tu_choi`. */
  answer: string | null;
  refused: boolean;
  citations: TrichDan[];
  graph: DoThi;
  meta: MetaLuot;
};

/** Chuỗi không rỗng sau khi bỏ khoảng trắng. */
function chuoi_that(gia_tri: unknown): boolean {
  return typeof gia_tri === "string" && gia_tri.trim() !== "";
}

/** Thân trả về có đúng hình envelope không.
 *
 *  Một thân sai hình là **lỗi hệ thống**, không phải một lượt trả lời rỗng: nếu
 *  UI vẽ một bong bóng trắng cho nó thì người xem đọc thành "hệ thống không có
 *  gì để nói", tức đúng chỗ mà NFR-10 đòi phân biệt được.
 *
 *  Năm phép kiểm, mỗi phép chặn một ca đã thấy được:
 *  - đủ năm khóa `KHOA_ENVELOPE`;
 *  - `refused` là **bool**. Ca nặng nhất của cả hàm: `"false"` là chuỗi rỗng
 *    hay không cũng **truthy** trong JavaScript, nên một câu trả lời thật sẽ
 *    render thành template từ chối FR-16 mà không gì bắt được;
 *  - `answer` là `null` **khi và chỉ khi** `refused` (AD-8). `refused: false`
 *    với `answer` rỗng hay toàn khoảng trắng là một bong bóng trắng rỗng;
 *  - `citations` là mảng, để `length` có nghĩa;
 *  - `meta` có đủ ba khóa `KHOA_META` là chuỗi, và `role` không rỗng - dòng
 *    meta nói "trả lời theo quyền X", một `role` rỗng ra "theo quyền  · 2 trích
 *    dẫn". Đi qua chính hằng `KHOA_META` chứ không gõ tay từng tên: một hằng chỉ
 *    để pytest so là một hằng chết, và tập đóng ba trường phải là **cơ chế**. */
export function la_envelope(than: unknown): than is Envelope {
  if (typeof than !== "object" || than === null) return false;
  const t = than as Record<string, unknown>;
  for (const khoa of KHOA_ENVELOPE) {
    if (!(khoa in t)) return false;
  }
  if (typeof t.refused !== "boolean") return false;
  if (t.refused ? t.answer !== null : !chuoi_that(t.answer)) return false;
  if (!Array.isArray(t.citations)) return false;
  const meta = t.meta as Record<string, unknown> | null;
  if (typeof meta !== "object" || meta === null) return false;
  for (const khoa of KHOA_META) {
    if (typeof meta[khoa] !== "string") return false;
  }
  return chuoi_that(meta.role);
}

/** Hỏi một câu. Trả envelope đã kiểm hình; ném `LoiApi` cho mọi ca hỏng.
 *
 *  **Không trần thời gian** (NFR-08 không đặt SLA, EXPERIENCE.md State Patterns):
 *  không `setTimeout`, không `AbortSignal.timeout`. Một đợt hỏi thật đã đo tới
 *  hàng chục giây, nên một trần "cho chắc" cắt đúng những câu chậm nhất.
 *  `tests/test_web_khung.py` quét cả `web/src` để giữ luật đó. */
export async function hoi(cau_hoi: string): Promise<Envelope> {
  const than = await goi<unknown>(TUYEN_HOI_DAP, { than: { [TRUONG_CAU_HOI]: cau_hoi } });
  if (!la_envelope(than)) throw new LoiApi(MA_ENVELOPE_LA, 200);
  return than;
}
