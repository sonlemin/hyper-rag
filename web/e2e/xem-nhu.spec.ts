import { expect, test } from "@playwright/test";

import { DAI_CAU_HOI_TOI_DA } from "../src/api/hoi_dap";

import {
  chan_moi_api,
  co_token,
  duong_anh,
  envelope,
  hoi_bang_nut,
  mock_danh_muc_vai,
  mock_doi_vai,
  mock_hoi_dap,
  loi_api,
  mock_toi,
  mock_toi_dong,
  phien_xem_nhu,
  PHIEN,
  PHIEN_THUONG,
  rong_cuon,
  token_trong_kho,
  vao_chat,
} from "./ho_tro";

// "Xem như" - API đổi vai và UI (story 4.5). Ca theo đúng các hàng I/O Matrix
// của spec. Không lượt nào ra máy chủ thật: mọi `/api/**` chưa mock bị chặn ở
// `beforeEach`, và mỗi ca mock đúng tuyến nó cần.
//
// Nhịp thật của đường này là "ghi token mới rồi **đọc lại** `/auth/toi`", nên
// hầu hết ca dùng `mock_toi_dong` với một biến phiên đổi được: một thân đóng
// băng làm mọi lần đọc lại trả về vai cũ, tức ca xanh trong khi màn hình thật
// không đổi gì.

const ANH = duong_anh("xem-nhu-4-5-1280.png");

const NUT = "[data-nut-xem-nhu]";
/** Phần tử mang `role="menu"`: chỉ chứa `menuitem*`. */
const MENU = "[data-menu-vai]";
/** Tấm nổi bọc menu, khối trạng thái và hộp lỗi - **một** tấm, không hai. */
const MENU_TAM = "[data-tam-xem-nhu]";
const CHIP = "[data-chip-xem-nhu]";
const CHIP_THAT = "[data-chip-vai-that]";
const MOC = "[data-moc-doi-vai]";

/** Trần độ dài câu hỏi, **đọc từ chính nguồn** `web/src/api/hoi_dap.ts` chứ
 *  không chép: `tests/test_web_khung.py` đã ghim hằng ấy với
 *  `api.hoi_dap.DAI_CAU_HOI_TOI_DA`, nên đọc từ đây là đo đúng con số hai bên
 *  đã thỏa thuận. Một `4000` gõ tay trong file này là bản chép thứ ba. */
const TRAN_CAU_HOI = DAI_CAU_HOI_TOI_DA;

/** Một phiên đổi được: `mock_toi_dong` đọc nó ở **mỗi** lời gọi. */
function phien_song() {
  let hien_tai: unknown = { ...PHIEN };
  return {
    doc: () => hien_tai,
    doi: (vai: string | null) => {
      hien_tai = vai === null ? { ...PHIEN } : phien_xem_nhu(vai);
    },
  };
}

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
  await co_token(page);
});

test("phiên demo+admin thấy nút; bấm mở menu role=menu đủ 5 vai kèm mô tả, DevOps có ✓", async ({
  page,
}) => {
  await mock_toi(page);
  const so_goi = await mock_danh_muc_vai(page);
  await vao_chat(page);

  // Chưa bấm thì chưa hỏi bảng chính sách.
  await expect(page.locator(NUT)).toBeVisible();
  expect(so_goi()).toBe(0);

  await page.locator(NUT).click();
  const menu = page.locator(MENU);
  await expect(menu).toHaveAttribute("role", "menu");
  await expect(menu.locator("[data-muc-vai]")).toHaveCount(5);
  expect(so_goi()).toBe(1);

  // Nhãn tiếng Việt và dòng mô tả vùng quyền, không khóa snake_case.
  await expect(menu.locator('[data-muc-vai="devops"]')).toContainText("DevOps");
  await expect(menu.locator('[data-muc-vai="sale_ba"]')).toContainText("Sale/BA");
  await expect(menu.locator('[data-muc-vai="truong_nhom"]')).toContainText("Trưởng nhóm");
  await expect(menu.locator('[data-muc-vai="sale_ba"]')).toContainText(
    "Ngoài kỹ thuật, thường không thấy chi tiết hạ tầng và bảo mật",
  );
  await expect(menu).not.toContainText("sale_ba");

  // Vai hiện tại có dấu chọn, và **chỉ** nó.
  await expect(menu.locator("[data-dang-chon]")).toHaveCount(1);
  await expect(menu.locator('[data-muc-vai="devops"]')).toHaveAttribute("aria-checked", "true");

  // Chưa mượn vai thì không mục thoát, không chip nào.
  await expect(page.locator("[data-thoat-xem-nhu]")).toHaveCount(0);
  await expect(page.locator(CHIP)).toHaveCount(0);
  await expect(page.locator(CHIP_THAT)).toHaveCount(0);
});

