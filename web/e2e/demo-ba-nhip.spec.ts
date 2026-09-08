import { expect, test, type Page } from "@playwright/test";

import { MICROCOPY } from "../src/microcopy";
import { TOKENS } from "../src/design/bien_css";

import {
  canh_do_thi,
  chan_moi_api,
  co_token,
  duong_anh,
  envelope,
  envelope_do_thi,
  hoi_bang_nut,
  mock_danh_muc_vai,
  mock_do_thi,
  mock_doi_vai,
  mock_hoi_dap,
  mock_toi_dong,
  node_dinh,
  node_vong,
  phien_song,
  trich_dan,
  vao_chat,
} from "./ho_tro";

// Đường demo ba nhịp đầu (story 4.7). **Một phiên liên tục**: đăng nhập một
// lần, hỏi, đổi vai, hỏi lại, đổi vai, hỏi lại - đúng thứ hội đồng nhìn, và
// đúng thứ mà ba spec trước không chấm được vì mỗi spec chỉ chấm một nhịp.
//
// Ba nhịp (EXPERIENCE.md, `scripts/cong-m2.sh` B2/B4/B5):
//   1. `dev01` (DevOps) hỏi câu ghim -> câu trả lời đầy đủ, ba cite-row, bấm ô
//      số [1] mở drawer và `HE-01` sáng, hover hàng 2 sáng `HE-02`.
//   2. Xem như Tech Support, hỏi lại -> divider chèn, slab bôi đen giữa câu,
//      dòng hạn chế nêu đúng nhóm, drawer vẽ lại **có** đỉnh `•••` và đỉnh
//      không che vẫn hiện.
//   3. Xem như Sale/BA, hỏi lại -> template từ chối, 0 cite-row, dòng meta
//      không vế trích dẫn, drawer về empty-state; hai lượt trước và hai
//      divider còn nguyên.
//
// Cộng hai ca mà spec 4.7 đòi riêng: một ca **máy chiếu** (ba nhịp render dưới
// một bộ lọc tương phản thấp, chụp ảnh bằng chứng) và một ca **tooltip canvas**
// (rê chuột theo tọa độ mà gương `sr-only` phơi ra, thứ đóng khoản sổ nợ 4-7).
//
// Không lượt nào ra máy chủ thật: `chan_moi_api` chặn mọi `/api/**` chưa mock.

const ANH = duong_anh("demo-4-7-1280.png");
const ANH_MAY_CHIEU = duong_anh("may-chieu-4-7-1280.png");

/** Ba id hyperedge thật của lượt nhịp 1. Không id nào được vào DOM. */
const ID_1 = "he-3f9c1a2b3c4d5e6f70819200";
const ID_2 = "he-aa11bb22cc33dd44ee55ff66";
const ID_3 = "he-0011223344556677889900aa";

const VAI_NHIP_2 = "tech_support";
const VAI_NHIP_3 = "sale_ba";

/** Hai màu vòng focus, đọc **từ token** rồi đổi sang dạng `getComputedStyle`
 *  trả về. Chép `"rgb(31, 90, 168)"` vào đây là một bản thứ hai của một giá trị
 *  mà `tests/test_web_khung.py` đã ghim với DESIGN.md. */
function rgb(hex: string): string {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
}
const TRANG = rgb(TOKENS.colors["focus-on-dark"]);
const PRIMARY = rgb(TOKENS.colors.primary);

/** Nhịp 1: `dev01` thấy ba nguồn L2, câu trả lời đầy đủ. */
function envelope_nhip_1() {
  return envelope({
    answer: "App01 lỗi 502 vì PHP-FPM hết bộ nhớ; khắc phục bằng cách nâng pm.max_children.",
    citations: [trich_dan(ID_1), trich_dan(ID_2), trich_dan(ID_3)],
    meta: { role: "devops", space: "synth", policy_version: "day-du@1" },
  });
}

/** Nhịp 2: Tech Support thấy hai nguồn, một L1 che `cause` và `owner`.
 *
 *  `answer` mang chính dấu che ở đúng chỗ (ADR-016 prompt v2: model chép nguyên
 *  dấu che vào câu), nên slab bôi đen của 4.4 có thứ để bôi. */
