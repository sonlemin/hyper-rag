// Tách một câu trả lời thành mảnh chữ và mảnh slab (story 4.4, FR-15).
//
// Ba hàm dưới đây là **hàm thuần** (không DOM, không React, không state), nhưng
// dự án **không có runner unit test cho TypeScript** và thêm một cái là Ask
// First của spec 4.1, nên chúng được chấm hai đường gián tiếp: `pytest` đọc
// nguồn file này và ghim ngữ pháp dấu che với `core/masking.py`, còn Playwright
// chấm hành vi qua DOM thật ở `web/e2e/cite-row.spec.ts`. Viết chúng thuần vẫn
// đáng vì đó là thứ làm ca "chuỗi ngoặc không phải dấu che" chấm được bằng một
// phép so văn bản chứ không bằng một phép đọc màu.
//
// Slab là **hiển thị best-effort trên `answer`** (chốt brief §6: không test an
// ninh nào trên `answer`), nên một chuỗi không nhận ra thì **giữ nguyên văn** -
// không bao giờ xóa, không bao giờ đoán.
//
// **Phạm vi: ba họ dấu che của vai slot, không phải cả bốn họ của `core/`.**
// `core/masking.py` sinh bốn họ; ba họ ở đây là `[<vai>:masked]` cho bảy vai,
// `[owner:group]`, và `[owner:<nhóm>]`. Hai họ còn lại - `[description:l2_only]`
// (`MASK_REASON_L2_ONLY`) và `[neighbor_id:no_key]` (`MASK_REASON_NO_KEY`) - cố
// ý **để nguyên văn**: khối `Always` của spec 4.4 chốt đúng ba họ và chốt "mọi
// chuỗi ngoặc vuông khác là chữ thường". Chúng tới được `answer` thật (cả hai
// nằm trong `_VI_DU_DAU_CHE` của `adapters/tra_loi.py` mà prompt dạy model chép
// nguyên), nên đây là một quyết định chứ không phải một chỗ bỏ sót, và
// `tests/test_web_khung.py` nêu đích danh hai họ bị loại để `core/` mọc thêm
// một `MASK_REASON_*` thứ năm là đỏ chứ không âm thầm.

import { VAI_SLOT } from "@/nhan";

// Ba hằng của ngữ pháp dấu che, chép từ `core/masking.py` và được
// `tests/test_web_khung.py` nhóm (11) ghim với chính hằng ở đó.
//
// Hai lý do vì hai luật khác nguồn (`core/masking.py`): `masked` là luật của
// bảng chính sách (loại nội dung này đang ở L1 và bảng khai vai đó phải che),
// `group` là luật AD-9 (vai `owner` luôn tổng quát hóa về mức nhóm, kể cả ở L2).
export const LY_DO_CHINH_SACH = "masked";
export const LY_DO_OWNER = "group";
export const VAI_OWNER = "owner";

/** Dấu che của một vai slot, dựng đúng như `core.masking.dau_che_truong`. */
function dau_che_truong(vai: string, ly_do: string): string {
  return `[${vai}:${ly_do}]`;
}

/** Dấu che theo bảng chính sách; `owner` mang lý do riêng (AD-9). */
function dau_che(vai: string): string {
  return dau_che_truong(vai, vai === VAI_OWNER ? LY_DO_OWNER : LY_DO_CHINH_SACH);
}

/** Dấu che `owner` mang tên nhóm phụ trách (`core.masking.dau_che_owner`). */
function dau_che_owner(nhom: string): string {
  return dau_che_truong(VAI_OWNER, nhom);
}

/** Một mảnh của câu trả lời sau khi tách.
 *
 *  `van_ban` của mảnh slab là **nguyên văn dấu che** mà server sinh ra; chữ
 *  hiển thị dựng ở tầng render từ `microcopy.json` cộng `nhan_slot`, để câu chữ
 *  vẫn ở một nguồn và hàm này vẫn thuần. */
export type ManhCau =
  | { loai: "chu"; van_ban: string }
  | { loai: "slab"; van_ban: string; vai: string; nhom: string | null };

