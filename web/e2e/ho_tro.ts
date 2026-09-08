import path from "node:path";

import { expect, type Page } from "@playwright/test";

// Đồ dùng chung của lưới Playwright. Không mang `.spec.` trong tên nên
// `testMatch` mặc định không nhặt nó thành một file test rỗng.
//
// Vì sao tách: hai spec đầu đã chép nhau và đã lệch một chỗ vô cớ (token giả
// mang hai tên khác nhau), và 4.3-4.7 còn thêm spec nữa.

/** Phiên mẫu của `GET /auth/toi`: `dev01`, DevOps, đủ hai cờ demo và admin.
 *
 *  `act: null` từ story 4.5 - `la_phien` đòi khóa ấy **có mặt**, vì vắng mặt là
 *  hợp đồng đã trôi còn `null` là một trạng thái thật ("không mượn vai nào"). */
export const PHIEN = {
  tai_khoan: "dev01",
  vai: "devops",
  khong_gian: "synth",
  demo: true,
  admin: true,
  act: null as { tai_khoan: string; vai: string } | null,
};

/** Phiên **đang mượn vai**: `vai` là vai giả, `act` là người thật.
 *
 *  `tai_khoan` giữ nguyên `dev01`: `sub` không bao giờ đổi (chỉ `role` đổi), nên
 *  chip vai của topbar vẫn ghi tên thật cạnh vai giả. */
export function phien_xem_nhu(vai: string, that = { tai_khoan: "dev01", vai: "devops" }) {
  return { ...PHIEN, vai, act: that };
}

/** Phiên **không cờ nào**: không thấy nút xem như, và ba tuyến API cũng từ chối. */
export const PHIEN_THUONG = {
  ...PHIEN,
  tai_khoan: "ts01",
  vai: "tech_support",
  demo: false,
  admin: false,
};

/** Token giả đặt sẵn trong kho trước khi trang tải. */
export const TOKEN_CO_SAN = "token-co-san";

/** Thư mục ảnh bằng chứng có commit. */
export function duong_anh(ten: string): string {
  return path.resolve(__dirname, "..", "..", "eval", "anh_bang_chung", ten);
}

/** Chặn **mọi** `/api/**` chưa mock: không lượt nào đi ra máy chủ thật. Route
 *  đăng ký sau thắng route đăng ký trước, nên mock cụ thể của từng ca vẫn ăn. */
export async function chan_moi_api(page: Page) {
  await page.route("**/api/**", (route) => route.abort("connectionrefused"));
}

/** Đặt token **một lần** cho phiên: init script chạy lại ở mỗi lần tải trang,
 *  nên nó phải tự nhận ra đã đặt rồi, nếu không ca 401 (khung xóa token rồi
 *  điều hướng) lại thấy token mọc lên sau lần tải kế. */
export async function co_token(page: Page) {
  await page.addInitScript((token) => {
    if (!sessionStorage.getItem("e2e_da_dat_token")) {
      sessionStorage.setItem("hyper_rag_token", token);
      sessionStorage.setItem("e2e_da_dat_token", "1");
    }
  }, TOKEN_CO_SAN);
}

export async function mock_toi(page: Page, than: unknown = PHIEN, status = 200) {
  await page.route("**/api/auth/toi", (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(than) }),
  );
}

/** Mock `/auth/toi` và trả về bộ đếm số lần tuyến bị gọi. */
export async function dem_goi_toi(page: Page): Promise<() => number> {
  let so = 0;
  await page.route("**/api/auth/toi", (route) => {
    so += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PHIEN),
    });
  });
  return () => so;
}

/** Mock `POST /auth/login` và trả về bộ đếm. `cho_ms` giữ phản hồi lại để ca
 *  "gửi hai lần" quan sát được trạng thái đang gửi. */
export async function mock_login(
  page: Page,
  than: unknown,
  status = 200,
  cho_ms = 0,
): Promise<() => number> {
  let so = 0;
  await page.route("**/api/auth/login", async (route) => {
    so += 1;
    if (cho_ms > 0) await new Promise((xong) => setTimeout(xong, cho_ms));
    await route.fulfill({
      status,
      contentType: "application/json",
      body: typeof than === "string" ? than : JSON.stringify(than),
    });
  });
  return () => so;
}

