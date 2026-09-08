"use client";

import { useState } from "react";

import { type TrichDan } from "@/api/hoi_dap";
import { component, TOKENS } from "@/design/bien_css";
import { HopLoi } from "@/khung/HopLoi";
import { HopThoai } from "@/khung/HopThoai";
import { nhan_vai } from "@/api/phien";
import { dien, MICROCOPY } from "@/microcopy";
import { mo_ta_vai } from "@/nhan";

import { DongHanChe } from "../DongHanChe";
import { KhoiNguon } from "../KhoiNguon";

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
  ["#FFFFFF", "level-l1"],
  ["level-l1-ink", "surface-card"],
  ["level-l1-ink", "primary-tint"],
  ["ink-muted", "primary-tint"],
  ["level-l1-ink", "surface-stream"],
  ["ink-muted", "level-l1-bg"],
  ["ink", "primary-tint-soft"],
  ["ink-muted", "primary-tint-soft"],
  ["graph-ring-1", "surface-card"],
  ["graph-ring-2", "surface-card"],
  ["graph-ring-3", "surface-card"],
  ["graph-ring-4", "surface-card"],
  ["graph-ring-5", "surface-card"],
  ["primary", "primary-tint"],
];

/** Dải màu vòng hyperedge, khóa của `tokens.colors`. Vòng thứ sáu quay vòng
 *  lại về màu đầu, nên năm ô dưới là **toàn bộ** dải mà đồ thị dùng. */
const MAU_VONG = ["graph-ring-1", "graph-ring-2", "graph-ring-3", "graph-ring-4", "graph-ring-5"];

/** Hai citation mẫu để xem cite-row, badge mức và dòng hạn chế L1 mà không cần
 *  một lượt hỏi thật. Cùng sáu khóa đóng với `adapters.trich_dan.KHOA_TRICH_DAN`. */
const TRICH_DAN_MAU: TrichDan[] = [
  {
    id: "he-mau-l2",
    level: "L2",
    scope: "noi_bo",
    content_type: "runbook",
    masked_slots: ["owner"],
    owner_group: "DevOps",
  },
  {
    id: "he-mau-l1",
    level: "L1",
    scope: "khach_hang_a",
    content_type: "bao_cao_su_co",
    masked_slots: ["cause", "remediation", "owner"],
    owner_group: "DevOps",
  },
];

/** Năm vai của bảng chính sách, chỉ để trang mẫu có gì mà vẽ. `MenuXemNhu`
 *  thật **không** có danh sách nào như thế - nó đọc `GET /auth/vai`, và pytest
 *  quét cấm mọi tên vai chép cứng trong file ấy. */
const VAI_MAU = ["devops", "tech_support", "sale_ba", "truong_nhom", "admin"];

const MAU = TOKENS.colors as Record<string, string>;
const hex = (ten: string) => (ten.startsWith("#") ? ten : MAU[ten]);