/** Một dấu che hợp lệ cùng thứ nó nói ra, dựng **một lượt** cùng với chuỗi.
 *
 *  `nhom` khác `null` chỉ ở họ `[owner:<nhóm>]`. Đi kèm ngay lúc dựng chứ không
 *  suy ngược từ chuỗi sau khi khớp: phép suy ngược duy nhất có thể viết là "lý
 *  do khác `group` thì nó là tên nhóm", và nó đọc sai đúng ca một nhóm phụ
 *  trách **tên là** `group` - khi đó `[owner:group]` do `dau_che_owner("group")`
 *  sinh ra bị đọc thành dấu che không nhóm và tên nhóm biến mất khỏi slab.
 *  `config/nhom-phu-trach.yaml` cấm `[`, `]` và `:` trong tên nhóm nhưng không
 *  cấm tên ấy. */
type DauChe = { chuoi: string; vai: string; nhom: string | null };

function thoat_regex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Mọi dấu che hợp lệ **của một lượt**, dài trước ngắn sau.
 *
 *  Tập là 8 vai (`[<vai>:masked]`, riêng `owner` ra `[owner:group]`) cộng
 *  `[owner:<nhóm>]` cho từng nhóm phụ trách xuất hiện trong `citations` của
 *  chính lượt đó. Hệ quả **cố ý**: `[owner:NhómKhôngCóTrongLượt]` là chữ
 *  thường, và một lượt không có citation nào thì không dấu owner mang tên nhóm
 *  nào thành slab.
 *
 *  Vẫn `export` dù hôm nay chỉ `tach_slab` gọi: 4.6 dựng chú thích hover cho
 *  đỉnh đồ thị từ cùng tập này, và tách nó ra một cửa có tên là cách để story
 *  ấy không dựng một bản thứ hai. Bỏ `export` thì bản thứ hai là đường rẻ nhất. */
export function cac_dau_che(cac_nhom: readonly string[]): DauChe[] {
  const ra: DauChe[] = VAI_SLOT.map((vai) => ({ chuoi: dau_che(vai), vai, nhom: null }));
  for (const nhom of cac_nhom) {
    if (nhom) ra.push({ chuoi: dau_che_owner(nhom), vai: VAI_OWNER, nhom });
  }
  // Khử trùng theo chuỗi, **giữ mục đầu tiên**: một nhóm tên `group` dựng ra
  // đúng chuỗi `[owner:group]` mà `dau_che("owner")` đã dựng. Giữ mục trước là
  // giữ dấu che không nhóm, tức render "[người phụ trách: che]" - đúng, vì hai
  // nghĩa ấy không phân biệt được từ chuỗi và AD-9 nói cái sau che ít hơn.
  const thay = new Set<string>();
  return ra
    .filter((d) => !thay.has(d.chuoi) && thay.add(d.chuoi))
    .sort((a, b) => b.chuoi.length - a.chuoi.length);
}

/** Tách `van_ban` thành mảnh chữ và mảnh slab.
 *
 *  Nhận diện **cùng cách** với `core.masking.la_dau_che` - dựng lại tập chuỗi
 *  hợp lệ rồi khớp **trọn** - chứ không bằng một regex tự do kiểu
 *  `\[\w+:\w+\]`: một tên entity thật bắt đầu bằng `[owner:` qua được phép so
 *  tiền tố, và khi đó một mảnh văn bản có thật biến thành một vệt đen. Danh mục
 *  chỉ có 8 vai cộng vài nhóm, nên hỏi thẳng "chuỗi này có đúng bằng một dấu
 *  che nào không" là rẻ và đúng. Phạm vi là ba họ dấu che của vai slot, xem
 *  đầu file.
 *
 *  Mảnh rỗng bị bỏ để renderer không sinh những `<span>` trắng. */
export function tach_slab(van_ban: string, cac_nhom: readonly string[]): ManhCau[] {
  const danh_sach = cac_dau_che(cac_nhom);
  const theo_chuoi = new Map(danh_sach.map((d) => [d.chuoi, d]));
  const mau = new RegExp(danh_sach.map((d) => thoat_regex(d.chuoi)).join("|"), "g");
  const ra: ManhCau[] = [];
  let vi_tri = 0;
  for (let m = mau.exec(van_ban); m !== null; m = mau.exec(van_ban)) {
    if (m.index > vi_tri) ra.push({ loai: "chu", van_ban: van_ban.slice(vi_tri, m.index) });
    const dau = theo_chuoi.get(m[0])!;
    ra.push({ loai: "slab", van_ban: m[0], vai: dau.vai, nhom: dau.nhom });
    vi_tri = m.index + m[0].length;
  }
  if (vi_tri < van_ban.length) ra.push({ loai: "chu", van_ban: van_ban.slice(vi_tri) });
  return ra.filter((manh) => manh.van_ban !== "");
}