export async function rong_cuon(page: Page): Promise<number> {
  return page.evaluate(() => document.scrollingElement!.scrollWidth);
}

export async function token_trong_kho(page: Page): Promise<string | null> {
  return page.evaluate(() => sessionStorage.getItem("hyper_rag_token"));
}

/** Envelope mẫu của `POST /hoi-dap` (AD-8, năm khóa). `sua` ghi đè từng khóa. */
export function envelope(sua: Record<string, unknown> = {}) {
  return {
    answer: "App01 lỗi 502 vì PHP-FPM hết bộ nhớ.",
    refused: false,
    citations: [],
    graph: { nodes: [], edges: [] },
    meta: { role: "devops", space: "synth", policy_version: "day-du@1" },
    ...sua,
  };
}

/** Một citation sáu khóa đóng (`adapters.trich_dan.KHOA_TRICH_DAN`).
 *
 *  Mặc định là một nguồn L2 không che gì. Story 4.4 mở chữ ký để dựng ca L1:
 *  `sua` ghi đè từng khóa, kể cả bằng một giá trị sai hình (ca "citation sai
 *  hình" đi qua đúng cửa này). */
export function trich_dan(id: string, sua: Record<string, unknown> = {}) {
  return {
    id,
    level: "L2",
    scope: "noi_bo",
    content_type: "runbook",
    masked_slots: [] as string[],
    owner_group: null as string | null,
    ...sua,
  };
}

/** Mock `POST /hoi-dap` và trả về bộ đếm. `cho_ms` giữ phản hồi lại để ca "đang
 *  chờ" và ca "gửi hai lần" quan sát được trạng thái đang chờ. Cùng khuôn với
 *  `mock_login`.
 *
 *  `than` nhận **cả hai dạng**, đúng khuôn `mock_do_thi`: một giá trị cố định,
 *  hay một hàm `(lan) => thân` cho ca nhiều lượt trên cùng một tuyến (ba nhịp
 *  của 4.7 là ba thân khác nhau vì vai đã đổi giữa chừng). Một helper thứ hai
 *  đứng cạnh helper này là hai quy ước cho cùng một vấn đề trong cùng một file,
 *  đúng thứ mà `ho_tro.ts` được tách ra để chặn.
 *
 *  Hàm trả `undefined` cho một chỉ số ngoài dải là một **lỗi nói ra**, không
 *  một `body: "undefined"` mà màn hình đọc thành `ENVELOPE_LA`: ca test khi ấy
 *  đỏ ở một chỗ cách xa nguyên nhân. */
export async function mock_hoi_dap(
  page: Page,
  than: unknown,
  status = 200,
  cho_ms = 0,
): Promise<() => number> {
  let so = 0;
  await page.route("**/api/hoi-dap", async (route) => {
    so += 1;
    if (cho_ms > 0) await new Promise((xong) => setTimeout(xong, cho_ms));
    const noi_dung = typeof than === "function" ? (than as (lan: number) => unknown)(so) : than;
    if (noi_dung === undefined) {
      throw new Error(`mock_hoi_dap: không có thân cho lượt thứ ${so}`);
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: typeof noi_dung === "string" ? noi_dung : JSON.stringify(noi_dung),
    });
  });
  return () => so;
}

/** Thân lỗi chuẩn `{error: {code, message}}` của `api/`. */
export function loi_api(code: string) {
  return { error: { code, message: "loi" } };
}

// --- Vào màn chat (dùng chung từ story 4.4) ---------------------------------
//
// Ba thứ dưới đây từng nằm trong `chat.spec.ts` và bị `cite-row.spec.ts` chép
// nguyên văn. Vòng review 4.3 đã dời đồ dùng chung ra file này đúng vì hai spec
// chép nhau rồi lệch một chỗ vô cớ (token giả mang hai tên khác nhau); một bản
// chép thứ ba là cùng một lỗi lặp lại, và 4.5-4.7 còn thêm spec nữa.

/** Câu ghim của cả epic (EXPERIENCE.md nhịp 1, `scripts/cong-m2.sh` B2/B4/B5). */
export const CAU_HOI = "Sự cố App01 lỗi 502 nguyên nhân là gì?";

