// Cửa duy nhất của tuyến hỏi đáp phía `web/` (story 4.3). Hợp đồng với `api/`
// khai thành hằng ở đây rồi `tests/test_web_khung.py` ghim từng cái với chính
// nguồn `api/hoi_dap.py` và `api/main.py` - cùng khuôn mà 4.2 ghim ba trường
// đăng nhập, và vì cùng một lý do: e2e mock trọn tuyến nên nó xanh với bất kỳ
// tên nào, còn phía `api/` không biết `web/` gửi gì.

import { VAI_SLOT } from "@/nhan";

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
 *  khỏi ngữ cảnh ngay ở tầng lọc, nên không có id nào để tra.
 *
 *  Bản chép thứ hai của `adapters.trich_dan.MUC_TRICH_DAN`, và
 *  `tests/test_web_khung.py` so **giá trị** hai bên - cùng khuôn với
 *  `KHOA_TRICH_DAN` ngay trên. Phía `api/` tập ấy **dẫn xuất** từ ngưỡng
 *  namespace chứ không viết tay, nên hạ `NAMESPACE_MIN_LEVEL` của `hyperedges`
 *  xuống là ở đó có thêm một mức mà `web/` từ chối thành `ENVELOPE_LA` cho mọi
 *  lượt; một hằng chỉ để đọc mà không ai ghim là đúng kiểu hỏng story này dựng
 *  ra để chặn. */
export const MUC_TRICH_DAN = ["L1", "L2"] as const;

export type MucTietLo = (typeof MUC_TRICH_DAN)[number];

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

/** Tiền tố của **mã hiển thị** một nguồn trên cite-row.
 *
 *  Id hyperedge thật (`he-` + 24 hex) không bao giờ vào DOM: nó không đọc được
 *  và nó là khóa tra của kho. `HE-nn` đánh theo thứ tự citation **trong lượt**,
 *  và 4.6 dùng lại đúng mã đó cho vòng đồ thị cùng chú thích hover. */
export const TIEN_TO_MA_HIEN_THI = "HE-";

/** Mã hiển thị của citation thứ `i` (0-based): `HE-01`, `HE-02`, ...
 *
 *  Hai chữ số, tràn thì nhiều hơn (không cắt): một lượt 100 nguồn vẫn phải phân
 *  biệt được từng hàng, và story 3.8 cố ý **không** đặt trần cho số cite-row. */
export function ma_hien_thi(i: number): string {
  return `${TIEN_TO_MA_HIEN_THI}${String(i + 1).padStart(2, "0")}`;
}

/** Chuỗi không rỗng sau khi bỏ khoảng trắng. */
function chuoi_that(gia_tri: unknown): boolean {
  return typeof gia_tri === "string" && gia_tri.trim() !== "";
}

/** Một mục của `citations` có đúng hình một citation không.
 *
 *  Phép kiểm thứ tư của story 4.3 chỉ hỏi `citations` có phải mảng; từ 4.4 mỗi
 *  mục thành một hàng mang badge mức, nên một `level` lạ sẽ vẽ ra một badge nói
 *  sai về quyền. Fail-closed ở đây rẻ hơn một hàng nói dối.
 *
 *  Năm phép kiểm, một-một với `TrichDan.__post_init__` phía `api/`, và hai
 *  trong số đó đi qua chính hai hằng đã ghim với `adapters/trich_dan.py`:
 *  - đủ sáu khóa `KHOA_TRICH_DAN` (thừa khóa thì bỏ qua: `api/` khai tập đóng,
 *    một khóa lạ là một trường mới chứ không phải một hàng sai);
 *  - `id` là chuỗi không rỗng. Predicate này hứa `id: string` cho mọi nơi gọi
 *    sau nó, và `null`, `0` hay `""` đều lọt nếu chỉ hỏi khóa có mặt. 4.4
 *    không đọc `id` (cite-row dùng `ma_hien_thi`), nhưng 4.6 khóa vòng đồ thị
 *    lên nó, và một phép kiểm hình thiếu đúng trường mà story sau tin là cách
 *    rẻ nhất để đẩy một lỗi sang một story không gây ra nó;
 *  - `level` nằm trong `MUC_TRICH_DAN` - L0 không có mặt, và `"L3"` là một
 *    badge không ai đọc được;
 *  - `scope` và `content_type` là chuỗi không rỗng (chúng hiện thẳng lên hàng);
 *  - `masked_slots` là mảng vai nằm trong danh mục 8 vai, và `owner_group` là
 *    chuỗi không rỗng hoặc `null`. */
export function la_trich_dan(muc: unknown): muc is TrichDan {
  if (typeof muc !== "object" || muc === null) return false;
  const t = muc as Record<string, unknown>;
  for (const khoa of KHOA_TRICH_DAN) {
    if (!(khoa in t)) return false;
  }
  if (!chuoi_that(t.id)) return false;
  if (!MUC_TRICH_DAN.includes(t.level as MucTietLo)) return false;
  if (!chuoi_that(t.scope) || !chuoi_that(t.content_type)) return false;
  if (!Array.isArray(t.masked_slots)) return false;
  if (!t.masked_slots.every((v) => typeof v === "string" && VAI_SLOT.includes(v))) return false;
  return t.owner_group === null || chuoi_that(t.owner_group);
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
 *  - `citations` là mảng **và mọi mục có đúng hình citation** (story 4.4): mỗi
 *    mục nay thành một hàng mang badge mức, nên một mục sai hình là một hàng
 *    nói sai về quyền chứ không phải một ô trống;
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
  if (!t.citations.every(la_trich_dan)) return false;
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