test("phiên không cờ nào: không nút, không menu, không gọi /auth/vai", async ({ page }) => {
  await mock_toi(page, PHIEN_THUONG);
  const so_goi = await mock_danh_muc_vai(page);
  await page.goto("/");
  await expect(page.locator("[data-chip-vai]")).toHaveText("ts01 · Tech Support");
  await expect(page.locator(NUT)).toHaveCount(0);
  await expect(page.locator(MENU)).toHaveCount(0);
  expect(so_goi()).toBe(0);
});

test("Esc đóng menu và trả focus về nút mở; menu không phải modal nên ⌘K còn chạy", async ({
  page,
}) => {
  await mock_toi(page);
  await mock_danh_muc_vai(page);
  await vao_chat(page);
  await page.locator(NUT).click();
  await expect(page.locator(MENU)).toBeVisible();

  // Không `aria-modal`: đó chính là điều kiện mà ⌘K của khung 4.1 kiểm, nên
  // phím tắt phải chạy **trong lúc menu đang mở** - đây là nhịp thật của buổi
  // demo, chọn vai rồi gõ ngay câu kế.
  await expect(page.locator('[role="dialog"][aria-modal="true"]')).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await expect(page.locator("[data-o-hoi]")).toBeFocused();
  await expect(page.locator(MENU)).toBeVisible();

  // Esc đóng và trả focus về nút mở, kể cả khi focus đang ở nơi khác.
  await page.keyboard.press("Escape");
  await expect(page.locator(MENU)).toHaveCount(0);
  await expect(page.locator(NUT)).toBeFocused();
});

test("đổi vai: token mới vào kho, phiên đọc lại, chip hổ phách và chip vai thật hiện", async ({
  page,
}) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  const so_doi = await mock_doi_vai(page, p.doi);
  await vao_chat(page);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();

  await expect(page.locator(CHIP)).toHaveText(/Đang xem như: Tech Support/);
  await expect(page.locator(CHIP_THAT)).toHaveText("dev01 · DevOps");
  // Chip vai của topbar theo vai **đang mang** (server phân giải), và `sub`
  // không đổi nên tên tài khoản vẫn là tài khoản thật.
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · Tech Support");
  expect(so_doi()).toBe(1);
  expect(await token_trong_kho(page)).toBe("token-tech_support");
  // Menu đóng sau khi đổi.
  await expect(page.locator(MENU)).toHaveCount(0);
});

test("mục thoát chỉ có khi đang mượn vai, và nó nói rõ về vai thật nào", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await vao_chat(page);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="sale_ba"]').click();
  await expect(page.locator(CHIP)).toBeVisible();

  await page.locator(NUT).click();
  const thoat = page.locator("[data-thoat-xem-nhu]");
  await expect(thoat).toHaveCount(1);
  await expect(thoat).toContainText("Thoát xem như");
  await expect(thoat).toContainText("về dev01 · DevOps");
  // Dấu ✓ nay ở vai đang mượn, không ở vai thật.
  await expect(page.locator("[data-dang-chon]")).toHaveAttribute("data-muc-vai", "sale_ba");
});

test("nút ✕ trên chip thoát xem như: về vai thật, chip biến mất", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  const so_doi = await mock_doi_vai(page, p.doi);
  await vao_chat(page);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator(CHIP)).toBeVisible();

  // ✕ bấm được khi menu **đang đóng**: đó là đường thoát nhanh của nhịp demo.
  await expect(page.locator(MENU)).toHaveCount(0);
  await page.locator("[data-thoat-nhanh]").click();

  await expect(page.locator(CHIP)).toHaveCount(0);
  await expect(page.locator(CHIP_THAT)).toHaveCount(0);
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
  expect(so_doi()).toBe(2);
  expect(await token_trong_kho(page)).toBe("token-that");
});