/** Vào màn chat và **đợi phiên đã đọc xong** (chip có chữ).
 *
 *  Vai của lượt đang chờ lấy từ phiên, nên gửi trước khi chip lên là đo một
 *  trạng thái khác: `waitForURL` về `/` xong thì `/auth/toi` vẫn chưa trả. */
export async function vao_chat(page: Page) {
  await page.goto("/");
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
}

export async function hoi_bang_nut(page: Page, cau = CAU_HOI) {
  await page.locator("[data-o-hoi]").fill(cau);
  await page.locator("[data-nut-gui]").click();
}


// --- Ba tuyến "xem như" (story 4.5) -----------------------------------------

/** Mock `GET /auth/vai` và trả về bộ đếm số lần tuyến bị gọi.
 *
 *  Bộ đếm là thứ ca "phiên thường không gọi `/auth/vai`" đứng lên: `chan_moi_api`
 *  đã abort mọi tuyến chưa mock nên một lời gọi lỡ bay đi sẽ thành một lỗi, chứ
 *  không thành một số 0 im lặng. */
export async function mock_danh_muc_vai(
  page: Page,
  cac_vai: string[] = ["admin", "devops", "sale_ba", "tech_support", "truong_nhom"],
  status = 200,
): Promise<() => number> {
  let so = 0;
  await page.route("**/api/auth/vai", (route) => {
    so += 1;
    return route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(status === 200 ? { vai: cac_vai } : loi_api("THIEU_QUYEN_DEMO_ADMIN")),
    });
  });
  return () => so;
}

/** Mock hai tuyến phát token của đường xem như.
 *
 *  `doi_phien` được gọi với vai vừa xin (hay `null` cho lượt thoát) để ca test
 *  đổi luôn thân `/auth/toi` - đúng đường đi thật: `web/` ghi token mới rồi đọc
 *  lại phiên, nó **không** tự sửa vai trên màn. Trả về bộ đếm hai tuyến. */
export async function mock_doi_vai(
  page: Page,
  doi_phien: (vai: string | null) => void,
  status = 200,
): Promise<() => number> {
  let so = 0;
  await page.route("**/api/auth/xem-nhu", async (route) => {
    so += 1;
    const than = JSON.parse(route.request().postData() ?? "{}") as { vai?: string };
    if (status === 200) doi_phien(than.vai ?? "");
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(
        status === 200 ? { token: `token-${than.vai}`, token_type: "bearer" } : loi_api("VAI_KHONG_CO"),
      ),
    });
  });
  await page.route("**/api/auth/thoat-xem-nhu", async (route) => {
    so += 1;
    if (status === 200) doi_phien(null);
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(
        status === 200
          ? { token: "token-that", token_type: "bearer" }
          : loi_api("KHONG_DANG_XEM_NHU"),
      ),
    });
  });
  return () => so;
}

/** Mock `/auth/toi` mà thân đọc **lúc gọi**, không đóng băng lúc mock.
 *
 *  Cần vì cả đường xem như đứng trên nhịp "ghi token mới rồi đọc lại phiên":
 *  một thân đóng băng làm mọi lần đọc lại trả về vai cũ, tức ca test xanh trong
 *  khi màn hình thật không đổi gì. */
export async function mock_toi_dong(page: Page, doc: () => unknown) {
  await page.route("**/api/auth/toi", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(doc()),
    }),
  );
}


// --- Đồ thị theo quyền (story 4.6) ------------------------------------------

/** Một node hyperedge của `graph` (`adapters.do_thi.KHOA_NODE_HYPEREDGE`).
 *
 *  `label` là `core.facts.cau_fact` dựng từ giá trị **đã che và đã lọc**, tức
 *  chữ của legend chứ không chữ trong vòng. */
export function node_vong(id: string, sua: Record<string, unknown> = {}) {
  return {
    id,
    kind: "hyperedge",
    label: `chủ thể: App01; triệu chứng: lỗi 502`,
    level: "L2",
    scope: "noi_bo",
    content_type: "runbook",
    ...sua,
  };
}