function envelope_nhip_2() {
  return envelope({
    answer: "Nguyên nhân sự cố App01 lỗi 502 là [cause:masked], do [owner:DevOps] phụ trách.",
    citations: [
      trich_dan(ID_1, {
        level: "L1",
        content_type: "bao_cao_su_co",
        masked_slots: ["cause", "owner"],
        owner_group: "DevOps",
      }),
      trich_dan(ID_2),
    ],
    meta: { role: VAI_NHIP_2, space: "synth", policy_version: "day-du@1" },
  });
}

/** Nhịp 3: Sale/BA bị chặn sạch. Lượt từ chối, `answer: null`, 0 citation. */
function envelope_nhip_3() {
  return envelope({
    answer: null,
    refused: true,
    citations: [],
    meta: { role: VAI_NHIP_3, space: "synth", policy_version: "day-du@1" },
  });
}

/** Đồ thị của nhịp 1: ba vòng, `App01` dùng chung. */
function do_thi_nhip_1() {
  return envelope_do_thi(
    [
      node_vong(ID_1),
      node_vong(ID_2, { label: "chủ thể: App01; nguồn: runbook/app01.md" }),
      node_vong(ID_3, { label: "chủ thể: App01; cách xử lý: nâng pm.max_children" }),
      node_dinh("ent-app01", "App01"),
      node_dinh("ent-502", "lỗi 502"),
      node_dinh("ent-runbook", "runbook/app01.md"),
      node_dinh("ent-fix", "nâng pm.max_children"),
    ],
    [
      canh_do_thi(ID_1, "ent-app01", "subject"),
      canh_do_thi(ID_1, "ent-502", "symptom"),
      canh_do_thi(ID_2, "ent-app01", "subject"),
      canh_do_thi(ID_2, "ent-runbook", "source"),
      canh_do_thi(ID_3, "ent-app01", "subject"),
      canh_do_thi(ID_3, "ent-fix", "remediation"),
    ],
  );
}

/** Đồ thị của nhịp 2: cùng danh sách id gửi đi, server trả **ít vòng hơn** và
 *  một đỉnh `•••` - và đỉnh không che (`App01`, `lỗi 502`) vẫn hiện. Đó là câu
 *  của nhịp 2: che đúng đỉnh, không che cả cụm. */
function do_thi_nhip_2() {
  return envelope_do_thi(
    [
      node_vong(ID_1, { level: "L1", label: "chủ thể: App01; nguyên nhân: [cause:masked]" }),
      node_vong(ID_2, { label: "chủ thể: App01; nguồn: runbook/app01.md" }),
      node_dinh("ent-app01", "App01"),
      node_dinh("ent-502", "lỗi 502"),
      node_dinh("ent-runbook", "runbook/app01.md"),
      node_dinh(`${ID_1}#cause`, "[cause:masked]", { masked: true }),
    ],
    [
      canh_do_thi(ID_1, "ent-app01", "subject"),
      canh_do_thi(ID_1, "ent-502", "symptom"),
      canh_do_thi(ID_1, `${ID_1}#cause`, "cause"),
      canh_do_thi(ID_2, "ent-app01", "subject"),
      canh_do_thi(ID_2, "ent-runbook", "source"),
    ],
  );
}

/** Ba envelope theo **thứ tự lượt hỏi**, không theo vai: đường thật là "gửi
 *  câu, nhận thân", và một mock tra theo vai giấu mất ca lượt gửi trước khi vai
 *  kịp đổi. */
function ba_luot() {
  const than = [envelope_nhip_1(), envelope_nhip_2(), envelope_nhip_3()];
  return (lan: number) => than[Math.min(lan, than.length) - 1];
}

/** Đồ thị theo **thứ tự lời gọi** `/do-thi`: lời gọi đầu là của `dev01`, mọi
 *  lời gọi sau là của Tech Support (drawer gọi lại ngay lúc đổi vai, rồi gọi
 *  lại lần nữa cho lượt mới). Nhịp 3 không gọi tuyến nào - lượt từ chối có 0
 *  citation nên không request nào bay đi. */
function cac_do_thi() {
  const than = [do_thi_nhip_1(), do_thi_nhip_2()];
  return (lan: number) => than[Math.min(lan, than.length) - 1];
}

async function doi_vai(page: Page, vai: string) {
  await page.locator("[data-nut-xem-nhu]").click();
  await page.locator(`[data-muc-vai="${vai}"]`).click();
  await expect(page.locator("[data-chip-xem-nhu]")).toBeVisible();
}

async function cho_ve_xong(page: Page) {
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-da-ve", "1");
}