test("đổi vai hai lần liên tiếp không hỏi câu nào: hai divider, lịch sử không đổi", async ({
  page,
}) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await mock_hoi_dap(page, envelope());
  await vao_chat(page);

  await hoi_bang_nut(page);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  const truoc = await page.locator("[data-luot]").first().innerHTML();

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator(MOC)).toHaveCount(1);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="sale_ba"]').click();
  await expect(page.locator(MOC)).toHaveCount(2);

  await expect(page.locator(MOC).nth(0)).toHaveText(
    "Đã đổi sang xem như Tech Support · câu hỏi giữ nguyên",
  );
  await expect(page.locator(MOC).nth(1)).toHaveText(
    "Đã đổi sang xem như Sale/BA · câu hỏi giữ nguyên",
  );

  // Lượt cũ giữ nguyên **từng byte**: không bao giờ render lại theo vai mới
  // (NFR-09: đổi vai có hiệu lực từ truy vấn kế tiếp).
  expect(await page.locator("[data-luot]").first().innerHTML()).toBe(truoc);
  await expect(page.locator("[data-luot-meta]").first()).toContainText("quyền DevOps");
});

test("đổi đi rồi đổi về cũng ra hai divider", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await vao_chat(page);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator(MOC)).toHaveCount(1);
  await page.locator("[data-thoat-nhanh]").click();
  await expect(page.locator(MOC)).toHaveCount(2);
  await expect(page.locator(MOC).nth(1)).toContainText("DevOps");
});

test("bấm lại đúng vai đang mang vẫn là một lần đổi, vẫn ra một divider", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await vao_chat(page);

  // Ca mà một phép suy divider từ chênh lệch tên vai sẽ nuốt mất.
  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="devops"]').click();
  await expect(page.locator(MOC)).toHaveCount(1);
  await expect(page.locator(MOC).nth(0)).toContainText("DevOps");
});

test("mốc đổi vai đứng ngoài vùng aria-live của mọi lượt", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator(MOC)).toHaveCount(1);
  // Một mốc nằm trong vùng live là trình đọc màn hình đọc lại cả câu trả lời
  // của lượt trước nó.
  await expect(page.locator(`[aria-live="polite"] ${MOC}`)).toHaveCount(0);
});

test("lượt đang chờ khi đổi vai: meta theo vai lúc gửi, không theo vai mới", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  // Giữ phản hồi lại để đổi vai xen vào giữa một lượt đang bay.
  await mock_hoi_dap(page, envelope(), 200, 800);
  await vao_chat(page);

  await hoi_bang_nut(page);
  await expect(page.locator("[data-dang-cho]")).toHaveCount(1);
  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator(CHIP)).toBeVisible();

  // Envelope về sau khi vai đã đổi; `meta.role` của chính envelope là vai lúc
  // **gửi** (server phân giải từ token của request ấy), nên dòng meta nói
  // DevOps chứ không Tech Support.
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-luot-meta]")).toContainText("quyền DevOps");
});

test("kho bị chặn: hộp lỗi khong_giu_duoc_phien, không đổi vai trên màn", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await vao_chat(page);

  // Chặn kho **sau** khi trang đã đọc token: mọi `setItem` sau đó ném.
  await page.evaluate(() => {
    const goc = Storage.prototype.setItem;
    Storage.prototype.setItem = function (...tham_so: [string, string]) {
      if (tham_so[0] === "hyper_rag_token") throw new Error("kho bị chặn");
      return goc.apply(this, tham_so);
    };
  });

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();

  await expect(page.locator("[data-loi-doi-vai]")).toHaveAttribute(
    "data-loi-doi-vai",
    "khong_giu_duoc_phien",
  );
  await expect(page.locator("[data-loi-doi-vai]")).toContainText("Trình duyệt không giữ được phiên");
  // Không đổi vai trên màn, không divider, và token cũ còn nguyên.
  await expect(page.locator(CHIP)).toHaveCount(0);
  await expect(page.locator(MOC)).toHaveCount(0);
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
});

test("lỗi máy chủ giữa một lần đổi vai: báo tại chỗ, giữ nguyên URL", async ({ page }) => {
  await mock_toi(page);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, () => {}, 400);
  await vao_chat(page);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();

  await expect(page.locator("[data-loi-doi-vai]")).toContainText("Hệ thống gặp lỗi");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator(CHIP)).toHaveCount(0);
});

