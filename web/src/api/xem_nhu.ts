// Ba lời gọi của đường "xem như" (story 4.5, FR-18), tất cả qua `goi` - cửa
// fetch duy nhất của `web/`. Tuyến và tên trường là hằng ở `phien.ts`, chỗ
// `tests/test_web_khung.py` ghim chúng với chính `api/main.py`.
//
// **Đổi vai là thay token, không phải một trạng thái ở client.** Ba hàm dưới
// đây ghi token mới vào đúng kho của `phien.ts` rồi để nơi gọi đọc lại
// `GET /auth/toi`; không hàm nào giữ vai đang mượn ở một chỗ thứ hai. Luật một
// cửa của 4.2 áp nguyên: một bản chép của "đang xem như vai gì" bên trình duyệt
// là một giá trị lệch được với token, và khi nó lệch thì màn hình nói một vai
// còn máy chủ trả lời theo vai khác - đúng chỗ nguy hiểm nhất của story này.

import { ghi_token, TRUONG_VAI, TRUONG_DANH_MUC_VAI, TUYEN_THOAT_XEM_NHU, TUYEN_VAI, TUYEN_XEM_NHU } from "./phien";

import { goi } from "./goi";

/** Thân 200 của hai tuyến phát token, cùng hình với `POST /auth/login`. */
type ThanToken = { token?: unknown };

/** Danh mục vai của **bảng chính sách đang chạy**.
 *
 *  Không lọc, không sắp lại, không thêm bớt: server đã sắp xếp, và một danh
 *  sách vai chép ở `web/` là đúng thứ AD-4 hứa không cần - thêm một vai vào
 *  YAML là dropdown **dài thêm một dòng ngay**, không sửa một dòng TypeScript
 *  nào. Nói cho đủ: dòng ấy hiện **nguyên khóa** `snake_case` và không có mô
 *  tả cho tới khi ai đó thêm một nhãn vào `NHAN_VAI` và một khóa
 *  `mo_ta_vai_<vai>` vào `microcopy.json` - hai dòng dữ liệu, không phải một
 *  thay đổi cơ chế, và cả hai đi theo luật khóa-lạ-hiện-nguyên-khóa nên dropdown
 *  vẫn dùng được ngay.
 *
 *  Thân sai hình trả mảng rỗng thay vì ném: menu không có gì để vẽ thì nó nói
 *  bằng cách không có mục nào, và nơi gọi vẫn phân biệt được ca ấy với ca lỗi
 *  mạng (ca kia ném `LoiApi`). */
export async function danh_muc_vai(): Promise<string[]> {
  const than = await goi<unknown>(TUYEN_VAI);
  if (typeof than !== "object" || than === null) return [];
  const cac = (than as Record<string, unknown>)[TRUONG_DANH_MUC_VAI];
  if (!Array.isArray(cac)) return [];
  return cac.filter((v): v is string => typeof v === "string" && v !== "");
}

/** Token của một thân 200, hay `null` khi thân không mang token dùng được.
 *
 *  Cùng luật với `token_dang_nhap` của 4.2, kể cả phép trim: một token `" abc "`
 *  qua được phép kiểm rỗng rồi đi thẳng vào header `Bearer`, và mọi lời gọi sau
 *  đó là 401. */
function token_cua(than: unknown): string | null {
  if (typeof than !== "object" || than === null) return null;
  const t = (than as ThanToken).token;
  if (typeof t !== "string") return null;
  const sach = t.trim();
  return sach === "" ? null : sach;
}

/** Kết cục của một lần đổi vai, đủ ba ca mà nơi gọi phải phân biệt. */
export type KetCucDoiVai =
  /** Token mới đã nằm trong kho; đọc lại `/auth/toi` là thấy vai mới. */
  | { loai: "xong" }
  /** Kho bị chặn (chế độ riêng tư, quota): **không** đổi vai trên màn, vì
   *  token cũ vẫn là token mà mọi lời gọi sau dùng. Nói ra bằng
   *  `MICROCOPY.khong_giu_duoc_phien`, đúng câu mà màn đăng nhập 4.2 dùng cho
   *  cùng nguyên nhân. */
  | { loai: "khong_giu_duoc" }
  /** Thân 200 không mang token: lỗi hệ thống, không phải một lần đổi vai thành
   *  công. Ghi một chuỗi rỗng vào kho là phiên chết ở request kế. */
  | { loai: "than_la" };

function ket_cuc(than: unknown): KetCucDoiVai {
  const token = token_cua(than);
  if (token === null) return { loai: "than_la" };
  return ghi_token(token) ? { loai: "xong" } : { loai: "khong_giu_duoc" };
}

/** Mượn một vai. Ném `LoiApi` cho mọi ca hỏng phía máy chủ (403 thiếu cờ, 400
 *  vai lạ, 401 hết phiên); nơi gọi rẽ nhánh theo `code` và theo `la_het_phien`. */
export async function doi_vai(vai: string): Promise<KetCucDoiVai> {
  return ket_cuc(await goi<unknown>(TUYEN_XEM_NHU, { than: { [TRUONG_VAI]: vai } }));
}

/** Về vai thật. Không thân request: vai thật nằm trong `act` của chính token,
 *  nên đây là một phép biến đổi thuần trên token phía máy chủ. */
export async function thoat_xem_nhu(): Promise<KetCucDoiVai> {
  return ket_cuc(await goi<unknown>(TUYEN_THOAT_XEM_NHU, { method: "POST" }));
}