/** Dựng trọn một phiên demo: ba tuyến mock đọc **động**, một lần vào chat. */
async function vao_demo(page: Page) {
  const phien = phien_song();
  await mock_toi_dong(page, phien.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, phien.doi);
  const so_hoi = await mock_hoi_dap(page, ba_luot());
  const da_gui = await mock_do_thi(page, cac_do_thi());
  await vao_chat(page);
  return { so_hoi, da_gui };
}

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
  await co_token(page);
});

test("ba nhịp liên tiếp trong **một** phiên, lịch sử và divider còn nguyên ở nhịp cuối", async ({
  page,
}) => {
  const { so_hoi, da_gui } = await vao_demo(page);

  // --- Nhịp 1: DevOps hỏi, ba cite-row, mở drawer bằng ô số [1] --------------
  await hoi_bang_nut(page);
  await expect(page.locator("[data-cite-row]")).toHaveCount(3);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-luot-meta]").last()).toContainText("DevOps");
  await expect(page.locator("[data-luot-meta]").last()).toContainText("3 trích dẫn");

  await page.locator('[data-cite-so="HE-01"]').click();
  await cho_ve_xong(page);
  await expect.poll(() => da_gui().length).toBe(1);
  expect(da_gui()).toEqual([[ID_1, ID_2, ID_3]]);
  await expect(page.locator("[data-drawer-do-thi]")).toHaveAttribute("data-ma-sang", "HE-01");
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-vong", "3");

  // Hover hàng 2 sáng đúng `HE-02` kèm chú thích chữ (tín hiệu phi màu).
  await page.locator("[data-cite-row]").nth(1).hover();
  await expect(page.locator("[data-drawer-do-thi]")).toHaveAttribute("data-ma-sang", "HE-02");
  await expect(page.locator('[data-dang-sang="HE-02"]')).toHaveCount(1);
  await page.mouse.move(2, 2);

  // --- Nhịp 2: xem như Tech Support, hỏi lại --------------------------------
  await doi_vai(page, VAI_NHIP_2);
  await expect(page.locator("[data-moc-doi-vai]")).toHaveCount(1);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(2);

  // Slab bôi đen giữa câu, và **không** một `[cause:masked]` trần nào trên màn.
  const luot_2 = page.locator("[data-tra-loi]").nth(1);
  await expect(luot_2.locator("[data-slab]")).toHaveCount(2);
  await expect(luot_2).toContainText("nguyên nhân: che");
  await expect(luot_2).toContainText("người phụ trách: DevOps");
  await expect(luot_2).not.toContainText("[cause:masked]");

  // Dòng hạn chế nêu **đúng nhóm** của citation L1 ấy.
  const han_che = page.locator("[data-han-che]");
  await expect(han_che).toHaveCount(1);
  await expect(han_che).toContainText("DevOps");
  await expect(han_che).toContainText("nguyên nhân");

  // Drawer vẽ lại **hai** lần trong nhịp này, và đó là hành vi đúng của 4.6:
  // một lần ngay khi đổi vai (cùng lượt cũ, cùng ba id, server lọc lại - đó là
  // câu "server lọc lại toàn bộ theo token" của ADR-018), rồi một lần nữa khi
  // lượt mới về với hai citation. Cả ba lần đều gửi **đúng** danh sách id mà
  // `/hoi-dap` của lượt đang vẽ vừa trả, không một danh sách do client dựng.
  //
  // `expect.poll` trước khi đọc danh sách: `cho_ve_xong` chỉ nói "một đồ thị đã
  // vẽ xong", và lời gọi thứ hai của nhịp này có thể chưa về lúc ấy - đọc
  // `da_gui()` ngay là đọc một danh sách còn thiếu một mục, tức một ca đỏ chớp
  // nháy nói sai nguyên nhân.
  await cho_ve_xong(page);
  await expect.poll(() => da_gui().length).toBe(3);
  expect(da_gui()).toEqual([
    [ID_1, ID_2, ID_3],
    [ID_1, ID_2, ID_3],
    [ID_1, ID_2],
  ]);
  const vung = page.locator("[data-vung-do-thi]");
  await expect(vung).toHaveAttribute("data-so-vong", "2");
  // Có đỉnh `•••` **và** đỉnh không che vẫn hiện: che đúng đỉnh, không cả cụm.
  await expect(vung).toHaveAttribute("data-so-dinh-che", "1");
  await expect(page.locator('[data-guong-dinh][data-che="1"]')).toHaveText("•••");
  // Khớp **trọn** nhãn: `runbook/app01.md` cũng chứa chuỗi "app01", và một phép
  // so chuỗi con ở đây báo xanh cho một đỉnh khác hẳn đỉnh đang nói tới.
  const guong = page.locator("[data-guong-dinh]");
  await expect(guong.filter({ hasText: /^App01$/ })).toHaveCount(1);
  await expect(guong.filter({ hasText: /^lỗi 502$/ })).toHaveCount(1);

  // --- Nhịp 3: xem như Sale/BA, hỏi lại -------------------------------------
  await doi_vai(page, VAI_NHIP_3);
  await expect(page.locator("[data-moc-doi-vai]")).toHaveCount(2);
  // Lần đổi vai này cũng làm drawer đọc lại lượt cũ dưới vai mới (đúng luật
  // của 4.6). Chốt số lời gọi **ngay trước** lượt hỏi để vế dưới đo đúng thứ
  // nó muốn đo: lượt từ chối không sinh request nào.
  await cho_ve_xong(page);
  await expect.poll(() => da_gui().length).toBe(4);
  const truoc_nhip_3 = da_gui().length;
  await hoi_bang_nut(page);
  await expect(page.locator("[data-tu-choi]")).toHaveCount(1);

  // Template trung tính, 0 cite-row, dòng meta **không** vế "n trích dẫn".
  const luot_3 = page.locator("[data-tu-choi]");
  await expect(luot_3.locator("[data-cite-row]")).toHaveCount(0);
  const meta_3 = luot_3.locator("[data-luot-meta]");
  await expect(meta_3).not.toContainText("trích dẫn");
  await expect(luot_3).toContainText(MICROCOPY.tu_choi);

  // Drawer về đúng empty-state, và **không** một lời gọi `/do-thi` thứ ba.
  await expect(page.locator("[data-do-thi-trong]")).toHaveCount(1);
  await expect(page.locator("[data-vung-do-thi]")).toHaveCount(0);
  expect(da_gui()).toHaveLength(truoc_nhip_3);
  // Và mọi lời gọi đã bay đi đều mang **đúng** danh sách id của lượt nó vẽ,
  // không một danh sách nào do client dựng hay cắt bớt.
  expect(da_gui()).toEqual([
    [ID_1, ID_2, ID_3],
    [ID_1, ID_2, ID_3],
    [ID_1, ID_2],
    [ID_1, ID_2],
  ]);

  // --- Lịch sử: ba lượt và hai divider còn nguyên trên màn -------------------
  expect(so_hoi()).toBe(3);
  await expect(page.locator("[data-luot]")).toHaveCount(3);
  await expect(page.locator("[data-moc-doi-vai]")).toHaveCount(2);
  // Lượt 1 vẫn ghi vai đã hỏi nó, không bị viết lại theo vai đang xem.
  await expect(page.locator("[data-luot-meta]").first()).toContainText("DevOps");
  await expect(page.locator("[data-luot]").nth(1).locator("[data-luot-meta]")).toContainText(
    "Tech Support",
  );

  await page.screenshot({ path: ANH, fullPage: false });
});

