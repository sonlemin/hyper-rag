// Kiểm tay console web bằng chromium thật trên máy chủ, tự động ba phép kiểm mà
// checklist bắt làm bằng DevTools (story 4.4).
//
// Không phải một ca Playwright: nó gọi máy chủ thật và **tốn tiền LLM thật** (2
// lời gọi mỗi lượt), nên nó không được nằm trong `npm run test:e2e` và không
// chạy ở hook CI. Chạy khi cần một phép kiểm tay có bằng chứng máy đọc được.
//
// Ba phép kiểm, đúng ba thứ mà một người phải mở DevTools ra làm:
//   1. Envelope khớp màn: số hàng bằng `citations.length`, nhãn khối và dòng
//      meta cùng một số ấy, ngoặc của dòng hạn chế bằng hợp `masked_slots` của
//      citation L1 **có nhóm** trừ `owner`, nhóm bằng tập nhóm duy nhất, badge
//      bằng `level`, scope và loại hiện nhãn tiếng Việt chứ không phải khóa
//      snake_case, và không id hyperedge thật nào trong DOM.
//   2. Không cuộn ngang ở 1280.
//   3. Khối nguồn nằm ngoài vùng `aria-live` của câu trả lời.
//
// Bảng nhãn đọc **từ chính `web/src/nhan.ts`** chứ không chép lại: một bản chép
// thứ hai ở đây sẽ báo xanh cho đúng cái nó chép sai.
//
// Chạy:
//   node web/e2e/kiem-tay.mjs --tai-khoan ts01 [--goc http://...] --cau "..." [--cau "..."]
// Ở trong `web/e2e/` vì nó cần `@playwright/test` của `web/`, và vì thư mục đó
// đã bị `.dockerignore` loại nên nó không vào image; đuôi `.mjs` nên `testMatch`
// của Playwright không nhặt nó vào `npm run test:e2e`.
// Mật khẩu lấy từ `.env` gốc repo theo tên `DEMO_MAT_KHAU_<TÊN>`.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const GOC_REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RONG = 1280;

// --- Đọc cấu hình của chính sản phẩm, không chép lại -------------------------

/** Khóa của một bảng `export const <ten>: Record<string,string> = {...}`. */
function bang_nhan(tho, ten) {
  const m = tho.match(new RegExp(`export const ${ten}(?::[^=]*)? = \\{(.*?)\\n\\};`, "s"));
  if (!m) throw new Error(`nhan.ts không có bảng ${ten}`);
  return Object.fromEntries(
    [...m[1].matchAll(/^\s*([a-z_][a-z0-9_]*):\s*"([^"]*)"/gm)].map((x) => [x[1], x[2]]),
  );
}

const NHAN_TS = readFileSync(resolve(GOC_REPO, "web/src/nhan.ts"), "utf-8");
const NHAN_SLOT = bang_nhan(NHAN_TS, "NHAN_SLOT");
const NHAN_LOAI = bang_nhan(NHAN_TS, "NHAN_LOAI");
const NHAN_SCOPE = bang_nhan(NHAN_TS, "NHAN_SCOPE");
const VAI_SLOT = Object.keys(NHAN_SLOT);
const VAI_OWNER = "owner";

function mat_khau(tai_khoan) {
  const env = readFileSync(resolve(GOC_REPO, ".env"), "utf-8");
  const m = env.match(new RegExp(`^DEMO_MAT_KHAU_${tai_khoan.toUpperCase()}=(.*)$`, "m"));
  if (!m) throw new Error(`.env không có DEMO_MAT_KHAU_${tai_khoan.toUpperCase()}`);
  return m[1].trim();
}

// --- Tham số dòng lệnh -------------------------------------------------------

function doc_tham_so(argv) {
  const ra = { tai_khoan: null, goc: "http://103.69.194.185:3000", cau: [] };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--tai-khoan") ra.tai_khoan = argv[++i];
    else if (argv[i] === "--goc") ra.goc = argv[++i];
    else if (argv[i] === "--cau") ra.cau.push(argv[++i]);
  }
  if (!ra.tai_khoan) throw new Error("thiếu --tai-khoan");
  if (ra.cau.length === 0) throw new Error("thiếu --cau (lặp được)");
  return ra;
}

// --- Ba phép kiểm ------------------------------------------------------------

/** Dòng hạn chế mà envelope này **phải** sinh ra, tính lại từ `citations`.
 *
 *  Cùng luật với `web/src/app/DongHanChe.tsx::tom_tat_han_che` nhưng viết độc
 *  lập: nếu hai bên ra khác nhau thì một trong hai sai, và đó đúng là thứ phép
 *  kiểm này đi tìm. `owner` ngoài phép đếm, và hai điều kiện L1 với có nhóm
 *  phải đúng trên **cùng một** citation. */
