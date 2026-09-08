// Phiên phía trình duyệt: token JWT ở `sessionStorage` (không kho bền nào khác,
// phiên chết khi đóng tab), cộng nhãn tiếng Việt của vai người dùng.

export const KHOA_TOKEN = "hyper_rag_token";

/** Người **thật** đứng sau một phiên đang mượn vai (claim `act`, story 4.5). */
export type ActPhien = {
  tai_khoan: string;
  vai: string;
};

/** Thân của `GET /auth/toi` (api/main.py). */
export type Phien = {
  tai_khoan: string;
  vai: string;
  khong_gian: string;
  demo: boolean;
  admin: boolean;
  /** `null` với một phiên thường; người thật khi phiên đang mượn vai. */
  act: ActPhien | null;
};

function la_chuoi_that(gia_tri: unknown): boolean {
  return typeof gia_tri === "string" && gia_tri.trim() !== "";
}

/** `act` của thân trả về có đúng hình không: `null`, hay hai chuỗi không rỗng.
 *
 *  **Vắng mặt không phải là `null`.** `null` là một trạng thái thật ("không
 *  mượn vai nào") còn vắng mặt là hợp đồng đã trôi, và đọc cái sau thành cái
 *  trước là chip hổ phách biến mất khỏi topbar cùng mục "Thoát xem như" biến
 *  mất khỏi menu, trong khi phiên vẫn đang mang một vai giả - đúng trạng thái
 *  nguy hiểm nhất mà màn này có thể ở. Cùng luật với `api.xac_thuc._doc_act`,
 *  chỗ một `act` có mặt mà không đọc được là từ chối cả token. */
function la_act(gia_tri: unknown): gia_tri is ActPhien | null {
  if (gia_tri === null) return true;
  if (typeof gia_tri !== "object") return false;
  const a = gia_tri as Record<string, unknown>;
  return la_chuoi_that(a.tai_khoan) && la_chuoi_that(a.vai);
}

/** Thân trả về có đúng hình phiên không: `tai_khoan` và `vai` phải là chuỗi
 *  **không rỗng**, và `act` phải có mặt đúng hình.
 *
 *  Một thân lạ (proxy trả HTML, envelope khác) không được thành chip
 *  `undefined · undefined`; caller coi nó là lỗi hệ thống. Và luật "chuỗi không
 *  rỗng" áp **đều** cho cả hai tầng: `la_act` đã đòi thế cho hai trường của
 *  `act`, nên để `tai_khoan`/`vai` ở cấp trên chỉ cần `typeof === "string"` là
 *  `{"tai_khoan": "", "vai": ""}` đi lọt và thành một chip `" · "` - đúng loại
 *  thân rỗng nghĩa mà cả hàm này dựng ra để chặn. */
export function la_phien(than: unknown): than is Phien {
  if (typeof than !== "object" || than === null) return false;
  const t = than as Record<string, unknown>;
  if (!(KHOA_ACT in t) || !la_act(t[KHOA_ACT])) return false;
  return la_chuoi_that(t.tai_khoan) && la_chuoi_that(t.vai);
}