test("hai lượt từ chối của hai vai khác nhau: thân giống hệt, chỉ dòng meta khác", async ({
  page,
}) => {
  // Lý do từ chối chỉ nằm trong audit (AD-8), nên hai lượt từ chối phải ra
  // **cùng một** DOM. Hai lượt mock **cùng một thân** thì phép so gần như hằng
  // đúng và ca này không đo gì; nên hai lượt ở đây khác nhau ở một thứ thật -
  // `meta.role`, tức vai đã hỏi - và ca khẳng định hai điều tách nhau: dòng
  // meta **có** khác (nó nói vai, và vai là thứ duy nhất được phép khác), còn
  // phần thân của lượt thì giống hệt từng byte.
  const phien = phien_song();
  await mock_toi_dong(page, phien.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, phien.doi);
  await mock_hoi_dap(page, (lan: number) =>
    envelope({
      answer: null,
      refused: true,
      citations: [],
      meta: {
        role: lan === 1 ? VAI_NHIP_2 : VAI_NHIP_3,
        space: "synth",
        policy_version: "day-du@1",
      },
    }),
  );
  await vao_chat(page);
  await doi_vai(page, VAI_NHIP_2);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-tu-choi]")).toHaveCount(1);
  await doi_vai(page, VAI_NHIP_3);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-tu-choi]")).toHaveCount(2);

  const luot = page.locator("[data-tu-choi]");
  // Dòng meta khác, và khác đúng ở tên vai.
  const meta_1 = await luot.nth(0).locator("[data-luot-meta]").innerText();
  const meta_2 = await luot.nth(1).locator("[data-luot-meta]").innerText();
  expect(meta_1).not.toBe(meta_2);
  expect(meta_1).toContain("Tech Support");
  expect(meta_2).toContain("Sale/BA");
  // Không dòng nào mang vế "n trích dẫn".
  expect(meta_1).not.toContain("trích dẫn");
  expect(meta_2).not.toContain("trích dẫn");
  // Phần thân - câu template và mọi thứ ngoài dòng meta - giống hệt từng byte.
  const than = async (i: number) =>
    luot.nth(i).evaluate((el) => {
      const ban = el.cloneNode(true) as HTMLElement;
      ban.querySelector("[data-luot-meta]")?.remove();
      return ban.innerHTML;
    });
  expect(await than(1)).toBe(await than(0));
});

