import { expect, test, type Page } from "@playwright/test";

import {
  canh_do_thi,
  chan_moi_api,
  co_token,
  duong_anh,
  envelope,
  envelope_do_thi,
  hoi_bang_nut,
  loi_api,
  mock_danh_muc_vai,
  mock_do_thi,
  mock_doi_vai,
  mock_hoi_dap,
  mock_toi,
  mock_toi_dong,
  node_dinh,
  node_vong,
  PHIEN,
  phien_xem_nhu,
  rong_cuon,
  token_trong_kho,
  trich_dan,
  vao_chat,
} from "./ho_tro";

// Drawer đồ thị kiểu paper với hover trích dẫn (story 4.6, FR-19). Mười tám ca
// theo 15 hàng I/O Matrix của spec cộng ba ca canh luật (1280px, tất định, và
// hai lý do trống ra cùng một DOM). Không lượt nào ra máy chủ thật: mọi
// `/api/**` chưa mock bị chặn ở `beforeEach`, và mỗi ca mock đúng tuyến nó cần.

const ANH = duong_anh("do-thi-4-6-1280.png");

/** Hai id hyperedge thật của lượt mẫu. Chúng **không bao giờ** được có mặt
 *  trong DOM: `web/` chỉ hiện `HE-01`, `HE-02`. */
const ID_1 = "he-3f9c1a2b3c4d5e6f70819200";
const ID_2 = "he-aa11bb22cc33dd44ee55ff66";

/** Đồ thị hai vòng chia chung entity `App01` - đúng hình mà mockup vẽ. */
function do_thi_hai_vong() {
  return envelope_do_thi(
    [
      node_vong(ID_1),
      node_vong(ID_2, { label: "chủ thể: App01; nguồn: runbook/app01.md" }),
      node_dinh("ent-app01", "App01"),
      node_dinh("ent-502", "lỗi 502"),
      node_dinh("ent-runbook", "runbook/app01.md"),
    ],
    [
      canh_do_thi(ID_1, "ent-app01", "subject"),
      canh_do_thi(ID_1, "ent-502", "symptom"),
      canh_do_thi(ID_2, "ent-app01", "subject"),
      canh_do_thi(ID_2, "ent-runbook", "source"),
    ],
  );
}

/** Cùng hai vòng nhưng vai `cause` bị che: một node riêng theo cặp (hyperedge,
 *  slot), id `<id_hyperedge>#cause` (ADR-018 quyết định 2). */
function do_thi_co_dinh_che() {
  return envelope_do_thi(
    [
      node_vong(ID_1, { level: "L1", label: "chủ thể: App01; nguyên nhân: [cause:masked]" }),
      node_dinh("ent-app01", "App01"),
      node_dinh(`${ID_1}#cause`, "[cause:masked]", { masked: true }),
    ],
    [
      canh_do_thi(ID_1, "ent-app01", "subject"),
      canh_do_thi(ID_1, `${ID_1}#cause`, "cause"),
    ],
  );
}

function envelope_hai_nguon() {
  return envelope({ citations: [trich_dan(ID_1), trich_dan(ID_2)] });
}

/** Vào chat, hỏi một câu có hai nguồn, rồi mở drawer bằng nút. */
async function mo_drawer(page: Page) {
  await vao_chat(page);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-cite-row]")).toHaveCount(2);
  await page.locator("[data-nut-do-thi]").click();
}

async function cho_ve_xong(page: Page) {
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-da-ve", "1");
}

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
  await co_token(page);
  await mock_toi(page);
});

test("mặc định: drawer đóng, chat chiếm toàn màn, nút Đồ thị không active", async ({
  page,
}) => {
  await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await expect(page.locator("[data-drawer-do-thi]")).toHaveCount(0);
  const nut = page.locator("[data-nut-do-thi]");
  await expect(nut).toHaveText("Đồ thị");
  await expect(nut).toHaveAttribute("aria-pressed", "false");
  await expect(nut).not.toHaveAttribute("data-active", /.*/);
});