function han_che_ky_vong(citations) {
  const vai = new Set();
  const nhom = [];
  for (const c of citations) {
    if (c.level !== "L1" || c.owner_group === null) continue;
    for (const v of c.masked_slots) if (v !== VAI_OWNER) vai.add(v);
    if (!nhom.includes(c.owner_group)) nhom.push(c.owner_group);
  }
  const cac_vai = VAI_SLOT.filter((v) => vai.has(v));
  if (cac_vai.length === 0 || nhom.length === 0) return null;
  return `Còn ${cac_vai.length} phần bị hạn chế (${cac_vai.map((v) => NHAN_SLOT[v] ?? v).join(", ")}) - liên hệ nhóm ${nhom.join(", ")}`;
}

function kiem_envelope_khop_man(env, dom, ghi) {
  const n = env.citations.length;
  ghi("số hàng cite bằng citations.length", dom.so_hang === n, `${dom.so_hang} vs ${n}`);
  if (n > 0) {
    ghi("nhãn khối nguồn mang đúng n", dom.nhan_khoi.includes(`Nguồn (${n})`), dom.nhan_khoi);
  } else {
    ghi("không citation nào thì không khối nguồn", dom.nhan_khoi === null, dom.nhan_khoi);
  }
  if (!env.refused && n > 0) {
    ghi("dòng meta mang đúng n trích dẫn", dom.meta.includes(`${n} trích dẫn`), dom.meta);
  }

  const ky_vong = han_che_ky_vong(env.citations);
  ghi(
    "dòng hạn chế đúng từng ký tự với thứ tính lại từ envelope",
    (dom.han_che ?? null) === ky_vong,
    `màn=${JSON.stringify(dom.han_che)} tính=${JSON.stringify(ky_vong)}`,
  );

  env.citations.forEach((c, i) => {
    const h = dom.hang[i];
    if (!h) return;
    const ma = `HE-${String(i + 1).padStart(2, "0")}`;
    ghi(`hàng ${i + 1}: mã ${ma}`, h.chu.includes(ma), h.chu);
    ghi(`hàng ${i + 1}: badge bằng level ${c.level}`, h.badge === c.level, `${h.badge}`);
    ghi(`hàng ${i + 1}: data-muc bằng level`, h.muc === c.level, `${h.muc}`);
    const ns = NHAN_SCOPE[c.scope] ?? c.scope;
    ghi(`hàng ${i + 1}: scope là nhãn "${ns}"`, h.chu.includes(ns), h.chu);
    if (NHAN_SCOPE[c.scope]) {
      ghi(`hàng ${i + 1}: không lộ khóa scope "${c.scope}"`, !h.chu.includes(c.scope), h.chu);
    }
    const nl = NHAN_LOAI[c.content_type] ?? c.content_type;
    ghi(`hàng ${i + 1}: loại là nhãn "${nl}"`, h.chu.includes(nl), h.chu);
    if (NHAN_LOAI[c.content_type]) {
      ghi(`hàng ${i + 1}: không lộ khóa loại "${c.content_type}"`, !h.chu.includes(c.content_type), h.chu);
    }
  });

  ghi("không id hyperedge thật nào trong DOM", !dom.co_id_that, dom.mau_id ?? "");
  for (const c of env.citations) {
    ghi(`id thật ${c.id.slice(0, 12)}... không vào DOM`, !dom.html.includes(c.id), "");
  }
}

// --- Chạy --------------------------------------------------------------------

const ts = doc_tham_so(process.argv.slice(2));
const trinh = await chromium.launch();
const ctx = await trinh.newContext({ viewport: { width: RONG, height: 900 } });
const page = await ctx.newPage();

/** Envelope của từng lượt, bắt ngay trên dây. */
const envelope = [];
page.on("response", async (r) => {
  if (!r.url().includes("/api/hoi-dap")) return;
  try {
    envelope.push(await r.json());
  } catch {
    envelope.push(null);
  }
});

let so_fail = 0;
let so_pass = 0;
function ghi(ten, dat, chi_tiet) {
  if (dat) so_pass += 1;
  else so_fail += 1;
  const dau = dat ? "  PASS" : "  FAIL";
  console.log(`${dau}  ${ten}${dat ? "" : `  <- ${chi_tiet}`}`);
}

