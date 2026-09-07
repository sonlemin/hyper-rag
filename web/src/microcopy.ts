// Lớp kiểu và hàm điền cho `microcopy.json`. Mọi chuỗi UI sống ở file JSON đó
// (để `tests/test_web_khung.py` đối chiếu với bảng Voice and Tone và với hằng
// `api.hoi_dap.TEMPLATE_TU_CHOI`); file này không chứa một chuỗi nào.

import microcopy from "./microcopy.json";

export type KhoaMicrocopy = keyof typeof microcopy;
export const MICROCOPY = microcopy;

// Chỗ trống của một chuỗi microcopy, khai **một lần** dưới dạng nguồn regex:
// `dien()` và `cac_manh()` phải nhận cùng một tập chỗ trống, và hai mẫu chép
// nhau là hai mẫu lệch nhau một lần sửa. Nguồn chuỗi chứ không một `RegExp`
// dùng chung: cờ `g` mang `lastIndex` đổi được, nên hai nơi dùng chung một
// object là một trạng thái chia sẻ giữa hai vòng lặp.
const NGUON_MAU_CHO_TRONG = "\\{([a-z][a-z0-9_]*)\\}";

function mau_cho_trong(): RegExp {
  return new RegExp(NGUON_MAU_CHO_TRONG, "g");
}

/** Điền chỗ trống `{ten}` của một chuỗi. Chỗ trống không được điền giữ nguyên
 *  để nhìn thấy trong UI thay vì biến thành `undefined`. */
export function dien(khoa: KhoaMicrocopy, gia_tri: Record<string, string | number> = {}): string {
  return MICROCOPY[khoa].replace(mau_cho_trong(), (nguyen, ten: string) =>
    ten in gia_tri ? String(gia_tri[ten]) : nguyen,
  );
}

/** Một mảnh của template đã tách theo chỗ trống. `ten` là tên chỗ trống mà mảnh
 *  này điền (để renderer bọc `<b>` quanh nó), hay `null` cho phần chữ cố định. */
export type ManhMicrocopy = { ten: string | null; van_ban: string };

/** Tách một chuỗi microcopy thành các mảnh kèm tên chỗ trống.
 *
 *  Vì sao cần: `dien()` trả một chuỗi phẳng, nên không bọc được `<b>` quanh
 *  `{vai}` của dòng meta ("Copilot · trả lời theo quyền **DevOps** · 2 trích
 *  dẫn", DESIGN.md). Cách khác là tách `meta_luot` thành ba khóa microcopy để
 *  ghép tay, nhưng khi đó bảng Voice and Tone không còn đối chiếu nguyên văn
 *  được với `microcopy.json` - phép canh của 4.1 sẽ mất. Tách **lúc render**
 *  giữ câu nguyên vẹn ở nguồn.
 *
 *  Chỗ trống không được điền giữ nguyên văn `{ten}` và trả về như chữ cố định,
 *  cùng hành vi với `dien()`: nhìn thấy trong UI thay vì thành `undefined`.
 *  Mảnh rỗng bị bỏ để renderer không sinh những `<span>` trắng. */
export function cac_manh(
  khoa: KhoaMicrocopy,
  gia_tri: Record<string, string | number> = {},
): ManhMicrocopy[] {
  const ra: ManhMicrocopy[] = [];
  let vi_tri = 0;
  const mau = mau_cho_trong();
  const nguon: string = MICROCOPY[khoa];
  for (let m = mau.exec(nguon); m !== null; m = mau.exec(nguon)) {
    if (m.index > vi_tri) ra.push({ ten: null, van_ban: nguon.slice(vi_tri, m.index) });
    const ten = m[1];
    if (ten in gia_tri) {
      ra.push({ ten, van_ban: String(gia_tri[ten]) });
    } else {
      ra.push({ ten: null, van_ban: m[0] });
    }
    vi_tri = m.index + m[0].length;
  }
  if (vi_tri < nguon.length) ra.push({ ten: null, van_ban: nguon.slice(vi_tri) });
  return ra.filter((manh) => manh.van_ban !== "");
}