test("mở bằng nút: gọi /do-thi đúng một lần với đúng hai id ấy, vẽ hai vòng", async ({
  page,
}) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  const da_gui = await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);

  // Đúng một lượt, đúng danh sách id của lượt ấy, đúng thứ tự citation.
  expect(da_gui()).toEqual([[ID_1, ID_2]]);
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-vong", "2");
  // Legend là chỗ đọc được nội dung vòng: mã hiển thị cộng `label` đầy đủ.
  const legend = page.locator("[data-legend-vong]");
  await expect(legend).toHaveCount(2);
  await expect(legend.nth(0)).toHaveAttribute("data-legend-vong", "HE-01");
  await expect(legend.nth(1)).toHaveAttribute("data-legend-vong", "HE-02");
  await expect(legend.nth(1)).toContainText("runbook/app01.md");
  // Entity dùng chung không bị nhân đôi: `App01` là một node cho cả hai vòng.
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-dinh", "3");
  // Và id hyperedge thật không có một byte nào trong DOM.
  const html = await page.locator("[data-drawer-do-thi]").innerHTML();
  expect(html).not.toContain(ID_1);
  expect(html).not.toContain("he-");
});

test("mở bằng số [n]: drawer mở và vòng HE-02 sáng, giữ sáng sau khi rời chuột", async ({
  page,
}) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await vao_chat(page);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-drawer-do-thi]")).toHaveCount(0);

  await page.locator('[data-cite-so="HE-02"]').click();
  await expect(page.locator("[data-drawer-do-thi]")).toHaveAttribute("data-ma-sang", "HE-02");
  // Rời chuột hẳn khỏi cite-row: mã **đã chọn** giữ sáng, khác hover.
  await page.mouse.move(2, 2);
  await expect(page.locator("[data-drawer-do-thi]")).toHaveAttribute("data-ma-sang", "HE-02");
});

test("hover cite-row: vòng tương ứng sáng và hàng hiện chú thích, rời hover trả về", async ({
  page,
}) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);

  const drawer = page.locator("[data-drawer-do-thi]");
  await expect(drawer).not.toHaveAttribute("data-ma-sang", /.*/);

  await page.locator("[data-cite-row]").nth(0).hover();
  await expect(drawer).toHaveAttribute("data-ma-sang", "HE-01");
  // Tín hiệu **phi màu** đi kèm: một chú thích chữ ngay trên hàng.
  await expect(page.locator('[data-dang-sang="HE-01"]')).toHaveText("→ đang sáng HE-01");

  await page.mouse.move(2, 2);
  await expect(drawer).not.toHaveAttribute("data-ma-sang", /.*/);
  await expect(page.locator("[data-dang-sang]")).toHaveCount(0);
});

test("hover cite-row của lượt cũ: không vòng nào sáng, không chú thích", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);

  // Lượt thứ hai, một nguồn: từ đây lượt một là lượt cũ.
  await mock_hoi_dap(page, envelope({ citations: [trich_dan(ID_2)] }));
  await hoi_bang_nut(page, "Câu thứ hai");
  await expect(page.locator("[data-khoi-nguon]")).toHaveCount(2);

  // Khối nguồn của lượt cũ đã thu gọn, mở lại rồi hover hàng của nó.
  await page.locator("[data-nut-khoi-nguon]").nth(0).click();
  const hang_cu = page.locator("[data-khoi-nguon]").nth(0).locator("[data-cite-row]").nth(0);
  await hang_cu.hover();
  await expect(page.locator("[data-dang-sang]")).toHaveCount(0);
  await expect(page.locator("[data-drawer-do-thi]")).not.toHaveAttribute("data-ma-sang", /.*/);
  // Và ô số của hàng cũ không phải một nút bấm được mà không làm gì.
  await expect(hang_cu.locator("[data-cite-so]")).toHaveCount(0);
});

