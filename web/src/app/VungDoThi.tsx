"use client";

import { useEffect, useRef, useState } from "react";
import type { Core, NodeSingular } from "cytoscape";

import { MICROCOPY } from "@/microcopy";
import { nhan_slot } from "@/nhan";

import { bo_cuc, BAN_KINH_VONG } from "./do_thi_bo_cuc";
import type { Khung } from "./do_thi_khung";

// Vùng canvas của drawer đồ thị (story 4.6): Cytoscape vẽ kiểu paper
// HyperGraphRAG - vòng hyperedge rỗng ruột viền dày, mũi tên tỏa từ mép vòng
// tới entity, nhãn vai slot dọc mũi tên (DESIGN.md Components, mockup trạng
// thái B).
//
// **Cytoscape chỉ nhận mã hiển thị.** `dung_khung` đã đổi mọi id thật thành
// `HE-nn` / `en-k` / `HE-nn#slot` trước khi khung tới đây, nên không id thật
// nào vào được `data-*` của canvas hay vào bất kỳ chỗ chèn JSX nào.
//
// **Tất định**: vị trí do `bo_cuc` tính, layout là `preset` - Cytoscape chỉ
// đặt node vào chỗ đã cho rồi fit khung nhìn. Không `cose`, không `random`,
// không nguồn ngẫu nhiên nào; `tests/test_web_khung.py` nhóm (13) quét cả hai
// vế của luật ấy.

/** Cỡ chữ trong canvas. Sàn 13px của Accessibility Floor áp cho **cả** nhãn
 *  đồ thị, nên không giá trị nào ở đây được xuống dưới. */
const CO_CHU_VONG = 15;
const CO_CHU_DINH = 13.5;
const CO_CHU_VAI = 13;

/** Đường kính node vòng và node đỉnh, đơn vị bố cục. */
const CO_VONG = BAN_KINH_VONG * 2;
const CO_DINH = 20;

/** Viền vòng thường và viền vòng đang sáng. Hover đổi **độ dày và quầng** chứ
 *  không đổi màu chữ: `graph-hover` trên nền trắng chỉ 2,30:1, dưới cả sàn 3:1
 *  cho chỉ báo phi văn bản, nên chữ trong vòng giữ màu của dải. Và vì một màu
 *  đơn lẻ là một chỉ báo yếu, độ dày viền là tín hiệu **phi màu** đi kèm. */
const VIEN_VONG = 4;
const VIEN_VONG_SANG = 7;

function bien(ten: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(ten).trim();
}

/** Cột màu của dải vòng, đọc từ CSS variables mà `bien_css.ts` sinh: màu sống ở
 *  `tokens.json`, không ở TSX. */
function mau_vong(chi_so: number): string {
  return bien(`--mau-graph-ring-${chi_so}`);
}

export type ViTriTooltip = { trai: number; tren: number };