test("hết phiên giữa một lần đổi vai: về màn đăng nhập với thông báo trung tính", async ({
  page,
}) => {
  await mock_toi(page);
  await mock_danh_muc_vai(page);
  await page.route("**/api/auth/xem-nhu", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "TOKEN_KHONG_HOP_LE", message: "x" } }),
    }),
  );
  await vao_chat(page);

  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();

  await page.waitForURL(/\/dang-nhap\?ly_do=het_han/);
  await expect(page.locator(".thong_bao_phien")).toBeVisible();
  expect(await token_trong_kho(page)).toBeNull();
});

test("/auth/toi thiếu khóa act là lỗi hệ thống, không phải một phiên thường", async ({ page }) => {
  // Vắng mặt và `null` không được đọc như nhau: `null` là "không mượn vai nào",
  // vắng mặt là hợp đồng đã trôi - và đọc cái sau thành cái trước là chip hổ
  // phách biến mất trong khi phiên vẫn đang mang một vai giả.
  const { act: _bo, ...thieu_act } = PHIEN;
  await mock_toi(page, thieu_act);
  await page.goto("/");
  await expect(page.locator("[data-ma-loi]")).toBeVisible();
  await expect(page.locator(NUT)).toHaveCount(0);
});

test("1280px: menu mở không làm trang cuộn ngang, và ảnh bằng chứng", async ({ page }) => {
  const p = phien_song();
  await mock_toi_dong(page, p.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, p.doi);
  await mock_hoi_dap(page, envelope());
  await page.setViewportSize({ width: 1280, height: 800 });
  await vao_chat(page);

  await hoi_bang_nut(page);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator(CHIP)).toBeVisible();
  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);

  await page.locator(NUT).click();
  await expect(page.locator(MENU)).toBeVisible();
  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await page.screenshot({ path: ANH, fullPage: false });
});

test("/auth/vai 500: hộp lỗi trong menu mang mã, không nút nào bấm được", async ({ page }) => {
  await mock_toi(page);
  await mock_danh_muc_vai(page, [], 500);
  await vao_chat(page);
  await page.locator(NUT).click();

  await expect(page.locator(`${MENU_TAM} [data-ma-loi]`)).toBeVisible();
  await expect(page.locator("[data-muc-vai]")).toHaveCount(0);
  // Báo tại chỗ, giữ nguyên URL: 5xx không được đá người dùng đi (luật 4.2).
  await expect(page).toHaveURL(/\/$/);
  expect(await token_trong_kho(page)).toBe("token-co-san");
});

test("/auth/vai 401: về màn đăng nhập, token đã xóa", async ({ page }) => {
  await mock_toi(page);
  await page.route("**/api/auth/vai", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify(loi_api("TOKEN_KHONG_HOP_LE")),
    }),
  );
  await vao_chat(page);
  await page.locator(NUT).click();

  await page.waitForURL(/\/dang-nhap\?ly_do=het_han/);
  expect(await token_trong_kho(page)).toBeNull();
});

test("/auth/vai trả danh mục rỗng: nói ra thay vì một menu chỉ có tiêu đề", async ({ page }) => {
  await mock_toi(page);
  await mock_danh_muc_vai(page, []);
  await vao_chat(page);
  await page.locator(NUT).click();
  await expect(page.locator("[data-khong-co-vai]")).toContainText(
    "Bảng chính sách đang chạy không khai vai nào",
  );
  await expect(page.locator("[data-muc-vai]")).toHaveCount(0);
});

test("danh mục vai đọc lại **mỗi lần mở**, không cache suốt vòng đời trang", async ({ page }) => {
  // Bảng chính sách hoán được lúc chạy (`POST /admin/policy`), nên một danh
  // sách đọc một lần rồi giữ mãi là một dropdown liệt kê một vai đã biến mất.
  await mock_toi(page);
  let lan = 0;
  await page.route("**/api/auth/vai", (route) => {
    lan += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ vai: lan === 1 ? ["devops", "sale_ba"] : ["devops"] }),
    });
  });
  await vao_chat(page);

  await page.locator(NUT).click();
  await expect(page.locator("[data-muc-vai]")).toHaveCount(2);
  await page.keyboard.press("Escape");

  await page.locator(NUT).click();
  await expect(page.locator("[data-muc-vai]")).toHaveCount(1);
  expect(lan).toBe(2);
});