test("lượt mới: gọi lại /do-thi với id của lượt mới, mọi highlight cũ bỏ", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  const da_gui = await mock_do_thi(page, (lan: number) =>
    lan === 1 ? do_thi_hai_vong() : do_thi_co_dinh_che(),
  );
  await mo_drawer(page);
  await cho_ve_xong(page);
  await page.locator('[data-cite-so="HE-01"]').click();
  await expect(page.locator("[data-drawer-do-thi]")).toHaveAttribute("data-ma-sang", "HE-01");

  await mock_hoi_dap(page, envelope({ citations: [trich_dan(ID_1)] }));
  await hoi_bang_nut(page, "Câu thứ hai");
  await expect.poll(() => da_gui().length).toBe(2);
  expect(da_gui()[1]).toEqual([ID_1]);
  await expect(page.locator("[data-drawer-do-thi]")).not.toHaveAttribute("data-ma-sang", /.*/);
  await cho_ve_xong(page);
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-vong", "1");
});

test("đổi vai: gọi lại /do-thi cùng danh sách id, đồ thị vẽ lại theo vai mới", async ({
  page,
}) => {
  let phien: unknown = PHIEN;
  await mock_toi_dong(page, () => phien);
  await mock_danh_muc_vai(page);
  await mock_doi_vai(page, (vai) => {
    phien = vai === null ? PHIEN : phien_xem_nhu(vai);
  });
  await mock_hoi_dap(page, envelope_hai_nguon());
  const da_gui = await mock_do_thi(page, (lan: number) =>
    lan === 1 ? do_thi_hai_vong() : do_thi_co_dinh_che(),
  );
  await mo_drawer(page);
  await cho_ve_xong(page);
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-dinh-che", "0");

  await page.locator("[data-nut-xem-nhu]").click();
  await page.locator('[data-muc-vai="tech_support"]').click();
  await expect(page.locator("[data-chip-xem-nhu]")).toContainText("Tech Support");

  // Cùng danh sách id, gửi lại để **server** lọc lại - không lọc phía client.
  await expect.poll(() => da_gui().length).toBe(2);
  expect(da_gui()[1]).toEqual([ID_1, ID_2]);
  await cho_ve_xong(page);
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-vong", "1");
  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-dinh-che", "1");
  await expect(page.locator("[data-chip-vai-do-thi]")).toHaveText("vai đang xem · Tech Support");
});

test("lượt từ chối: không gọi /do-thi, drawer hiện empty-state", async ({ page }) => {
  await mock_hoi_dap(page, envelope({ answer: null, refused: true, citations: [] }));
  const da_gui = await mock_do_thi(page, do_thi_hai_vong());
  await vao_chat(page);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-tu-choi]")).toHaveCount(1);
  await page.locator("[data-nut-do-thi]").click();

  await expect(page.locator("[data-do-thi-trong]")).toHaveText(
    "Chưa có dữ liệu đồ thị cho lượt trả lời này",
  );
  expect(da_gui()).toEqual([]);
});

test("toàn bộ ngoài quyền: thân trả nodes rỗng ra đúng empty-state ấy", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  const da_gui = await mock_do_thi(page, envelope_do_thi([], []));
  await mo_drawer(page);

  await expect(page.locator("[data-do-thi-trong]")).toHaveText(
    "Chưa có dữ liệu đồ thị cho lượt trả lời này",
  );
  // Có gửi id đi (server là nơi lọc), nhưng màn hình **không** nói ra điều đó.
  expect(da_gui()).toEqual([[ID_1, ID_2]]);
  await expect(page.locator("[data-vung-do-thi]")).toHaveCount(0);
  await expect(page.locator("[data-legend-do-thi]")).toHaveCount(0);
});

test("chưa có lượt nào: empty-state, không request nào bay đi", async ({ page }) => {
  const da_gui = await mock_do_thi(page, do_thi_hai_vong());
  await vao_chat(page);
  await page.locator("[data-nut-do-thi]").click();
  await expect(page.locator("[data-do-thi-trong]")).toHaveText(
    "Chưa có dữ liệu đồ thị cho lượt trả lời này",
  );
  expect(da_gui()).toEqual([]);
});

