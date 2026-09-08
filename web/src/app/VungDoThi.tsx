"use client";

import { useEffect, useRef, useState } from "react";
import type { Core, NodeSingular } from "cytoscape";

import { MA_DO_THI_VE_HONG } from "@/api/do_thi";
import { component } from "@/design/bien_css";
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
//
// **Mọi ca hỏng của tầng vẽ đi ra một mã**, không một canvas trắng: chunk
// Cytoscape không tải được, hay constructor dội vì dữ liệu hỏng, đều gọi
// `bao_hong` để drawer dựng hộp đỏ. Một `void import(...).then(...)` không có
// `.catch` là một unhandled rejection và một drawer đứng im - đúng thứ mà cả
// `la_do_thi` lẫn NFR-10 tồn tại để chặn.

/** Cỡ chữ **gốc** trong canvas, tính bằng px trên màn ở zoom 1. Sàn 13px của
 *  Accessibility Floor áp cho **cả** nhãn đồ thị, nên không giá trị nào ở đây
 *  được xuống dưới - `tests/test_web_khung.py` nhóm (13) đọc ba hằng này ra
 *  khỏi nguồn và chấm chúng, vì phép quét `font-size: <n>px` của nhóm (3)
 *  không thấy một hằng TypeScript. */
export const CO_CHU_VONG = 15;
export const CO_CHU_DINH = 13.5;
export const CO_CHU_VAI = 13;

/** Đường kính node vòng và node đỉnh, đơn vị bố cục. */
const CO_VONG = BAN_KINH_VONG * 2;
const CO_DINH = 20;

/** Đệm quanh đồ thị khi fit, đơn vị px màn hình. */
const DEM_FIT = 40;

/** Viền vòng thường và viền vòng đang sáng. Hover đổi **độ dày và quầng** chứ
 *  không đổi màu chữ: `graph-hover` trên nền trắng chỉ 2,30:1, dưới cả sàn 3:1
 *  cho chỉ báo phi văn bản, nên chữ trong vòng giữ màu của dải. Và vì một màu
 *  đơn lẻ là một chỉ báo yếu, độ dày viền là tín hiệu **phi màu** đi kèm. */
const VIEN_VONG = 4;
const VIEN_VONG_SANG = 7;

/** Hai độ mờ của đỉnh bị che, **đọc từ token** chứ không chọn trong TSX
 *  (`components.graph-entity-masked`; `tests/test_web_khung.py` nhóm (14) đọc
 *  chính hai định danh này ra khỏi file để phép canh không đứng trên một con số
 *  chép lại).
 *
 *  Vì sao **hai** giá trị chứ không một `opacity`: một `opacity: 0.45` trên cả
 *  node làm mờ luôn viền và nhãn `•••`, và viền `graph-entity-border` hợp thành
 *  ở 0,45 trên nền trắng chỉ **2,71:1** - dưới sàn 3:1 cho chỉ báo phi văn bản,
 *  và không đạt sàn ấy ở bất kỳ hệ số máy chiếu nào. Ở 0,8 nó là **7,94:1**.
 *  Nền vẫn mờ 45% nên "đỉnh này mờ hơn" vẫn đọc được bằng mắt; thứ được nâng là
 *  đúng phần nói *đây là một đỉnh*. Nhịp 2 của đường demo che một đỉnh, không
 *  che cả cụm. */
function alpha(muc: Record<string, string>, khoa: string, ten: string): number {
  const v = Number(muc[khoa]);
  // Khóa vắng cho `Number(undefined)` = `NaN`, và một `NaN` đi thẳng vào
  // Cytoscape là một node vẽ ra không ai đoán được. Ném ở đây, một lần, với
  // câu nói được sai ở đâu.
  if (!Number.isFinite(v) || v < 0 || v > 1) {
    throw new Error(`token ${ten}.${khoa} phải là một số trong [0, 1], nhận ${muc[khoa]}`);
  }
  return v;
}

