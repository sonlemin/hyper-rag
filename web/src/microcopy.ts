// Lớp kiểu và hàm điền cho `microcopy.json`. Mọi chuỗi UI sống ở file JSON đó
// (để `tests/test_web_khung.py` đối chiếu với bảng Voice and Tone và với hằng
// `api.hoi_dap.TEMPLATE_TU_CHOI`); file này không chứa một chuỗi nào.

import microcopy from "./microcopy.json";

export type KhoaMicrocopy = keyof typeof microcopy;
export const MICROCOPY = microcopy;

/** Điền chỗ trống `{ten}` của một chuỗi. Chỗ trống không được điền giữ nguyên
 *  để nhìn thấy trong UI thay vì biến thành `undefined`. */
export function dien(khoa: KhoaMicrocopy, gia_tri: Record<string, string | number> = {}): string {
  return MICROCOPY[khoa].replace(/\{([a-z][a-z0-9_]*)\}/g, (nguyen, ten: string) =>
    ten in gia_tri ? String(gia_tri[ten]) : nguyen,
  );
}