export function BoMau() {
  const [mo, dat_mo] = useState(false);
  // Đếm để trang re-render trong lúc modal mở: bài e2e chấm focus vẫn trả về
  // nút mở sau Esc dù component cha đã render lại giữa chừng.
  const [dem, dat_dem] = useState(0);
  const [mo_nguon, dat_mo_nguon] = useState(true);
  const chip_vai = component("chip-role");
  const slab = component("slab-redact");
  const badge_l1 = component("badge-level-l1");
  const badge_l2 = component("badge-level-l2");
  const mo_che = component("graph-entity-masked");
  // Viền và nhãn `•••` mờ theo `stroke-opacity` (cả span), còn **nền** mờ thêm
  // xuống `fill-opacity` bằng một phép trộn: hai độ mờ là hai giá trị khác nhau
  // của cùng một component, và lồng hai `opacity` vào nhau thì nhân chúng lại.
  const che = {
    stroke_opacity: Number(mo_che["stroke-opacity"]),
    nen: Math.round(
      (Number(mo_che["fill-opacity"]) / Number(mo_che["stroke-opacity"])) * 100,
    ),
  };

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

      <h2 className="tieu_de_khoi">Khối nguồn, cite-row và dòng hạn chế L1</h2>
      <div className="the">
        <p className="luot__than">
          App01 gặp sự cố ngày 12/08.{" "}
          <span className="slab">{dien("slab_che", { ten_slot: "nguyên nhân" })}</span>{" "}
          <span className="slab">{dien("slab_owner", { ten_slot: "người phụ trách", nhom: "DevOps" })}</span>{" "}
          đã xử lý xong.
        </p>
        <KhoiNguon citations={TRICH_DAN_MAU} mo={mo_nguon} dat_mo={dat_mo_nguon} />
        <DongHanChe citations={TRICH_DAN_MAU} />
      </div>

      {/* Ba khối của "xem như" (story 4.5) dựng **tĩnh** ở đây, không qua
          `MenuXemNhu`: component thật đọc `GET /auth/vai` và ghi token, tức
          trang mẫu sẽ đổi vai thật của người đang xem. Ở đây chỉ cần thấy màu,
          cỡ chữ và tương phản của chip, mục vai và mốc đổi vai. Danh mục vai
          lấy từ đúng bảng nhãn mà pytest ghim với `config/policy-*.yaml`. */}
      <h2 className="tieu_de_khoi">Xem như: chip, mục vai và mốc đổi vai</h2>
      <div className="the" style={{ background: "var(--mau-primary-deep)", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span className="chip_xem_nhu">
          {dien("chip_xem_nhu", { vai: nhan_vai("tech_support") })}
          <span className="chip_xem_nhu__x">✕</span>
        </span>
        <span className="nut_xem_nhu">
          {MICROCOPY.nut_xem_nhu}
          <span className="nut_xem_nhu__caret">▾</span>
        </span>
        <span className="chip_vai_that">dev01 · {nhan_vai("devops")}</span>
      </div>
      <div className="the" style={{ padding: 0, overflow: "hidden" }}>
        <div className="menu_vai" style={{ position: "static", width: "100%", boxShadow: "none", border: 0 }}>
          <div className="menu_vai__tieu_de">{MICROCOPY.tieu_de_menu_vai}</div>
          {VAI_MAU.map((v) => (
            <div key={v} className="menu_vai__muc" data-dang-chon={v === "tech_support" ? "1" : undefined}>
              <span className="menu_vai__dau">{v === "tech_support" ? "✓" : ""}</span>
              <span className="menu_vai__chu">
                <span className="menu_vai__ten">{nhan_vai(v)}</span>
                {mo_ta_vai(v) !== null && <span className="menu_vai__mo_ta">{mo_ta_vai(v)}</span>}
              </span>
            </div>
          ))}
          <div className="menu_vai__thoat">
            <span className="menu_vai__x">✕</span>
            {MICROCOPY.thoat_xem_nhu}
            <span className="menu_vai__ve">
              {dien("ve_vai_that", { tai_khoan: "dev01", vai: nhan_vai("devops") })}
            </span>
          </div>
        </div>
      </div>
      <div className="the" style={{ background: "var(--mau-surface-stream)" }}>
        <div className="moc_doi_vai">
          <span>{dien("divider_doi_vai", { vai: nhan_vai("tech_support") })}</span>
        </div>
      </div>

      <h2 className="tieu_de_khoi">Đồ thị: dải màu vòng và ba trạng thái node</h2>
      <div className="the" style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
        {MAU_VONG.map((ten, i) => (
          <span key={ten} style={{ display: "inline-flex", alignItems: "center", gap: 8 }} data-mau-vong={ten}>
            <i
              style={{
                width: 30,
                height: 30,
                borderRadius: "50%",
                border: `4px solid ${hex(ten)}`,
                display: "inline-block",
              }}
            />
            <b style={{ color: hex(ten) }}>HE-{String(i + 1).padStart(2, "0")}</b>
          </span>
        ))}
      </div>
      <div className="the" style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
        {/* Ba trạng thái node của DESIGN.md: vòng hyperedge rỗng ruột, entity
            thấy được, entity bị che (mờ 45%, nét đứt, nhãn "•••"). Vòng đang
            sáng đổi **viền và quầng** chứ không đổi màu chữ - `graph-hover`
            trên nền trắng chỉ 2,30:1. */}
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }} data-node-mau="vong">
          <i style={{ width: 30, height: 30, borderRadius: "50%", border: "4px solid var(--mau-graph-ring-1)", display: "inline-block" }} />
          vòng hyperedge
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }} data-node-mau="vong-sang">
          <i
            style={{
              width: 30,
              height: 30,
              borderRadius: "50%",
              border: "7px solid var(--mau-graph-hover)",
              boxShadow: "0 0 0 6px color-mix(in srgb, var(--mau-graph-hover-halo) 30%, transparent)",
              display: "inline-block",
            }}
          />
          vòng đang sáng
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }} data-node-mau="dinh">
          <i style={{ width: 16, height: 16, borderRadius: "50%", background: "var(--mau-graph-entity-fill)", border: "2px solid var(--mau-graph-entity-border)", display: "inline-block" }} />
          entity
        </span>
        {/* Hai độ mờ, đọc từ `components.graph-entity-masked` như `VungDoThi`
            đọc (story 4.7): nền mờ 45% giữ nguyên, viền và nhãn `•••` lên 0,8
            vì cặp hợp thành ở 0,45 chỉ 2,71:1 trên nền trắng. Trang mẫu phải
            hiện đúng thứ canvas vẽ, nếu không nó là bản chép thứ hai. */}
        <span
          style={{ display: "inline-flex", alignItems: "center", gap: 8, opacity: che.stroke_opacity }}
          data-node-mau="dinh-che"
        >
          <i
            style={{
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: `color-mix(in srgb, var(--mau-graph-entity-fill) ${che.nen}%, transparent)`,
              border: "2px dashed var(--mau-graph-entity-border)",
              display: "inline-block",
            }}
          />
          ••• ({MICROCOPY.tooltip_node_mo})
        </span>
      </div>
      <div className="the" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="nut_do_thi">
          {MICROCOPY.nut_do_thi}
        </button>
        <button type="button" className="nut_do_thi" data-active="1">
          {MICROCOPY.nut_do_thi}
        </button>
        <span className="graph_head__chip">{dien("chip_vai_dang_xem", { vai: nhan_vai("tech_support") })}</span>
        <span className="cite_row__dang_sang">{dien("chu_thich_dang_sang", { ma: "HE-01" })}</span>
        <span className="tooltip_node" style={{ position: "static" }}>
          {MICROCOPY.tooltip_node_mo}
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