test("hai lý do trống ra DOM giống hệt nhau", async ({ page }) => {
  // Lý do một: lượt từ chối (không citation nào).
  await mock_hoi_dap(page, envelope({ answer: null, refused: true, citations: [] }));
  await mock_do_thi(page, envelope_do_thi([], []));
  await vao_chat(page);
  await hoi_bang_nut(page);
  await page.locator("[data-nut-do-thi]").click();
  await expect(page.locator("[data-do-thi-trong]")).toHaveCount(1);
  const tu_choi = await page.locator(".drawer_do_thi__than").innerHTML();

  // Lý do hai: có citation, nhưng mọi hyperedge ngoài quyền.
  await mock_hoi_dap(page, envelope_hai_nguon());
  await hoi_bang_nut(page, "Câu thứ hai");
  await expect(page.locator("[data-cite-row]")).toHaveCount(2);
  await expect(page.locator("[data-do-thi-trong]")).toHaveCount(1);
  const ngoai_quyen = await page.locator(".drawer_do_thi__than").innerHTML();

  expect(ngoai_quyen).toBe(tu_choi);
});

test("node che: một đỉnh mờ nhãn ••• kèm tooltip Cần quyền L2", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({
      citations: [
        trich_dan(ID_1, {
          level: "L1",
          masked_slots: ["cause", "owner"],
          owner_group: "DevOps",
        }),
      ],
    }),
  );
  await mock_do_thi(page, do_thi_co_dinh_che());
  await vao_chat(page);
  await hoi_bang_nut(page);
  await page.locator("[data-nut-do-thi]").click();
  await cho_ve_xong(page);

  await expect(page.locator("[data-vung-do-thi]")).toHaveAttribute("data-so-dinh-che", "1");
  const che = page.locator('[data-guong-dinh][data-che="1"]');
  await expect(che).toHaveCount(1);
  // Nhãn là "•••", **không** phải dấu che của server: `[cause:masked]` là chữ
  // của ngữ cảnh LLM và nó không được vào màn.
  await expect(che).toHaveText("•••");
  await expect(che).toHaveAttribute("title", "Cần quyền L2");
  const html = await page.locator("[data-drawer-do-thi]").innerHTML();
  expect(html).not.toContain("[cause:masked]");
  // Node che mang mã theo cặp (hyperedge, slot), không gộp giữa hai vòng.
  await expect(che).toHaveAttribute("data-guong-dinh", "HE-01#cause");
});

test("thân sai hình: hộp đỏ DO_THI_LA, không vẽ đồ thị nửa vời", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  // Node hyperedge thiếu khóa `label` (tập khóa đóng của AD-8).
  await mock_do_thi(
    page,
    envelope_do_thi(
      [{ id: ID_1, kind: "hyperedge", level: "L2", scope: "noi_bo", content_type: "runbook" }],
      [],
    ),
  );
  await mo_drawer(page);

  await expect(page.locator("[data-drawer-do-thi] [data-ma-loi]")).toHaveAttribute(
    "data-ma-loi",
    "DO_THI_LA",
  );
  await expect(page.locator("[data-vung-do-thi]")).toHaveCount(0);
  await expect(page.locator("[data-do-thi-trong]")).toHaveCount(0);
});

test("kho hỏng: hộp đỏ KHO_KHONG_SAN_SANG, URL giữ nguyên, chat không đổi", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, loi_api("KHO_KHONG_SAN_SANG"), 503);
  await mo_drawer(page);

  await expect(page.locator("[data-drawer-do-thi] [data-ma-loi]")).toHaveAttribute(
    "data-ma-loi",
    "KHO_KHONG_SAN_SANG",
  );
  expect(new URL(page.url()).pathname).toBe("/");
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-cite-row]")).toHaveCount(2);
});

