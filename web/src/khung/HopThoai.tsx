"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { MICROCOPY } from "@/microcopy";

const CHON_FOCUS =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

type ThuocTinh = {
  mo: boolean;
  tieu_de: string;
  dong: () => void;
  children: ReactNode;
  chan?: ReactNode;
};

/** Modal một lớp 560px (DESIGN.md Components). Esc đóng; focus trap tối thiểu
 *  (Tab quay vòng trong hộp, focus vào phần tử đầu khi mở, trả về phần tử đã
 *  mở khi đóng). Cấm modal chồng modal: caller chỉ mở một hộp một lúc. */
export function HopThoai({ mo, tieu_de, dong, children, chan }: ThuocTinh) {
  const hop = useRef<HTMLDivElement>(null);
  const truoc_khi_mo = useRef<Element | null>(null);
  // `dong` giữ trong ref: effect chỉ phụ thuộc `mo`, nên caller truyền một
  // closure mới mỗi lần render không làm listener gỡ/gắn lại hay mất focus.
  const dong_ref = useRef(dong);
  dong_ref.current = dong;

  // Gắn phím và focus vào hộp khi mở; gỡ listener khi đóng hay unmount.
  useEffect(() => {
    if (!mo) return;
    truoc_khi_mo.current = document.activeElement;
    const dau = hop.current?.querySelector<HTMLElement>(CHON_FOCUS);
    (dau ?? hop.current)?.focus();

    function phim(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        dong_ref.current();
        return;
      }
      if (e.key !== "Tab" || !hop.current) return;
      const cac = Array.from(hop.current.querySelectorAll<HTMLElement>(CHON_FOCUS));
      if (cac.length === 0) return;
      const dau_tien = cac[0];
      const cuoi = cac[cac.length - 1];
      if (e.shiftKey && document.activeElement === dau_tien) {
        e.preventDefault();
        cuoi.focus();
      } else if (!e.shiftKey && document.activeElement === cuoi) {
        e.preventDefault();
        dau_tien.focus();
      }
    }
    document.addEventListener("keydown", phim);
    return () => document.removeEventListener("keydown", phim);
  }, [mo]);

  // Trả focus về phần tử trước khi mở, chỉ khi `mo` chuyển sang false (tách
  // khỏi cleanup gỡ listener, để một re-render giữa chừng không trả focus sớm).
  useEffect(() => {
    if (mo) return;
    const cu = truoc_khi_mo.current;
    truoc_khi_mo.current = null;
    if (cu instanceof HTMLElement) cu.focus();
  }, [mo]);

  if (!mo) return null;
  return (
    <div className="hop_thoai__nen" onMouseDown={(e) => e.target === e.currentTarget && dong()}>
      <div
        className="hop_thoai"
        role="dialog"
        aria-modal="true"
        aria-labelledby="hop_thoai_tieu_de"
        ref={hop}
        tabIndex={-1}
      >
        <div className="hop_thoai__dau">
          <span id="hop_thoai_tieu_de">{tieu_de}</span>
          <button type="button" className="hop_thoai__dong" onClick={dong} aria-label={MICROCOPY.dong}>
            ✕
          </button>
        </div>
        <div className="hop_thoai__than">{children}</div>
        {chan && <div className="hop_thoai__chan">{chan}</div>}
      </div>
    </div>
  );
}
