"use client";

import { useState } from "react";

import { component, TOKENS } from "@/design/bien_css";
import { HopLoi } from "@/khung/HopLoi";
import { HopThoai } from "@/khung/HopThoai";
import { dien, MICROCOPY } from "@/microcopy";

// Tỷ lệ tương phản WCAG, cùng công thức với `tests/test_web_khung.py`. Bản này
// chỉ để hiển thị trên trang mẫu; phép canh sống ở pytest.
function kenh(c: number): number {
  const v = c / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}
function do_sang(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * kenh(r) + 0.7152 * kenh(g) + 0.0722 * kenh(b);
}
function tuong_phan(a: string, b: string): number {
  const [s, t] = [do_sang(a), do_sang(b)].sort((x, y) => y - x);
  return (s + 0.05) / (t + 0.05);
}

const CAP: Array<[string, string]> = [
  ["#FFFFFF", "primary-deep"],
  ["#FFFFFF", "primary"],
  ["redact-ink", "redact-bg"],
  ["level-l1-ink", "level-l1-bg"],
  ["level-l2", "level-l2-bg"],
  ["danger", "danger-bg"],
  ["ink", "surface-card"],
  ["ink-muted", "surface-card"],
  ["ink", "surface-app"],
];

const MAU = TOKENS.colors as Record<string, string>;
const hex = (ten: string) => (ten.startsWith("#") ? ten : MAU[ten]);

export function BoMau() {
  const [mo, dat_mo] = useState(false);
  // Đếm để trang re-render trong lúc modal mở: bài e2e chấm focus vẫn trả về
  // nút mở sau Esc dù component cha đã render lại giữa chừng.
  const [dem, dat_dem] = useState(0);
  const chip_vai = component("chip-role");
  const slab = component("slab-redact");
  const badge_l1 = component("badge-level-l1");
  const badge_l2 = component("badge-level-l2");

  return (
    <div data-bo-mau>
      <h1 className="tieu_de_trang">Bộ mẫu khung (chỉ admin)</h1>

      <h2 className="tieu_de_khoi">Ô hỏi (đích của ⌘K)</h2>
      <textarea className="o_hoi" rows={2} data-o-hoi placeholder={MICROCOPY.placeholder_o_hoi} />

      <h2 className="tieu_de_khoi">Bảng màu và tương phản</h2>
      <div className="the" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
        {CAP.map(([chu, nen]) => {
          const ty_le = tuong_phan(hex(chu), hex(nen));
          return (
            <div
              key={`${chu}/${nen}`}
              data-cap-tuong-phan
              style={{ background: hex(nen), color: hex(chu), padding: 10, borderRadius: 4, border: "1px solid var(--mau-border)" }}
            >
              <div style={{ fontWeight: 600 }}>
                {chu} / {nen}
              </div>
              <div>{ty_le.toFixed(2)}:1 {ty_le >= 4.5 ? "đạt" : "dưới sàn"}</div>
            </div>
          );
        })}
      </div>

      <h2 className="tieu_de_khoi">Thang chữ</h2>
      <div className="the">
        {Object.entries(TOKENS.typography).map(([ten, muc]) => (
          <div key={ten} style={{ fontSize: `var(--chu-${ten}-co)`, fontWeight: `var(--chu-${ten}-dam, 400)` as never, fontFamily: `var(--chu-${ten}-font, inherit)` }}>
            {ten} · {(muc as { fontSize: string }).fontSize}
          </div>
        ))}
      </div>

      <h2 className="tieu_de_khoi">Chip, badge, slab</h2>
      <div className="the" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ background: "var(--mau-primary-deep)", padding: 6, borderRadius: chip_vai.radius }}>
          <span className="chip_vai">dev01 · DevOps</span>
        </span>
        <span style={{ background: badge_l2.background, color: badge_l2.foreground, borderRadius: badge_l2.radius, padding: "2px 8px", fontSize: "var(--chu-meta-chip-co)", fontWeight: 600 }}>L2</span>
        <span style={{ background: badge_l1.background, color: badge_l1.foreground, borderRadius: badge_l1.radius, padding: "2px 8px", fontSize: "var(--chu-meta-chip-co)", fontWeight: 600 }}>L1</span>
        <span style={{ background: slab.background, color: slab.foreground, borderRadius: slab.radius, padding: "1px 6px", fontWeight: 700 }}>
          {dien("slab_che", { ten_slot: "nguyên nhân" })}
        </span>
      </div>

      <h2 className="tieu_de_khoi">Nút và hộp lỗi</h2>
      <div className="the" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="nut_chinh">
          Gửi
        </button>
        <button type="button" className="nut_phu">
          {MICROCOPY.dong}
        </button>
        <button type="button" className="nut_chinh" onClick={() => dat_mo(true)} data-mo-hop-thoai>
          Mở modal
        </button>
        <div style={{ flexBasis: "100%" }}>
          <HopLoi>{MICROCOPY.loi_he_thong}</HopLoi>
        </div>
      </div>

      <h2 className="tieu_de_khoi">Microcopy</h2>
      <div className="the">
        <p>{MICROCOPY.tu_choi}</p>
        <p>{dien("dong_han_che_l1", { n: 2, cac_slot: "nguyên nhân, hành động khắc phục", nhom: "DevOps" })}</p>
        <p>{MICROCOPY.phien_het_han}</p>
      </div>

      <HopThoai
        mo={mo}
        tieu_de="Modal mẫu 560px"
        dong={() => dat_mo(false)}
        chan={
          <button type="button" className="nut_chinh" onClick={() => dat_mo(false)}>
            {MICROCOPY.dong}
          </button>
        }
      >
        <p>Một lớp, Esc đóng, focus trả về nút mở.</p>
        <button type="button" className="nut_phu" onClick={() => dat_dem(dem + 1)} data-dem>
          Đếm {dem}
        </button>
      </HopThoai>
    </div>
  );
}