await page.goto(`${ts.goc}/dang-nhap`);
await page.fill("#o_tai_khoan", ts.tai_khoan);
await page.fill("#o_mat_khau", mat_khau(ts.tai_khoan));
await page.click("button[type=submit]");
await page.waitForSelector("[data-chip-vai]");
console.log(`\n# ${await page.textContent("[data-chip-vai]")}  @ ${ts.goc}\n`);

for (const [i, cau] of ts.cau.entries()) {
  console.log(`--- lượt ${i + 1}: ${cau}`);
  await page.fill("[data-o-hoi]", cau);
  await page.click("[data-nut-gui]");
  await page.waitForFunction(
    (n) => document.querySelectorAll("[data-luot]").length === n &&
      !document.querySelector("[data-luot]:last-of-type [data-dang-cho]"),
    i + 1,
    { timeout: 300000 },
  );

  const dom = await page.evaluate(() => {
    const luot = document.querySelector("[data-luot]:last-of-type");
    const q = (s) => luot.querySelector(s);
    return {
      nac: q("[data-tra-loi]") ? "tra_loi" : q("[data-tu-choi]") ? "tu_choi" : "loi",
      than: q(".luot__than")?.textContent.trim() ?? null,
      meta: q("[data-luot-meta]")?.textContent.trim() ?? "",
      slab: [...luot.querySelectorAll("[data-slab]")].map((s) => s.textContent),
      nhan_khoi: q("[data-nut-khoi-nguon]")?.textContent.trim() ?? null,
      so_hang: luot.querySelectorAll("[data-cite-row]").length,
      hang: [...luot.querySelectorAll("[data-cite-row]")].map((h) => ({
        muc: h.getAttribute("data-muc"),
        badge: h.querySelector("[data-badge-muc]")?.textContent.trim() ?? null,
        chu: h.textContent.replace(/\s+/g, " ").trim(),
      })),
      han_che: q("[data-han-che] .note_l1__chu")?.textContent.trim().replace(/\s+/g, " ") ?? null,
      nut_khoa: q("[data-nut-xin-truy-cap]")?.disabled ?? null,
      live: q("[data-khoi-nguon]")?.closest("[aria-live]")?.getAttribute("aria-live") ?? null,
      co_id_that: /\bhe-[0-9a-f]{16,}/.test(luot.innerHTML),
      mau_id: (luot.innerHTML.match(/\bhe-[0-9a-f]{16,}/) ?? [null])[0],
      html: luot.innerHTML,
    };
  });

  const env = envelope[i];
  if (!env) {
    ghi("bắt được envelope trên dây", false, "không đọc được JSON");
    continue;
  }
  console.log(`  nấc=${dom.nac} refused=${env.refused} citations=${env.citations.length} slab=${dom.slab.length}`);
  if (dom.than) console.log(`  answer: ${dom.than.slice(0, 200)}`);
  if (dom.slab.length) console.log(`  slab:   ${dom.slab.join("  ")}`);
  // Dump envelope: phép kiểm là so envelope với màn, nên người đọc phải thấy vế
  // envelope. `masked_slots` là thứ quyết định dòng hạn chế, nên nó in ra cả
  // dạng khóa lẫn dạng nhãn.
  env.citations.forEach((c, k) => {
    const vai = c.masked_slots.map((v) => `${v}=${NHAN_SLOT[v] ?? "?"}`).join(",") || "-";
    console.log(`  cit ${k + 1}: ${c.level} ${c.scope}/${c.content_type} nhóm=${c.owner_group ?? "null"} che=[${vai}]`);
  });
  if (dom.han_che) console.log(`  hạn chế: ${dom.han_che}`);

  // (1) Envelope khớp màn.
  kiem_envelope_khop_man(env, dom, ghi);

  // (3) Khối nguồn ngoài vùng live.
  if (dom.nhan_khoi !== null) {
    ghi("khối nguồn nằm trong aria-live=off", dom.live === "off", `${dom.live}`);
  }
  if (dom.han_che !== null) {
    ghi("nút xin truy cập đang khóa", dom.nut_khoa === true, `${dom.nut_khoa}`);
  }
}

// (2) Không cuộn ngang ở 1280.
const rong_cuon = await page.evaluate(() => document.scrollingElement.scrollWidth);
ghi(`không cuộn ngang ở ${RONG}px`, rong_cuon <= RONG, `scrollWidth=${rong_cuon}`);

await page.screenshot({ path: resolve(GOC_REPO, `eval/anh_bang_chung/kiem-tay-4-4-${ts.tai_khoan}.png`) });
await trinh.close();

console.log(`\n${so_pass} PASS, ${so_fail} FAIL`);
process.exit(so_fail === 0 ? 0 : 1);
