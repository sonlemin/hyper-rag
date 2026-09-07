import { expect, test } from "@playwright/test";

import {
  chan_moi_api,
  co_token,
  duong_anh,
  envelope,
  hoi_bang_nut,
  mock_hoi_dap,
  mock_toi,
  rong_cuon,
  trich_dan,
  vao_chat,
} from "./ho_tro";

// Cite-row, slab bôi đen và dòng hạn chế L1 (story 4.4). Mười bốn ca theo đúng
// 14 hàng I/O Matrix của spec. Không lượt nào ra máy chủ thật: mọi `/api/**`
// chưa mock bị chặn ở `beforeEach`, và mỗi ca mock đúng tuyến nó cần.

const ANH = duong_anh("cite-row-4-4-1280.png");

/** Một citation L1 của nhóm DevOps che `cause` + `remediation` + `owner`. */
function l1_devops(id: string) {
  return trich_dan(id, {
    level: "L1",
    scope: "khach_hang_a",
    content_type: "bao_cao_su_co",
    masked_slots: ["cause", "remediation", "owner"],
    owner_group: "DevOps",
  });
}

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
  await co_token(page);
  await mock_toi(page);
});

test("lượt L2 thuần: khối nguồn mở, hai cite-row badge L2, không slab, không dòng hạn chế", async ({
  page,
}) => {
  await mock_hoi_dap(
    page,
    envelope({ citations: [trich_dan("he-01"), trich_dan("he-02")] }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  const khoi = page.locator("[data-khoi-nguon]");
  await expect(khoi).toHaveCount(1);
  await expect(khoi).toHaveAttribute("data-mo", "1");
  await expect(khoi.locator("[data-nut-khoi-nguon]")).toContainText("Nguồn (2)");

  const hang = page.locator("[data-cite-row]");
  await expect(hang).toHaveCount(2);
  await expect(hang.nth(0)).toHaveAttribute("data-muc", "L2");
  await expect(hang.nth(1)).toHaveAttribute("data-muc", "L2");
  await expect(hang.nth(0)).toContainText("HE-01");
  await expect(hang.nth(1)).toContainText("HE-02");
  await expect(hang.nth(0).locator("[data-badge-muc]")).toHaveText("L2");
  // Nhãn loại và nhãn scope là chữ tiếng Việt, không khóa snake_case.
  await expect(hang.nth(0)).toContainText("Quy trình vận hành");
  await expect(hang.nth(0)).not.toContainText("runbook");
  await expect(hang.nth(0)).toContainText("nội bộ");
  await expect(hang.nth(0)).not.toContainText("noi_bo");

  await expect(page.locator("[data-slab]")).toHaveCount(0);
  await expect(page.locator("[data-han-che]")).toHaveCount(0);
  // Id hyperedge thật không bao giờ vào DOM.
  await expect(page.locator("[data-tra-loi]")).not.toContainText("he-01");
});

test("lượt có L1: slab đen inline, cite-row L1 nghiêng hổ phách, dòng hạn chế đúng chữ", async ({
  page,
}) => {
  await mock_hoi_dap(
    page,
    envelope({
      answer: "App01 gặp sự cố ngày 12/08. [cause:masked] [remediation:masked]",
      citations: [l1_devops("he-09")],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  // Slab đúng vị trí, đúng nhãn tiếng Việt của EXPERIENCE.md.
  const slab = page.locator("[data-slab]");
  await expect(slab).toHaveCount(2);
  await expect(slab.nth(0)).toHaveText("[nguyên nhân: che]");
  await expect(slab.nth(1)).toHaveText("[hành động khắc phục: che]");
  await expect(slab.nth(0)).toHaveAttribute("data-slab", "cause");
  // Chữ quanh slab giữ nguyên văn.
  await expect(page.locator("[data-tra-loi] .luot__than")).toContainText(
    "App01 gặp sự cố ngày 12/08.",
  );
  await expect(page.locator("[data-tra-loi] .luot__than")).not.toContainText("[cause:masked]");

  // Cite-row L1: nghiêng, badge L1, và có **chữ** bên cạnh badge (sàn
  // accessibility: trạng thái che không dựa vào màu đơn lẻ).
  const hang = page.locator("[data-cite-row]");
  await expect(hang).toHaveAttribute("data-muc", "L1");
  await expect(hang.locator("[data-badge-muc]")).toHaveText("L1");
  await expect(hang).toContainText("còn một phần bị hạn chế, liên hệ DevOps");
  await expect(hang).toHaveCSS("font-style", "italic");

  // Dòng hạn chế: đếm hai vai (bỏ `owner`), liệt kê đúng nhóm.
  const note = page.locator("[data-han-che]");
  await expect(note).toHaveCount(1);
  await expect(note).toContainText(
    "Còn 2 phần bị hạn chế (nguyên nhân, hành động khắc phục) - liên hệ nhóm DevOps",
  );
});

test("dấu owner có nhóm: slab giữ nguyên tên nhóm", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({
      answer: "Nhóm phụ trách là [owner:DevOps].",
      citations: [trich_dan("he-01", { masked_slots: ["owner"], owner_group: "DevOps" })],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-slab]")).toHaveText("[người phụ trách: DevOps]");
  // Citation L2 nên không có dòng hạn chế nào, dù `masked_slots` mang `owner`.
  await expect(page.locator("[data-han-che]")).toHaveCount(0);
});

test("dấu owner không nhóm: slab '[người phụ trách: che]'", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({
      answer: "Nhóm phụ trách là [owner:group].",
      citations: [trich_dan("he-01")],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-slab]")).toHaveText("[người phụ trách: che]");
});

test("chuỗi ngoặc không phải dấu che: giữ nguyên văn, không slab nào", async ({ page }) => {
  // Ba cách một chuỗi ngoặc vuông đi lọt nếu nhận diện bằng một regex tự do:
  // một ghi chú thường, một lý do không phải lý do của tầng che, và một tên
  // nhóm **không có** trong `citations` của chính lượt này.
  await mock_hoi_dap(
    page,
    envelope({
      answer: "Xem [ghi chú] rồi [cause:che] và [owner:NhómLạ] là chữ thường.",
      citations: [trich_dan("he-01", { owner_group: "DevOps" })],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-slab]")).toHaveCount(0);
  await expect(page.locator("[data-tra-loi] .luot__than")).toHaveText(
    "Xem [ghi chú] rồi [cause:che] và [owner:NhómLạ] là chữ thường.",
  );
});

test("nhiều nhóm L1: liệt kê nhóm duy nhất theo thứ tự xuất hiện, không lặp", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({
      answer: "Sự cố App01. [cause:masked]",
      citations: [
        l1_devops("he-09"),
        trich_dan("he-10", {
          level: "L1",
          content_type: "vong_doi_ticket",
          masked_slots: ["symptom", "owner"],
          owner_group: "Tech Support",
        }),
        l1_devops("he-11"),
      ],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  const note = page.locator("[data-han-che]");
  // Ba vai bị che sau khi bỏ `owner`, theo thứ tự danh mục 8 vai
  // (`symptom` trước `cause` trước `remediation`), và hai nhóm không lặp.
  await expect(note).toContainText(
    "Còn 3 phần bị hạn chế (triệu chứng, nguyên nhân, hành động khắc phục) - liên hệ nhóm DevOps, Tech Support",
  );
  await expect(page.locator("[data-cite-row]")).toHaveCount(3);
});

test("L1 chỉ che owner: cite-row L1 vẫn có, không dòng hạn chế nào", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({
      citations: [
        trich_dan("he-09", {
          level: "L1",
          content_type: "bao_cao_su_co",
          masked_slots: ["owner"],
          owner_group: "Tech Support",
        }),
      ],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-cite-row]")).toHaveAttribute("data-muc", "L1");
  await expect(page.locator("[data-han-che]")).toHaveCount(0);
});

test("L1 che một vai nhưng không có nhóm: không dòng hạn chế, hàng không nói 'liên hệ'", async ({
  page,
}) => {
  // Ca này chấm nhánh **nhóm** của luật, nhánh mà mọi ca L1 khác của file này
  // đi vòng qua: chúng đều mang `owner_group`, còn ca "L1 chỉ che owner" thoát
  // ở nhánh `cac_vai.length === 0` chứ không ở nhánh nhóm. Câu chữ của dòng
  // hạn chế kết bằng "liên hệ nhóm X"; không có X thì không có dòng.
  await mock_hoi_dap(
    page,
    envelope({
      answer: "Sự cố App01. [cause:masked]",
      citations: [
        trich_dan("he-09", {
          level: "L1",
          content_type: "bao_cao_su_co",
          masked_slots: ["cause"],
          owner_group: null,
        }),
      ],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  // Hàng vẫn có, vẫn L1, vẫn badge L1 - chỉ vế "liên hệ" là vắng.
  const hang = page.locator("[data-cite-row]");
  await expect(hang).toHaveAttribute("data-muc", "L1");
  await expect(hang.locator("[data-badge-muc]")).toHaveText("L1");
  await expect(hang).not.toContainText("liên hệ");
  await expect(page.locator("[data-han-che]")).toHaveCount(0);
  // Slab trong câu vẫn nói "cái gì bị che" - phần ấy không phụ thuộc nhóm.
  await expect(page.locator("[data-slab]")).toHaveText("[nguyên nhân: che]");
});

test("L1 có vai bị che không nhóm, cạnh L1 chỉ che owner có nhóm: không dòng hạn chế", async ({
  page,
}) => {
  // Phép ghép sai mà vòng review bắt được: gom `cac_vai` và `cac_nhom` bằng hai
  // lượt độc lập cho ra "Còn 1 phần bị hạn chế (nguyên nhân) - liên hệ nhóm
  // DevOps", tức bảo người dùng đi hỏi một nhóm không giữ vai bị che đó. Ở một
  // sản phẩm break-glass thì đó là gửi yêu cầu tới sai người.
  await mock_hoi_dap(
    page,
    envelope({
      answer: "Sự cố App01. [cause:masked]",
      citations: [
        trich_dan("he-09", {
          level: "L1",
          content_type: "bao_cao_su_co",
          masked_slots: ["cause"],
          owner_group: null,
        }),
        trich_dan("he-10", {
          level: "L1",
          content_type: "runbook",
          masked_slots: ["owner"],
          owner_group: "DevOps",
        }),
      ],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-cite-row]")).toHaveCount(2);
  await expect(page.locator("[data-han-che]")).toHaveCount(0);
});

test("không citation nào mà câu có [owner:DevOps]: không slab nào", async ({ page }) => {
  // Câu mà Design Notes khẳng định: tập nhóm để nhận diện `[owner:<nhóm>]` lấy
  // từ `owner_group` của **chính lượt đó**, nên một lượt không citation nào thì
  // không dấu owner mang tên nhóm nào thành slab. Đây là hệ quả cố ý của phép
  // nhận diện bằng dựng lại, và không có ca này thì nó chỉ là một câu văn.
  await mock_hoi_dap(
    page,
    envelope({ answer: "Nhóm phụ trách là [owner:DevOps].", citations: [] }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-slab]")).toHaveCount(0);
  await expect(page.locator("[data-tra-loi] .luot__than")).toHaveText(
    "Nhóm phụ trách là [owner:DevOps].",
  );
  // Nhưng `[owner:group]` thì vẫn thành slab: nó không cần nhóm nào của lượt.
  await mock_hoi_dap(
    page,
    envelope({ answer: "Nhóm phụ trách là [owner:group].", citations: [] }),
  );
  await hoi_bang_nut(page, "câu hai");
  await expect(page.locator("[data-slab]")).toHaveText("[người phụ trách: che]");
});

test("lượt cũ thu gọn: bấm mở lại và giữ mở qua lượt sau", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({ citations: [trich_dan("he-01"), trich_dan("he-02")] }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page, "câu một");
  await expect(page.locator("[data-khoi-nguon]")).toHaveAttribute("data-mo", "1");

  await hoi_bang_nut(page, "câu hai");
  const khoi = page.locator("[data-khoi-nguon]");
  await expect(khoi).toHaveCount(2);
  await expect(khoi.nth(0)).toHaveAttribute("data-mo", "0");
  await expect(khoi.nth(1)).toHaveAttribute("data-mo", "1");
  await expect(khoi.nth(0).locator("[data-nut-khoi-nguon]")).toContainText("Nguồn (2)");
  // Thu gọn thì không hàng nào trong DOM, chỉ còn nhãn.
  await expect(khoi.nth(0).locator("[data-cite-row]")).toHaveCount(0);

  // Bấm mở lại lượt cũ.
  await khoi.nth(0).locator("[data-nut-khoi-nguon]").click();
  await expect(khoi.nth(0)).toHaveAttribute("data-mo", "1");
  await expect(khoi.nth(0).locator("[data-cite-row]")).toHaveCount(2);

  // Và lựa chọn ấy giữ nguyên qua lượt sau: một khối tự đóng lại dưới tay người
  // đang đọc là mất chỗ họ vừa mở.
  await hoi_bang_nut(page, "câu ba");
  await expect(page.locator("[data-khoi-nguon]")).toHaveCount(3);
  await expect(page.locator("[data-khoi-nguon]").nth(0)).toHaveAttribute("data-mo", "1");
});

test("lượt từ chối xen giữa không thu gọn lượt trả lời trước", async ({ page }) => {
  // Luật của EXPERIENCE.md là "lượt **trả lời** mới nhất luôn mở", nên một lượt
  // từ chối - vốn không có khối nguồn nào - không được cướp vai trò ấy. Nếu nó
  // cướp thì màn hình còn đúng không nguồn nào mở, ngay sau một câu vừa trả lời
  // có nguồn. Đo được trên máy chủ thật với `ts01` ngày 07/09/2026: câu thứ hai
  // rơi vào `refused` và khối nguồn của câu thứ nhất vẫn mở.
  const luot = [
    envelope({ citations: [trich_dan("he-01"), trich_dan("he-02")] }),
    envelope({ answer: null, refused: true, citations: [] }),
  ];
  let i = 0;
  await page.route("**/api/hoi-dap", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(luot[Math.min(i++, luot.length - 1)]),
    });
  });
  await vao_chat(page);
  await hoi_bang_nut(page, "câu có nguồn");
  await expect(page.locator("[data-khoi-nguon]")).toHaveAttribute("data-mo", "1");

  await hoi_bang_nut(page, "câu bị từ chối");
  await expect(page.locator("[data-tu-choi]")).toHaveCount(1);
  // Lượt từ chối không sinh khối nguồn nào, và lượt trả lời trước vẫn mở.
  await expect(page.locator("[data-khoi-nguon]")).toHaveCount(1);
  await expect(page.locator("[data-khoi-nguon]")).toHaveAttribute("data-mo", "1");
  await expect(page.locator("[data-khoi-nguon] [data-cite-row]")).toHaveCount(2);
});

test("lượt từ chối: không khối nguồn, không dòng hạn chế, DOM như 4.3", async ({ page }) => {
  await mock_hoi_dap(page, envelope({ answer: null, refused: true, citations: [] }));
  await vao_chat(page);
  await hoi_bang_nut(page);

  const tu_choi = page.locator("[data-tu-choi]");
  await expect(tu_choi).toHaveCount(1);
  await expect(tu_choi.locator("[data-khoi-nguon]")).toHaveCount(0);
  await expect(tu_choi.locator("[data-han-che]")).toHaveCount(0);
  await expect(tu_choi.locator("[data-slab]")).toHaveCount(0);
  await expect(tu_choi.locator("[data-luot-meta]")).toHaveText(
    "Copilot · trả lời theo quyền DevOps",
  );
  await expect(tu_choi).not.toContainText("Nguồn");
});

test("không citation nào: không khối nguồn, vẫn có bong bóng trả lời", async ({ page }) => {
  await mock_hoi_dap(page, envelope({ citations: [] }));
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-khoi-nguon]")).toHaveCount(0);
  await expect(page.locator("[data-tra-loi]")).not.toContainText("Nguồn (0)");
  await expect(page.locator("[data-tra-loi]")).toContainText("App01 lỗi 502");
});

test("nút xin truy cập: disabled, có tooltip, không request nào", async ({ page }) => {
  const dem = await mock_hoi_dap(
    page,
    envelope({ answer: "[cause:masked]", citations: [l1_devops("he-09")] }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  const nut = page.locator("[data-nut-xin-truy-cap]");
  await expect(nut).toHaveText("Xin truy cập khẩn cấp");
  await expect(nut).toBeDisabled();
  await expect(nut).toHaveAttribute("title", "Chưa khả dụng");
  // Bấm một nút `disabled` không sinh sự kiện; đếm request để chắc chắn.
  await nut.click({ force: true }).catch(() => {});
  expect(dem()).toBe(1);
});

test("tooltip badge mức: title đúng chuỗi bảng Voice and Tone", async ({ page }) => {
  await mock_hoi_dap(page, envelope({ citations: [trich_dan("he-01")] }));
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-badge-muc]")).toHaveAttribute(
    "title",
    "Mức truy cập của vai hiện tại với nguồn này",
  );
});

test("citation sai hình: hộp đỏ ENVELOPE_LA, không lượt trả lời", async ({ page }) => {
  // Bốn cách một citation nói sai về quyền. `level: "L3"` là ca nặng nhất: nó vẽ
  // ra một badge mà không tầng nào của hệ định nghĩa.
  const bien_the: Array<[string, unknown]> = [
    ["level lạ", envelope({ citations: [trich_dan("he-01", { level: "L3" })] })],
    ["level L0", envelope({ citations: [trich_dan("he-01", { level: "L0" })] })],
    [
      "vai ngoài danh mục",
      envelope({ citations: [trich_dan("he-01", { masked_slots: ["nguyen_nhan"] })] }),
    ],
    ["thiếu khóa", envelope({ citations: [{ id: "he-01", level: "L2" }] })],
  ];

  await vao_chat(page);
  for (let i = 0; i < bien_the.length; i += 1) {
    const [ten, than] = bien_the[i];
    await mock_hoi_dap(page, than);
    await hoi_bang_nut(page, `câu số ${i + 1}`);
    await expect(page.locator("[data-ma-loi='ENVELOPE_LA']"), ten).toHaveCount(i + 1);
  }
  await expect(page.locator("[data-tra-loi]")).toHaveCount(0);
  await expect(page.locator("[data-cite-row]")).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe("/");
});

test("khối lượng thật: 100 citation, không cuộn ngang, HE-100 hiện đủ", async ({ page }) => {
  // Số thật, không phải một số tròn cho vui: story 3.4 đo một lượt `dev01` trên
  // `synth` ra 97 citation và 3.7 ra 96, và spec 4.4 **cố ý không đặt trần** cho
  // số cite-row (một trần phía `web/` là một phép lọc thứ hai đứng ngoài cửa
  // quyền, và nó giấu đúng lúc server đang báo động). Nên ba chữ số là ca vận
  // hành chứ không phải ca biên: ô số 20px cố định cắt mất một chữ số, và một
  // hàng flex không wrap đẩy badge mức ra khỏi tầm nhìn.
  const nhieu = Array.from({ length: 100 }, (_, i) =>
    i % 7 === 0
      ? trich_dan(`he-${i}`, {
          level: "L1",
          scope: "khach_hang_b",
          content_type: "bi_mat_ha_tang",
          masked_slots: ["cause", "owner"],
          owner_group: "DevOps",
        })
      : trich_dan(`he-${i}`, { scope: "khach_hang_a", content_type: "vong_doi_ticket" }),
  );
  await mock_hoi_dap(page, envelope({ citations: nhieu }));
  await vao_chat(page);
  await hoi_bang_nut(page);

  const hang = page.locator("[data-cite-row]");
  await expect(hang).toHaveCount(100);
  await expect(page.locator("[data-nut-khoi-nguon]")).toContainText("Nguồn (100)");
  // Mã ba chữ số hiện **đủ**, không bị ô số cắt.
  await expect(hang.nth(99)).toContainText("HE-100");
  await expect(hang.nth(0)).toContainText("HE-01");

  // Badge mức của hàng cuối vẫn nằm trong hàng, không bị đẩy ra ngoài.
  const badge = hang.nth(99).locator("[data-badge-muc]");
  await expect(badge).toBeVisible();
  const hop_hang = await hang.nth(99).boundingBox();
  const hop_badge = await badge.boundingBox();
  expect(hop_badge!.x + hop_badge!.width).toBeLessThanOrEqual(hop_hang!.x + hop_hang!.width + 1);

  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await expect(page.locator("[data-o-hoi]")).toBeInViewport();
});

test("1280px: slab, ba cite-row và dòng hạn chế không cuộn ngang", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({
      answer:
        "App01 gặp sự cố ngày 12/08, gián đoạn 40 phút. [cause:masked] [remediation:masked] Sự cố đã được [owner:DevOps] xử lý xong.",
      citations: [
        trich_dan("he-01"),
        l1_devops("he-09"),
        trich_dan("he-02", { scope: "khach_hang_a", content_type: "canh_bao" }),
      ],
    }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  await expect(page.locator("[data-cite-row]")).toHaveCount(3);
  await expect(page.locator("[data-slab]")).toHaveCount(3);
  await expect(page.locator("[data-han-che]")).toHaveCount(1);
  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await expect(page.locator("[data-o-hoi]")).toBeInViewport();
  await expect(page.locator("[data-nut-gui]")).toBeInViewport();
  await page.screenshot({ path: ANH, fullPage: false });
});