export function VungDoThi({ khung, ma_sang }: { khung: Khung; ma_sang: string | null }) {
  const o = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [da_ve, dat_da_ve] = useState(false);
  const [tooltip, dat_tooltip] = useState<ViTriTooltip | null>(null);

  // Dựng lại cả instance khi khung đổi: một lượt mới hay một lần đổi vai là một
  // đồ thị khác hẳn, và vá từng node vào một instance cũ là chỗ một node của
  // vai trước sống sót qua một lần đổi vai.
  useEffect(() => {
    let con_song = true;
    let hien_tai: Core | null = null;
    dat_da_ve(false);
    dat_tooltip(null);
    const vi_tri = bo_cuc(khung);
    void import("cytoscape").then((mod) => {
      const goc = o.current;
      if (!con_song || goc === null) return;
      hien_tai = mod.default({
        container: goc,
        elements: [
          ...khung.vong.map((v) => ({
            data: { id: v.ma, nhan: v.nhan_ngan === "" ? v.ma : `${v.ma}\n${v.nhan_ngan}`, mau: mau_vong(v.mau) },
            position: { ...vi_tri[v.ma] },
            classes: "vong",
          })),
          ...khung.dinh.map((d) => ({
            data: { id: d.ma, nhan: d.nhan },
            position: { ...vi_tri[d.ma] },
            classes: d.che ? "dinh che" : "dinh",
          })),
          ...khung.canh.map((c) => ({
            data: {
              id: `${c.tu}>${c.den}:${c.slot}`,
              source: c.tu,
              target: c.den,
              vai: nhan_slot(c.slot),
              mau: mau_vong(khung.vong.find((v) => v.ma === c.tu)?.mau ?? 1),
            },
            classes: c.che ? "canh che" : "canh",
          })),
        ],
        style: [
          {
            selector: "node.vong",
            style: {
              shape: "ellipse",
              width: CO_VONG,
              height: CO_VONG,
              "background-opacity": 0,
              "border-width": VIEN_VONG,
              "border-color": "data(mau)",
              label: "data(nhan)",
              color: "data(mau)",
              "font-size": CO_CHU_VONG,
              "font-weight": 700,
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": `${CO_VONG - 16}px`,
            },
          },
          {
            selector: "node.vong.dang-sang",
            style: {
              "border-width": VIEN_VONG_SANG,
              "border-color": bien("--mau-graph-hover"),
              "overlay-color": bien("--mau-graph-hover-halo"),
              "overlay-opacity": 0.3,
              "overlay-padding": 12,
            },
          },
          {
            selector: "node.dinh",
            style: {
              shape: "ellipse",
              width: CO_DINH,
              height: CO_DINH,
              "background-color": bien("--mau-graph-entity-fill"),
              "border-width": 2,
              "border-color": bien("--mau-graph-entity-border"),
              label: "data(nhan)",
              color: bien("--mau-ink"),
              "font-size": CO_CHU_DINH,
              "font-weight": 700,
              "text-valign": "bottom",
              "text-margin-y": 6,
              "text-outline-color": "#FFFFFF",
              "text-outline-width": 3,
              "text-wrap": "wrap",
              "text-max-width": "150px",
            },
          },
          {
            selector: "node.dinh.che",
            style: {
              opacity: 0.45,
              "border-style": "dashed",
            },
          },
          {
            selector: "edge",
            style: {
              "curve-style": "straight",
              width: 2,
              "line-color": "data(mau)",
              "target-arrow-color": "data(mau)",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.9,
              label: "data(vai)",
              color: bien("--mau-ink-muted"),
              "font-size": CO_CHU_VAI,
              "text-rotation": "autorotate",
              "text-outline-color": "#FFFFFF",
              "text-outline-width": 3,
            },
          },
          {
            selector: "edge.che",
            style: {
              "line-style": "dashed",
              opacity: 0.5,
            },
          },
        ],
        layout: { name: "preset", fit: true, padding: 40 },
        // Bốn phép tương tác của story 4.8 (zoom, pan, chọn node, kéo node) tắt
        // hẳn ở đây: spec 4.6 xếp cả bốn vào story sau, và một canvas trượt đi
        // dưới tay người trình bày giữa buổi demo là một hình không ai lấy lại
        // được đúng như cũ.
        userZoomingEnabled: false,
        userPanningEnabled: false,
        boxSelectionEnabled: false,
        autoungrabify: true,
        autounselectify: true,
      });
      hien_tai.on("mouseover", "node.che", (evt) => {
        const n = evt.target as NodeSingular;
        const p = n.renderedPosition();
        dat_tooltip({ trai: p.x + 16, tren: p.y - 12 });
      });
      hien_tai.on("mouseout", "node.che", () => {
        dat_tooltip(null);
      });
      cy.current = hien_tai;
      dat_da_ve(true);
    });
    return () => {
      con_song = false;
      cy.current = null;
      if (hien_tai !== null) hien_tai.destroy();
    };
  }, [khung]);

  // Vòng đang sáng: một lớp CSS trên đúng một node, không dựng lại đồ thị.
  useEffect(() => {
    const c = cy.current;
    if (c === null) return;
    c.nodes(".vong").removeClass("dang-sang");
    if (ma_sang !== null) c.getElementById(ma_sang).addClass("dang-sang");
  }, [ma_sang, da_ve]);

  return (
    <div
      className="vung_do_thi"
      data-vung-do-thi
      data-da-ve={da_ve ? "1" : "0"}
      data-so-vong={khung.vong.length}
      data-so-dinh={khung.dinh.length}
      data-so-dinh-che={khung.dinh.filter((d) => d.che).length}
    >
      <div
        className="vung_do_thi__canvas"
        ref={o}
        role="img"
        aria-label={MICROCOPY.nhan_vung_do_thi}
      />
      {/* Gương chữ của đúng thứ đang vẽ trên canvas. Canvas là một tấm ảnh với
          trình đọc màn hình và với mọi phép kiểm tự động, nên một `aria-label`
          một dòng là toàn bộ thứ chúng nhận được từ một đồ thị mười đỉnh.
          Gương này không thêm một byte thông tin nào so với màn hình: vòng
          mang đúng chữ viết **trong** vòng (mã cộng nhãn ngắn; `label` đầy đủ
          nằm ở legend), đỉnh bị che ra `•••` đúng như trên canvas
          (EXPERIENCE.md: node mờ **không** hiện tên), và mã hiển thị là mã mà
          cite-row đã dùng. */}
      <ul className="sr-only" data-guong-do-thi>
        {khung.vong.map((v) => (
          <li key={v.ma} data-guong-vong={v.ma}>
            {v.nhan_ngan === "" ? v.ma : `${v.ma}: ${v.nhan_ngan}`}
          </li>
        ))}
        {khung.dinh.map((d) => (
          <li
            key={d.ma}
            data-guong-dinh={d.ma}
            data-che={d.che ? "1" : undefined}
            title={d.che ? MICROCOPY.tooltip_node_mo : undefined}
          >
            {d.nhan}
          </li>
        ))}
      </ul>
      {/* Tooltip của đỉnh mờ. Canvas không mang được `title`, nên nó là một
          phần tử DOM đặt theo `renderedPosition` - và nhờ vậy Playwright đọc
          được đúng chuỗi mà bảng Voice and Tone chốt. Chỉ báo mức, không mời
          bấm: điểm khởi phát break-glass duy nhất là dòng hạn chế trong chat
          (FR-20). */}
      {tooltip !== null && (
        <span
          className="tooltip_node"
          data-tooltip-node
          style={{ left: tooltip.trai, top: tooltip.tren }}
        >
          {MICROCOPY.tooltip_node_mo}
        </span>
      )}
    </div>
  );
}