test("hết phiên: 401 giữa một lần mở drawer xóa token và về màn đăng nhập", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, loi_api("TOKEN_KHONG_HOP_LE"), 401);
  await mo_drawer(page);

  await page.waitForURL(/\/dang-nhap\?ly_do=het_han/);
  expect(await token_trong_kho(page)).toBeNull();
});

test("kéo grip: độ rộng đổi trong khoảng cho phép, thả ra giữ nguyên; ✕ đóng", async ({
  page,
}) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);

  const drawer = page.locator("[data-drawer-do-thi]");
  const vung = page.locator(".man_chat__vung");
  const rong_vung = (await vung.boundingBox())!.width;
  const truoc = (await drawer.boundingBox())!.width;
  expect(truoc / rong_vung).toBeGreaterThan(0.3);

  const grip = (await page.locator("[data-grip-drawer]").boundingBox())!;
  await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
  await page.mouse.down();
  // Kéo hẳn sang trái quá biên: độ rộng phải dừng ở trần 72%, không vượt.
  await page.mouse.move(grip.x - 900, grip.y + grip.height / 2, { steps: 8 });
  await page.mouse.up();

  const sau = (await drawer.boundingBox())!.width;
  expect(sau).toBeGreaterThan(truoc);
  expect(sau / rong_vung).toBeLessThanOrEqual(0.721);
  expect(sau / rong_vung).toBeGreaterThanOrEqual(0.28);

  // Thả ra thì giữ nguyên (một lần di chuột nữa không kéo tiếp).
  await page.mouse.move(grip.x + 400, grip.y);
  expect((await drawer.boundingBox())!.width).toBeCloseTo(sau, 0);

  await page.locator("[data-dong-drawer]").click();
  await expect(drawer).toHaveCount(0);
});

test("kéo grip sang phải không hẹp hơn 28%", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);

  const drawer = page.locator("[data-drawer-do-thi]");
  const rong_vung = (await page.locator(".man_chat__vung").boundingBox())!.width;
  const grip = (await page.locator("[data-grip-drawer]").boundingBox())!;
  await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
  await page.mouse.down();
  await page.mouse.move(grip.x + 900, grip.y + grip.height / 2, { steps: 8 });
  await page.mouse.up();

  expect((await drawer.boundingBox())!.width / rong_vung).toBeGreaterThanOrEqual(0.279);
});

test("tất định: đóng rồi mở lại cho đúng một hình", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);
  const lan_1 = await page.locator("[data-vung-do-thi]").screenshot();

  await page.locator("[data-dong-drawer]").click();
  await expect(page.locator("[data-drawer-do-thi]")).toHaveCount(0);
  await page.locator("[data-nut-do-thi]").click();
  await cho_ve_xong(page);
  const lan_2 = await page.locator("[data-vung-do-thi]").screenshot();

  // Cùng một lượt vẽ hai lần cho **cùng một hình**: đó là thứ để buổi diễn tập
  // có nghĩa. Bố cục là hàm thuần cộng `layout: {name: "preset"}`, không một
  // nguồn ngẫu nhiên nào (phép quét nguồn ở `tests/test_web_khung.py`).
  expect(Buffer.compare(lan_1, lan_2)).toBe(0);
});

test("1280px: drawer, cite-row và legend không cuộn ngang", async ({ page }) => {
  await mock_hoi_dap(page, envelope_hai_nguon());
  await mock_do_thi(page, do_thi_hai_vong());
  await mo_drawer(page);
  await cho_ve_xong(page);
  await page.locator("[data-cite-row]").nth(0).hover();
  await expect(page.locator('[data-dang-sang="HE-01"]')).toBeVisible();

  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await expect(page.locator("[data-o-hoi]")).toBeInViewport();
  await expect(page.locator("[data-nut-do-thi]")).toBeInViewport();
  await page.screenshot({ path: ANH, fullPage: false });
});