test("tooltip canvas: rê chuột lên đúng tọa độ một đỉnh ••• hiện Cần quyền L2", async ({
  page,
}) => {
  // Khoản sổ nợ địa chỉ 4-7: Cytoscape vẽ vào `<canvas>` nên một node không
  // phải một phần tử DOM, và trước story này không phép kiểm tự động nào rê
  // chuột tới được một đỉnh mờ. Gương `sr-only` nay phơi tọa độ **đã render**
  // của từng node, nên một ca test đưa chuột tới đúng chỗ mà không phải phơi
  // `cy` ra `window`.
  const phien = phien_song();
  await mock_toi_dong(page, phien.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, phien.doi);
  await mock_hoi_dap(page, () => envelope_nhip_2());
  await mock_do_thi(page, do_thi_nhip_2());
  await vao_chat(page);
  await hoi_bang_nut(page);
  await page.locator("[data-nut-do-thi]").click();
  await cho_ve_xong(page);

  const guong = page.locator('[data-guong-dinh][data-che="1"]');
  await expect(guong).toHaveCount(1);
  // `getAttribute` trả `null` khi gương mất tọa độ, và `Number(null)` là `0`
  // với `Number.isFinite(0)` đúng - tức phép canh cũ bỏ lọt đúng ca nó sinh ra
  // để bắt, rồi ca hỏng ở bước rê chuột với một thông điệp nói sai nguyên nhân.
  const tho_x = await guong.getAttribute("data-x");
  const tho_y = await guong.getAttribute("data-y");
  expect(tho_x, "gương đỉnh mất `data-x`").not.toBeNull();
  expect(tho_y, "gương đỉnh mất `data-y`").not.toBeNull();
  const x = Number(tho_x);
  const y = Number(tho_y);
  expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);

  // Tọa độ là px trong hệ của `.vung_do_thi` (canvas là `inset: 0` bên trong
  // nó), nên chỗ rê chuột là góc của canvas cộng tọa độ ấy.
  const hop = await page.locator(".vung_do_thi__canvas").boundingBox();
  expect(hop).not.toBeNull();
  await page.mouse.move(hop!.x + x, hop!.y + y);
  const tooltip = page.locator("[data-tooltip-node]");
  await expect(tooltip).toHaveCount(1);
  await expect(tooltip).toHaveText("Cần quyền L2");

  // Rời khỏi đỉnh thì tooltip biến mất: nó là chỉ báo của một đỉnh, không một
  // chú thích lơ lửng.
  await page.mouse.move(hop!.x + 2, hop!.y + 2);
  await expect(page.locator("[data-tooltip-node]")).toHaveCount(0);
});