function kho(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function doc_token(): string | null {
  try {
    return kho()?.getItem(KHOA_TOKEN) ?? null;
  } catch {
    return null;
  }
}

/** Ghi token; trả `false` khi kho bị chặn (chế độ riêng tư, quota), để màn
 *  đăng nhập nói được là phiên không giữ được thay vì lặng lẽ mất. */
export function ghi_token(token: string): boolean {
  try {
    const k = kho();
    if (!k) return false;
    k.setItem(KHOA_TOKEN, token);
    return true;
  } catch {
    return false;
  }
}

export function xoa_token(): void {
  try {
    kho()?.removeItem(KHOA_TOKEN);
  } catch {
    /* kho bị chặn: không có gì để xóa */
  }
}

// Nhãn tiếng Việt của vai người dùng (5 vai PRD 1.5). Khóa lạ hiện nguyên khóa:
// một nhãn đoán là một chỗ để UI nói khác với token.
// Xuất ra vì `tests/test_web_khung.py` nhóm (12) ghim **khóa** của bảng này với
// hợp các vai của bốn `config/policy-*.yaml`, và vì menu xem như dựng bảng mô tả
// vùng quyền theo đúng danh mục khóa ấy. Một bản chép thứ hai của năm tên vai
// là hai bản trôi khỏi nhau ở lần sửa đầu tiên.
export const NHAN_VAI: Record<string, string> = {
  devops: "DevOps",
  tech_support: "Tech Support",
  sale_ba: "Sale/BA",
  truong_nhom: "Trưởng nhóm",
  admin: "Admin",
};

export function nhan_vai(vai: string): string {
  return NHAN_VAI[vai] ?? vai;
}

/** Nội dung chip vai trên topbar: "Tên · Vai". Không bao giờ gắn Lx. */
export function chip_vai(phien: Phien): string {
  return `${phien.tai_khoan} · ${nhan_vai(phien.vai)}`;
}

// --- Vòng đời phiên (story 4.2) ---------------------------------------------

/** Giá trị của tham số `ly_do` trên `/dang-nhap` khi khung đá về vì hết phiên.
 *  Màn đăng nhập đọc nó ra một thông báo **trung tính**, không phải hộp lỗi. */
export const LY_DO_HET_HAN = "het_han";

/** Tên tham số truy vấn mang lý do trên `/dang-nhap`. */
export const THAM_SO_LY_DO = "ly_do";

/** Màn đăng nhập, route mở duy nhất của app.
 *
 *  Hằng sống ở đây chứ không ở `KhungApp.tsx` (nơi nó ở tới story 4.2): từ màn
 *  chat 4.3 có **hai** nơi điều hướng về màn đăng nhập vì hết phiên, và một
 *  đường dẫn chép hai lần là một bản viết sai mà không phép so nào bắt.
 *  `KhungApp` re-export nó cho `ROUTE_MO`. */
export const DUONG_DANG_NHAP = "/dang-nhap";

/** URL đầy đủ để đá về màn đăng nhập vì **hết phiên**, kèm lý do trung tính.
 *
 *  Một hàm chứ không một chuỗi ghép tay ở mỗi nơi gọi: hai bản chép là hai chỗ
 *  một bản quên `?ly_do=het_han` rồi người dùng bị đá ra mà không biết vì sao.
 *  Đăng xuất thì dùng thẳng `DUONG_DANG_NHAP` (không `ly_do`): tự thoát và hết
 *  phiên là hai chuyện khác nhau. */
export function duong_het_phien(): string {
  return `${DUONG_DANG_NHAP}?${THAM_SO_LY_DO}=${LY_DO_HET_HAN}`;
}

/** Luật phân loại lỗi của cả app, khai **một chỗ**: chỉ 401 là hết phiên.
 *
 *  Chỉ một nhánh `la_het_phien` mới **được phép** điều hướng tới màn đăng nhập
 *  vì một lỗi; nơi nào đi vào nhánh đó mà cố ý không điều hướng thì phải nói ra
 *  lý do (màn đăng nhập là một chỗ như vậy). 403 (đủ phiên, thiếu quyền), 5xx
 *  và lỗi mạng báo tại chỗ bằng `HopLoi` và giữ nguyên URL: đá người dùng ra
 *  ngoài giữa một lượt hỏi vì máy chủ chết là mất câu hỏi của họ và nói sai
 *  nguyên nhân.
 *
 *  Nhận `unknown` chứ không nhận `LoiApi`: `catch` của TypeScript cho `unknown`,
 *  và một phép so hình dạng ở đây rẻ hơn một lần ép kiểu ở mỗi nơi gọi. Không
 *  import `LoiApi` vì `goi.ts` đã import file này (vòng import). */
export function la_het_phien(loi: unknown): boolean {
  if (typeof loi !== "object" || loi === null) return false;
  return (loi as { status?: unknown }).status === 401;
}

/** Mã lỗi của `api/xac_thuc.py` cho **mọi** ca đăng nhập sai; `tests/test_web_khung.py`
 *  ghim nó bằng chính hằng `api.xac_thuc.MA_DANG_NHAP_SAI`. */
export const MA_DANG_NHAP_SAI = "DANG_NHAP_SAI";

/** 401 **của tuyến đăng nhập**: sai tài khoản hoặc mật khẩu, chứ không phải một
 *  401 hạ tầng.
 *
 *  Hai thứ khác nhau cùng mang 401. Một proxy chen giữa trả 401 với thân HTML
 *  thì `goi.ts` gán mã `MANG`, và đọc nó thành "bạn gõ sai mật khẩu" là bắt
 *  người dùng gõ lại mãi một mật khẩu đúng. Nên nhánh "sai thông tin" đòi
 *  **cả** status lẫn mã, mọi ca còn lại rơi về lỗi hệ thống. */
export function la_sai_thong_tin(loi: unknown): boolean {
  if (!la_het_phien(loi)) return false;
  return (loi as { code?: unknown }).code === MA_DANG_NHAP_SAI;
}

// Tên ba trường của hợp đồng `POST /auth/login` với `api/main.py`, khai thành
// hằng để `tests/test_web_khung.py` ghim được chúng với chính nguồn `api/`.
// Vì sao phải ghim: đổi tên một trường ở một bên không làm test nào đỏ nhưng
// làm màn đăng nhập chết **im lặng theo chiều xấu nhất** - `api/main.py` ánh xạ
// thân sai trường về đúng 401 `DANG_NHAP_SAI`, nên UI hiện "Sai tài khoản hoặc
// mật khẩu" cho một mật khẩu đúng.
export const TRUONG_TAI_KHOAN = "tai_khoan";
export const TRUONG_MAT_KHAU = "mat_khau";
export const TRUONG_TOKEN = "token";

/** Tuyến phát token. `cua_mo` của `api/main.py`, không cần Bearer. */
export const TUYEN_DANG_NHAP = "/auth/login";

/** Token của thân `POST /auth/login`, hay `null` nếu thân không mang token dùng
 *  được. Thân 200 thiếu `token` là **lỗi hệ thống** chứ không phải một lần đăng
 *  nhập thành công: ghi một chuỗi rỗng vào kho là phiên chết ở request kế.
 *
 *  Trả bản **đã trim**: một token `" abc "` qua được phép kiểm rỗng rồi đi
 *  thẳng vào header `Bearer`, và mọi lời gọi sau đó là 401. */
export function token_dang_nhap(than: unknown): string | null {
  if (typeof than !== "object" || than === null) return null;
  const t = (than as Record<string, unknown>)[TRUONG_TOKEN];
  if (typeof t !== "string") return null;
  const sach = t.trim();
  return sach === "" ? null : sach;
}

/** Đăng xuất: xóa token phía trình duyệt. Không gọi tuyến API nào vì `api/`
 *  không có danh sách đen JWT, nên token cũ vẫn hợp lệ tới hết TTL 12 giờ (giới
 *  hạn đã nhận ở ADR-022, không phải một khoản nợ mới). Điều hướng là việc của
 *  nơi gọi. */
export function dang_xuat(): void {
  xoa_token();
}


// --- "Xem như": đọc phiên đang mượn vai (story 4.5, FR-18) -------------------
//
// Ba hằng tuyến và hai tên trường khai ở đây rồi `tests/test_web_khung.py` nhóm
// (12) ghim chúng với chính `api/main.py` - cùng khuôn mà 4.2 ghim ba trường
// đăng nhập và 4.3 ghim hợp đồng envelope, và vì cùng một lý do: e2e mock trọn
// tuyến nên nó xanh với bất kỳ tên nào, còn phía `api/` không biết `web/` gửi gì.

/** Phát token mượn vai. Thân `{vai: "<tên vai>"}`, trả `{token, token_type}`. */
export const TUYEN_XEM_NHU = "/auth/xem-nhu";

/** Về vai thật. Không thân request: vai thật đã nằm trong `act` của token. */
export const TUYEN_THOAT_XEM_NHU = "/auth/thoat-xem-nhu";

/** Danh mục vai của **bảng chính sách đang chạy**, không một danh sách ở `web/`. */
export const TUYEN_VAI = "/auth/vai";

/** Trường duy nhất của thân `POST /auth/xem-nhu`. */
export const TRUONG_VAI = "vai";

/** Khóa mang danh mục vai trong thân `GET /auth/vai`. */
export const TRUONG_DANH_MUC_VAI = "vai";

/** Khóa `act` của `GET /auth/toi`; `la_phien` đòi nó có mặt. */
export const KHOA_ACT = "act";

/** Phiên có đang mượn vai không. **Một nguồn**: claim `act` của chính token,
 *  không phải một chênh lệch giữa `vai` và một giá trị nhớ ở client - một
 *  trạng thái thứ hai bên trình duyệt là một trạng thái lệch được với token. */
export function la_dang_xem_nhu(phien: Phien): boolean {
  return phien.act !== null;
}

/** Vai của **người thật**: vai trong `act` khi đang mượn, còn không thì chính
 *  vai của phiên. Menu dùng nó để biết dòng nào là vai gốc. */
export function vai_that(phien: Phien): string {
  return phien.act?.vai ?? phien.vai;
}

/** Tài khoản của người thật; `sub` không bao giờ đổi nên nó luôn bằng
 *  `phien.tai_khoan`, và hàm này tồn tại để nơi gọi không phải biết điều đó. */
export function tai_khoan_that(phien: Phien): string {
  return phien.act?.tai_khoan ?? phien.tai_khoan;
}

/** Chip **vai thật** mờ cạnh chip hổ phách: "dev01 · DevOps". Cùng khuôn với
 *  `chip_vai`, và cũng không bao giờ gắn Lx. */
export function chip_vai_that(phien: Phien): string {
  return `${tai_khoan_that(phien)} · ${nhan_vai(vai_that(phien))}`;
}