const CHE = component("graph-entity-masked");
const MO_NEN_CHE = alpha(CHE, "fill-opacity", "graph-entity-masked");
const MO_VIEN_CHE = alpha(CHE, "stroke-opacity", "graph-entity-masked");

/** Độ mờ của **mũi tên** tới một đỉnh bị che, cũng đọc từ token
 *  (`components.graph-edge-masked`).
 *
 *  Mũi tên là thứ nói đỉnh mờ ấy thuộc **vòng nào**, tức chính mệnh đề "che
 *  đúng đỉnh, không che cả cụm" của nhịp 2. Bản 4.6 để nó ở `opacity: 0.5` chép
 *  cứng trong file này: màu vòng tối nhất của dải hợp thành ra **2,21:1** trên
 *  nền trắng và nhãn vai của nó **2,08:1**, cả hai dưới sàn 3:1 và chết ở mọi
 *  hệ số máy chiếu. Dấu "đã che" là **nét đứt**, không phải độ mờ. */
const CANH_CHE = component("graph-edge-masked");
const MO_CANH_CHE = alpha(CANH_CHE, "line-opacity", "graph-edge-masked");
const MO_CHU_CANH_CHE = alpha(CANH_CHE, "text-opacity", "graph-edge-masked");

function bien(ten: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(ten).trim();
}

/** Cột màu của dải vòng, đọc từ CSS variables mà `bien_css.ts` sinh: màu sống ở
 *  `tokens.json`, không ở TSX. */
function mau_vong(chi_so: number): string {
  return bien(`--mau-graph-ring-${chi_so}`);
}

function lam_tron(v: number): number {
  return Math.round(v * 100) / 100;
}

export type ViTriTooltip = { trai: number; tren: number };