test("chụp ảnh bằng chứng ở điều kiện máy chiếu, và vòng focus dùng đúng token", async ({
  page,
}) => {
  // **Tên ca nói đúng thứ nó làm.** Bốn `expect` dưới đây chấm rằng bốn phần
  // tử *có mặt* dưới bộ lọc, và chúng xanh y hệt ở `contrast(0)` - một bộ lọc
  // CSS không đổi cây DOM. Phép đo tương phản thật nằm ở hai chỗ khác: nhóm
  // (14) của `tests/test_web_khung.py` tính trên token bằng cùng mô hình
  // (`mo_phong_may_chieu`, k = 0,7), và mắt người ở `kiem-tay-4-7.md` mục 2.
  // Việc của ca này là dựng ra **ảnh bằng chứng** ở đúng điều kiện buổi bảo vệ
  // chạy, cộng một phép đo thật: màu vòng focus đọc từ `getComputedStyle`.
  const phien = phien_song();
  await mock_toi_dong(page, phien.doc);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, phien.doi);
  await mock_hoi_dap(page, () => envelope_nhip_2());
  await mock_do_thi(page, do_thi_nhip_2());
  await vao_chat(page);
  await page.addStyleTag({ content: "html { filter: contrast(0.7); }" });
  await hoi_bang_nut(page);
  await page.locator("[data-nut-do-thi]").click();
  await cho_ve_xong(page);

  await expect(page.locator("[data-slab]").first()).toBeVisible();
  await expect(page.locator("[data-badge-muc]").first()).toHaveText("L1");
  await expect(page.locator("[data-han-che]")).toBeVisible();
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-dinh-che", "1");

  // Vòng focus, **ba** phép đo chứ một: luật theo vùng và hai ngoại lệ của nó.
  // Nút "Xem như" nằm trên nền `primary-deep` nên vòng phải trắng; hai đảo nền
  // **sáng** bên trong `.topbar` thì phải quay về xanh thép, nếu không phép sửa
  // của story này lật ngược thành vòng trắng trên nền trắng (mục menu) và vòng
  // trắng trên nền hổ phách 1,10:1 (nút ✕ của chip).
  // Đọc **màu vòng focus thật** của ba phần tử, mỗi cái ở đúng cách người dùng
  // tới nó. `:focus-visible` là một heuristic về "đang đi bằng bàn phím", nên
  // cách đưa focus vào là một phần của phép đo: một `.focus()` từ script trên
  // một `tabindex="-1"` (mục menu) **không** khớp `:focus-visible`, và khi ấy
  // `outlineColor` trả về `currentColor` của phần tử - một con số trông như
  // một câu trả lời mà không phải. Ca khẳng định `matches(":focus-visible")`
  // trước khi đọc màu, nên chỗ hỏng nói đúng nguyên nhân.
  const mau_vong_focus = async (chon: string) => {
    const o = page.locator(chon);
    expect(await o.evaluate((e) => e.matches(":focus-visible")), chon).toBe(true);
    return o.evaluate((e) => getComputedStyle(e).outlineColor);
  };
  /** Đưa focus vào một phần tử **theo lối bàn phím**: một phím vô hại đặt lại
   *  "modality" của trình duyệt trước, vì sau một cú bấm chuột (mở drawer ở
   *  trên) thì `.focus()` từ script không còn khớp `:focus-visible`. */
  const focus_bang_ban_phim = async (chon: string) => {
    await page.keyboard.press("Shift");
    await page.locator(chon).focus();
  };

  // Một, nút trên nền `primary-deep`: vòng phải **trắng**.
  await focus_bang_ban_phim("[data-nut-xem-nhu]");
  expect(await mau_vong_focus("[data-nut-xem-nhu]"), "nút trên nền đậm").toBe(TRANG);

  // Hai, mục menu trên nền `surface-card`. Mục mang `tabindex="-1"` và menu
  // dùng roving focus, nên đường thật tới nó là một phím mũi tên - đúng đường
  // ca này đi.
  await page.locator("[data-nut-xem-nhu]").press("Enter");
  await expect(page.locator("[data-menu-vai]")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  const muc = await page.evaluate(
    () => document.activeElement?.getAttribute("data-muc-vai") ?? null,
  );
  expect(muc, "phím mũi tên phải đưa focus vào một mục menu").not.toBeNull();
  expect(await mau_vong_focus(`[data-muc-vai="${muc}"]`), "mục menu trên nền trắng").toBe(
    PRIMARY,
  );
  await page.keyboard.press("Escape");

  // Ba, nút ✕ của chip "Đang xem như" trên nền `level-l1-bg`: vòng trắng ở đó
  // là **1,10:1**, tức lỗ mà chính phép sửa của story này tạo ra.
  await doi_vai(page, VAI_NHIP_2);
  await focus_bang_ban_phim("[data-thoat-nhanh]");
  expect(await mau_vong_focus("[data-thoat-nhanh]"), "✕ trên nền chip hổ phách").toBe(
    PRIMARY,
  );

  await page.screenshot({ path: ANH_MAY_CHIEU, fullPage: false });
});
