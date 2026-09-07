// Một cửa gọi API duy nhất của `web/` (`tests/test_web_khung.py` canh không
// file nào khác gọi `fetch`). Đường đi: trình duyệt -> `/api/<tuyến>` cùng origin
// -> rewrite của Next -> `API_NOI_BO`. Gắn Bearer từ sessionStorage, parse
// envelope lỗi `{error: {code, message}}` thành `LoiApi`, và ném `LoiApi` mã
// `MANG` khi không tới được máy chủ hay thân không phải JSON.

import { doc_token } from "./phien";

export const GOC_API = "/api";

/** Mã dùng khi lỗi mạng hay thân không đọc được; không phải mã của `api/`. */
export const MA_MANG = "MANG";

export class LoiApi extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number, message?: string) {
    super(message ?? code);
    this.name = "LoiApi";
    this.code = code;
    this.status = status;
  }
}

type TuyChon = {
  method?: "GET" | "POST";
  than?: unknown;
  /** Bỏ Bearer (đăng nhập). */
  khong_token?: boolean;
};

/** Gọi một tuyến của `api/`. 2xx không thân (204, thân rỗng) trả `null`. */
export async function goi<T>(tuyen: string, tuy_chon: TuyChon = {}): Promise<T> {
  const duong = tuyen.startsWith("/") ? tuyen : `/${tuyen}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (tuy_chon.than !== undefined) headers["Content-Type"] = "application/json";
  const token = tuy_chon.khong_token ? null : doc_token();
  if (token) headers.Authorization = `Bearer ${token}`;

  let phan_hoi: Response;
  try {
    phan_hoi = await fetch(`${GOC_API}${duong}`, {
      method: tuy_chon.method ?? (tuy_chon.than === undefined ? "GET" : "POST"),
      headers,
      body: tuy_chon.than === undefined ? undefined : JSON.stringify(tuy_chon.than),
      cache: "no-store",
    });
  } catch (loi) {
    throw new LoiApi(MA_MANG, 0, loi instanceof Error ? loi.message : String(loi));
  }

  const van_ban = await phan_hoi.text();
  if (phan_hoi.ok && (phan_hoi.status === 204 || van_ban.trim() === "")) {
    return null as T;
  }

  let than: unknown = null;
  try {
    than = JSON.parse(van_ban);
  } catch {
    if (phan_hoi.ok) throw new LoiApi(MA_MANG, phan_hoi.status);
  }

  if (!phan_hoi.ok) {
    const loi = (than as { error?: { code?: string; message?: string } } | null)?.error;
    throw new LoiApi(loi?.code ?? MA_MANG, phan_hoi.status, loi?.message);
  }
  return than as T;
}