export function VungDoThi({
  khung,
  ma_sang,
  bao_hong,
}: {
  khung: Khung;
  ma_sang: string | null;
  /** Tầng vẽ hỏng: drawer dựng hộp đỏ mang mã này. */
  bao_hong: (ma: string) => void;
}) {
  const o = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [da_ve, dat_da_ve] = useState(false);
  const [tooltip, dat_tooltip] = useState<ViTriTooltip | null>(null);
  // Hệ số bù cỡ chữ và cỡ chữ **nhỏ nhất trên màn** sau khi bù. Đưa ra DOM để
  // một ca e2e đo được sàn 13px trên một đồ thị lớn thay vì tin vào một phép
  // tính không ai chấm.
  const [do_chu, dat_do_chu] = useState({ he_so: 1, co_man_hinh: CO_CHU_VAI });
  // Tọa độ **đã render** của từng node, tính bằng px trong hệ của
  // `.vung_do_thi` (nó `position: relative`, canvas là `inset: 0` bên trong nên
  // hai hệ trùng nhau). Xem chú thích ở gương `sr-only` dưới đây: đây là cách
  // duy nhất một phép kiểm tự động rê chuột được lên một đỉnh trên canvas mà
  // không phải phơi `cy` ra `window`.
  const [toa_do, dat_toa_do] = useState<Record<string, { x: number; y: number }>>({});

  // Dựng lại cả instance khi khung đổi: một lượt mới hay một lần đổi vai là một
  // đồ thị khác hẳn, và vá từng node vào một instance cũ là chỗ một node của
  // vai trước sống sót qua một lần đổi vai.
  useEffect(() => {
    let con_song = true;
    let hien_tai: Core | null = null;
    let quan_sat: ResizeObserver | null = null;
    dat_da_ve(false);
    dat_tooltip(null);
    dat_toa_do({});
    const vi_tri = bo_cuc(khung);

    /** Bù cỡ chữ theo zoom sau mỗi lần fit.
     *
     *  `font-size` của Cytoscape là **đơn vị không gian đồ thị**, không phải px
     *  màn hình: `fit` co cả hình, nên một đồ thị nhiều vòng đẩy chữ xuống dưới
     *  13px và phá thẳng câu `Always` của spec ("không chữ nào dưới 13px, kể cả
     *  nhãn trong canvas"). Nhân ngược theo `1/zoom` giữ px trên màn đúng bằng
     *  ba hằng gốc.
     *
     *  Chỉ nhân **cỡ chữ**, không nhân `text-max-width`: giữ nguyên bề ngang
     *  cho phép của nhãn thì chữ to hơn chỉ xuống thêm dòng chứ không tràn
     *  ngang khỏi vòng. Hệ quả đã nhận: trên một đồ thị rất lớn nhãn có thể
     *  cao quá vòng - sàn 13px là một `Always` của spec, còn "chữ nằm gọn
     *  trong vòng" là một ghi chú kiểu vẽ. */
    function bu_co_chu(c: Core) {
      const z = c.zoom();
      if (!Number.isFinite(z) || z <= 0) return;
      const he_so = z < 1 ? 1 / z : 1;
      c.nodes(".vong").style("font-size", CO_CHU_VONG * he_so);
      c.nodes(".dinh").style("font-size", CO_CHU_DINH * he_so);
      c.edges().style("font-size", CO_CHU_VAI * he_so);
      dat_do_chu({
        he_so: lam_tron(he_so),
        co_man_hinh: lam_tron(CO_CHU_VAI * he_so * z),
      });
      // Cùng nhịp, không một effect thứ hai: tọa độ đã render chỉ đúng **sau**
      // `fit`, và mọi lần khung nhìn đổi (kéo grip -> `ResizeObserver` -> `fit`)
      // là một lần cả hai con số này lệch cùng lúc.
      const bang: Record<string, { x: number; y: number }> = {};
      for (const ma of [...khung.vong.map((v) => v.ma), ...khung.dinh.map((d) => d.ma)]) {
        const n = c.getElementById(ma);
        if (n.length === 0) continue;
        const p = n.renderedPosition();
        // Khung nhìn chưa ổn định cho `NaN`/`Infinity`, và một `data-x="NaN"`
        // trên gương là một tọa độ mà một phép kiểm sẽ rê chuột tới rồi hỏng ở
        // một bước sau với thông điệp nói sai nguyên nhân. Bỏ qua đỉnh ấy:
        // thiếu thuộc tính là một trạng thái đọc được, `NaN` thì không.
        if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
        bang[ma] = { x: lam_tron(p.x), y: lam_tron(p.y) };
      }
      dat_toa_do(bang);
    }

    void import("cytoscape")
      .then((mod) => {
        const goc = o.current;
        if (!con_song || goc === null) return;
        hien_tai = mod.default({
          container: goc,
          elements: [
            ...khung.vong.map((v) => ({
              data: {
                id: v.ma,
                nhan: v.nhan_ngan === "" ? v.ma : `${v.ma}\n${v.nhan_ngan}`,
                mau: mau_vong(v.mau),
              },
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
                "background-opacity": MO_NEN_CHE,
                "border-opacity": MO_VIEN_CHE,
                "text-opacity": MO_VIEN_CHE,
                // Quầng trắng phải mờ **cùng nhịp** với chữ nó bọc: để nó ở
                // mặc định 1 là một vành trắng 3px đầy đủ quanh một chữ đã mờ,
                // tức nó ăn vào chính nét chữ và làm `•••` khó đọc hơn cả khi
                // không có quầng.
                "text-outline-opacity": MO_VIEN_CHE,
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
                "line-opacity": MO_CANH_CHE,
                "text-opacity": MO_CHU_CANH_CHE,
                "text-outline-opacity": MO_CHU_CANH_CHE,
              },
            },
          ],
          layout: { name: "preset", fit: true, padding: DEM_FIT },
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
        // Tooltip đặt theo `renderedPosition`, tức theo khung nhìn hiện tại.
        // Mọi lần khung nhìn đổi (fit lại sau một cú kéo grip, một lần đặt lại
        // vị trí) làm nó lơ lửng tách khỏi chính đỉnh nó mô tả, và một chú
        // thích "Cần quyền L2" trỏ nhầm đỉnh là một câu nói sai về quyền.
        hien_tai.on("pan zoom resize position", () => {
          dat_tooltip(null);
        });
        bu_co_chu(hien_tai);

        // Drawer kéo giãn được, và Cytoscape **chỉ** tự nghe resize của
        // `window`. Không có quan sát này thì sau một cú kéo grip canvas giữ
        // kích thước cũ: đồ thị lệch khỏi khung hay bị cắt mất một phần, và
        // hai ca e2e đo `boundingBox` của drawer vẫn xanh trong đúng trạng
        // thái ấy.
        quan_sat = new ResizeObserver(() => {
          const c = cy.current;
          if (c === null) return;
          dat_tooltip(null);
          c.resize();
          c.fit(undefined, DEM_FIT);
          bu_co_chu(c);
        });
        quan_sat.observe(goc);

        cy.current = hien_tai;
        dat_da_ve(true);
      })
      .catch(() => {
        // Chunk Cytoscape không tải được, hay constructor dội vì dữ liệu hỏng.
        // Cả hai là **lỗi hệ thống nhìn thấy được**, không một canvas trắng:
        // một drawer đứng ở `data-da-ve="0"` không nói được nó đang trống hay
        // đang hỏng, và đó đúng là chỗ NFR-10 đòi phân biệt.
        if (con_song) bao_hong(MA_DO_THI_VE_HONG);
      });

    return () => {
      con_song = false;
      cy.current = null;
      if (quan_sat !== null) quan_sat.disconnect();
      if (hien_tai !== null) hien_tai.destroy();
    };
  }, [khung, bao_hong]);

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
      /* Số node hyperedge mà server trả về nhưng không citation nào của
         lượt nhận, tức không có mã `HE-nn` để đặt. Theo hợp đồng nó luôn
         bằng 0 (`/do-thi` chỉ nhận đúng danh sách id của `citations`), và
         `dung_khung` **bỏ** những node ấy. Phơi ra đây để phép bỏ im lặng
         thành một con số ca e2e đọc được: một `bi_bo` khác 0 là hợp đồng
         giữa hai tuyến đã trôi, không phải một vòng vẽ thiếu vô hại. */
      data-so-bo={khung.bi_bo}
      /* Tên thuộc tính cố ý không chứa chuỗi `he-`: ca e2e "mở bằng nút"
         khẳng định DOM của drawer không mang một byte nào của id hyperedge
         thật bằng cách quét đúng chuỗi ấy, và một tên `data-he-so-chu` làm
         phép quét đó đỏ vì một lý do không liên quan. */
      data-ty-le-chu={do_chu.he_so}
      data-co-chu-man-hinh={do_chu.co_man_hinh}
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
          cite-row đã dùng.

          Từ story 4.7 mỗi mục còn mang `data-x`/`data-y`: tọa độ **đã render**
          của node ấy trong hệ của `.vung_do_thi`, cập nhật cùng nhịp với phép
          bù cỡ chữ. Nó không thêm một byte thông tin nào (nó là chỗ node đang
          nằm, thứ ai nhìn màn hình cũng thấy) và nó đóng đúng một lỗ: tooltip
          "Cần quyền L2" vẽ **trên canvas**, nên trước đó không phép kiểm tự
          động nào rê chuột tới được một đỉnh mờ, và đường duy nhất còn lại là
          phơi `cy` ra `window` - tức thêm mã chỉ để test vào đường phục vụ. */}
      <ul className="sr-only" data-guong-do-thi>
        {khung.vong.map((v) => (
          <li
            key={v.ma}
            data-guong-vong={v.ma}
            data-x={toa_do[v.ma]?.x}
            data-y={toa_do[v.ma]?.y}
          >
            {v.nhan_ngan === "" ? v.ma : `${v.ma}: ${v.nhan_ngan}`}
          </li>
        ))}
        {khung.dinh.map((d) => (
          <li
            key={d.ma}
            data-guong-dinh={d.ma}
            data-che={d.che ? "1" : undefined}
            data-x={toa_do[d.ma]?.x}
            data-y={toa_do[d.ma]?.y}
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