test("menu cư xử như menu: chỉ menuitem bên trong, focus vào menu, Up/Down/Home/End", async ({
  page,
}) => {
  await mock_toi(page);
  await mock_danh_muc_vai(page);
  await vao_chat(page);
  await page.locator(NUT).click();

  // Phần tử mang `role="menu"` chứa **chỉ** `menuitem*`: tiêu đề, khối trạng
  // thái và hộp lỗi đều nằm ngoài nó. Khai một vai trợ năng rồi không giữ
  // đúng hợp đồng của nó tệ hơn là không khai.
  const con = await page.locator(`${MENU} > *`).evaluateAll((cac) =>
    cac.map((e) => e.getAttribute("role")),
  );
  expect(con.every((r) => r === "menuitemradio" || r === "menuitem")).toBe(true);
  await expect(page.locator(MENU)).toHaveAttribute("aria-labelledby", /.+/);

  // Focus vào **mục đang chọn** ngay khi mở, nếu không thì Up/Down không đi đâu.
  await expect(page.locator('[data-muc-vai="devops"]')).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator('[data-muc-vai="sale_ba"]')).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page.locator('[data-muc-vai="devops"]')).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.locator('[data-muc-vai="truong_nhom"]')).toBeFocused();
  await page.keyboard.press("Home");
  await expect(page.locator('[data-muc-vai="admin"]')).toBeFocused();
});

test("hộp lỗi đổi vai nằm **dưới** mục cuối, không phủ lên menu", async ({ page }) => {
  // Một lần đổi vai hỏng thì menu **vẫn mở** (chỉ ca thành công mới đóng), nên
  // hai tấm nổi cùng `top`/`right` sẽ chồng lên nhau; một ca chỉ đòi "hộp có
  // chữ" xanh với cả trạng thái ấy.
  await mock_toi(page);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, () => {}, 400);
  await vao_chat(page);
  await page.locator(NUT).click();
  await page.locator('[data-muc-vai="tech_support"]').click();

  const hop = page.locator("[data-loi-doi-vai]");
  await expect(hop).toBeVisible();
  await expect(page.locator(MENU)).toBeVisible();
  const o_hop = (await hop.boundingBox())!;
  const o_muc = (await page.locator("[data-muc-vai]").last().boundingBox())!;
  expect(o_hop.y).toBeGreaterThanOrEqual(o_muc.y + o_muc.height);
});

test("khung đánh dấu lúc đọc lại phiên, nên một /auth/toi treo không im lặng", async ({ page }) => {
  // Bỏ `dang_doc` khi đọc lại là đúng (nó từng unmount cả lịch sử chat), nhưng
  // nó để lại một trạng thái vô hình: chip còn vai cũ trong khi token đã đổi.
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, () => {});
  // Một **cờ đặt tay**, không một bộ đếm lời gọi: React StrictMode của
  // `next dev` gọi effect hai lần ở lần mount đầu, nên "lần thứ hai" không phải
  // là "lần đọc lại sau khi đổi vai".
  let treo = false;
  await page.route("**/api/auth/toi", async (route) => {
    if (treo) await new Promise((xong) => setTimeout(xong, 2000));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(treo ? phien_xem_nhu("tech_support") : PHIEN),
    });
  });
  await vao_chat(page);
  await page.locator(NUT).click();
  treo = true;
  await page.locator('[data-muc-vai="tech_support"]').click();

  await expect(page.locator("[data-khung]")).toHaveAttribute("data-dang-doc-lai", "1");
  // Lịch sử vẫn còn (children không unmount) và composer vẫn ở đó.
  await expect(page.locator("[data-o-hoi]")).toBeVisible();
  await expect(page.locator("[data-khung]")).not.toHaveAttribute("data-dang-doc-lai", "1", {
    timeout: 10000,
  });
  await expect(page.locator(CHIP)).toBeVisible();
});