/** Một node entity (`adapters.do_thi.KHOA_NODE_ENTITY`). */
export function node_dinh(id: string, nhan: string, sua: Record<string, unknown> = {}) {
  return { id, kind: "entity", label: nhan, masked: false, ...sua };
}

/** Một cạnh hyperedge -> entity mang đúng một vai slot. */
export function canh_do_thi(source: string, target: string, slot: string) {
  return { source, target, slot };
}

/** Envelope của `POST /do-thi`: `answer: null`, `refused: false`,
 *  `citations: []`, `graph` có nội dung (ADR-018). */
export function envelope_do_thi(nodes: unknown[], edges: unknown[]) {
  return envelope({ answer: null, refused: false, citations: [], graph: { nodes, edges } });
}

/** Đồ thị `n` vòng, mỗi vòng một đỉnh riêng: đủ lớn để `fit` co hình xuống
 *  dưới zoom 1, tức đúng ca mà phép bù cỡ chữ của `VungDoThi` sinh ra để đỡ. */
export function do_thi_nhieu_vong(n: number) {
  const nodes: unknown[] = [];
  const edges: unknown[] = [];
  for (let i = 0; i < n; i += 1) {
    const he = `he-${String(i).padStart(24, "0")}`;
    nodes.push(node_vong(he, { label: `chủ thể: May chu ${i}` }));
    nodes.push(node_dinh(`ent-${i}`, `May chu ${i}`));
    edges.push(canh_do_thi(he, `ent-${i}`, "subject"));
  }
  return { nodes, edges };
}

/** `citations` khớp `do_thi_nhieu_vong(n)`: cùng id, cùng thứ tự. */
export function trich_dan_nhieu(n: number) {
  return Array.from({ length: n }, (_, i) => trich_dan(`he-${String(i).padStart(24, "0")}`));
}

/** Mock `POST /do-thi`. Trả về hàm đọc **danh sách thân đã gửi**, nên một ca
 *  vừa đếm được số lần gọi vừa khẳng định đúng danh sách id nào bay đi - thứ
 *  quan trọng nhất của story: đổi vai là gọi lại **đúng danh sách ấy** để
 *  server lọc lại, không lọc lại phía client.
 *
 *  `than` là một hàm để ca "đổi vai" trả hai đồ thị khác nhau cho hai lần gọi
 *  liên tiếp; một thân đóng băng làm ca ấy xanh trong khi màn hình không đổi. */
export async function mock_do_thi(
  page: Page,
  than: unknown,
  status = 200,
): Promise<() => string[][]> {
  const da_gui: string[][] = [];
  await page.route("**/api/do-thi", async (route) => {
    const gui = JSON.parse(route.request().postData() ?? "{}") as { hyperedge_ids?: string[] };
    da_gui.push(gui.hyperedge_ids ?? []);
    const noi_dung =
      typeof than === "function"
        ? (than as (lan: number) => unknown)(da_gui.length)
        : than;
    await route.fulfill({
      status,
      contentType: "application/json",
      body: typeof noi_dung === "string" ? noi_dung : JSON.stringify(noi_dung),
    });
  });
  return () => da_gui;
}


// --- Đường demo ba nhịp (story 4.7) -----------------------------------------
//
// Story 4.7 thêm **một** đồ dùng ở đây, và nới `mock_hoi_dap` nhận thêm dạng
// hàm thay vì dựng một helper thứ hai cạnh nó: ba nhịp còn lại dựng từ
// `envelope`/`trich_dan`/`node_vong`/`mock_do_thi` đã có.

/** Một phiên **đổi được**: `mock_toi_dong` đọc nó ở mỗi lời gọi.
 *
 *  Dời từ `xem-nhu.spec.ts` sang đây ở story 4.7 vì spec thứ hai cần đúng nó:
 *  hai bản chép của cùng một đồ dùng là hai bản lệch nhau ở lần sửa đầu, đúng
 *  lý do vòng review 4.3 dựng ra file này. */
export function phien_song() {
  let hien_tai: unknown = { ...PHIEN };
  return {
    doc: () => hien_tai,
    doi: (vai: string | null) => {
      hien_tai = vai === null ? { ...PHIEN } : phien_xem_nhu(vai);
    },
  };
}