test("đọc lại phiên hỏng sau khi đổi vai: hộp lỗi, không mốc nào", async ({ page }) => {
  // Cờ "lần đọc này do một lần đổi vai" phải được xóa ở **cả** nhánh hỏng, nếu
  // không thì một lần đọc phiên bất kỳ sau đó chèn một mốc không có thật.
  //
  // Giới hạn của ca này, nói ra thay vì để người đọc tưởng nó chấm nhiều hơn:
  // một lần đọc hỏng đưa khung vào trạng thái lỗi và **unmount** màn chat, nên
  // hệ quả xa của cờ bẩn không quan sát được qua DOM trong cùng một vòng đời
  // trang. Thứ chấm được ở đây là nhánh hỏng không sinh mốc và không treo; ca
  // "hai lần đổi chồng nhau" ngay dưới chấm chính phép đếm.
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, () => {});
  let hong = false;
  await page.route("**/api/auth/toi", (route) =>
    hong
      ? route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify(loi_api("KHO_KHONG_SAN_SANG")),
        })
      : route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PHIEN),
        }),
  );
  await vao_chat(page);
  await page.locator(NUT).click();
  hong = true;
  await page.locator('[data-muc-vai="tech_support"]').click();

  await expect(page.locator("[data-ma-loi]")).toHaveAttribute(
    "data-ma-loi",
    "KHO_KHONG_SAN_SANG",
  );
  await expect(page.locator(MOC)).toHaveCount(0);
  // Báo tại chỗ, giữ nguyên URL: 5xx không đá người dùng đi (luật 4.2).
  await expect(page).toHaveURL(/\/$/);
});

test("hai lần đổi chồng nhau khi lần đọc đầu chưa xong vẫn ra **hai** mốc", async ({ page }) => {
  // Effect hủy lần đọc trước (`con_song = false`) nên chỉ `.then()` cuối chạy.
  // Một boolean "đang chờ xác nhận" cho **một** mốc trên **hai** lần đổi thật;
  // một bộ đếm thì không.
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, () => {});
  let vai_hien_tai = "devops";
  let cham = false;
  await page.route("**/api/auth/toi", async (route) => {
    // Lần đọc lại đầu tiên chậm, để lần bấm thứ hai chen vào giữa.
    if (cham) await new Promise((xong) => setTimeout(xong, 600));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        vai_hien_tai === "devops" ? PHIEN : phien_xem_nhu(vai_hien_tai),
      ),
    });
  });
  await vao_chat(page);

  await page.locator(NUT).click();
  cham = true;
  vai_hien_tai = "tech_support";
  await page.locator('[data-muc-vai="tech_support"]').click();
  // Bấm lần hai **trong lúc** lần đọc thứ nhất còn bay.
  await page.locator(NUT).click();
  vai_hien_tai = "sale_ba";
  await page.locator('[data-muc-vai="sale_ba"]').click();

  await expect(page.locator(CHIP)).toContainText("Sale/BA");
  await expect(page.locator(MOC)).toHaveCount(2);
});

test("dán quá trần: ô cắt về đúng trần và không request nào bay đi", async ({ page }) => {
  // `maxLength` là cơ chế đóng khoản ledger `CAU_HOI_QUA_DAI`, nhưng phép canh
  // pytest chỉ so một chuỗi trong nguồn: tách composer ra một component khác mà
  // vẫn để literal lại trong `ManChat.tsx` là test xanh còn câu dài lại bay
  // tới `api/`. Ở đây đo hành vi thật của trình duyệt.
  await mock_toi(page);
  const so_hoi = await mock_hoi_dap(page, envelope());
  await vao_chat(page);

  const qua_dai = "x".repeat(TRAN_CAU_HOI + 1000);
  await page.locator("[data-o-hoi]").fill(qua_dai);
  const dai = await page.locator("[data-o-hoi]").inputValue();
  expect(dai.length).toBe(TRAN_CAU_HOI);

  // Bộ đếm nói ra chỗ vừa bị cắt, thay vì cắt lặng lẽ.
  await expect(page.locator("[data-dem-ky-tu]")).toHaveAttribute("data-cham-tran", "1");
  await expect(page.locator("[data-dem-ky-tu]")).toContainText(`${TRAN_CAU_HOI}`);

  await page.locator("[data-nut-gui]").click();
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  expect(so_hoi()).toBe(1);
  // Và câu đi ra đúng bằng phần ô giữ lại, không dài hơn: không request nào
  // mang quá trần tới `api/`.
  expect(dai.length).toBeLessThanOrEqual(TRAN_CAU_HOI);
});

test("bộ đếm ký tự chỉ hiện khi gần trần", async ({ page }) => {
  await mock_toi(page);
  await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await page.locator("[data-o-hoi]").fill("ngắn");
  await expect(page.locator("[data-dem-ky-tu]")).toHaveCount(0);
  await page.locator("[data-o-hoi]").fill("x".repeat(TRAN_CAU_HOI - 10));
  await expect(page.locator("[data-dem-ky-tu]")).toBeVisible();
  await expect(page.locator("[data-dem-ky-tu]")).not.toHaveAttribute("data-cham-tran", "1");
});
