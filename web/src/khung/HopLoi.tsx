import type { ReactNode } from "react";

/** Hộp lỗi hệ thống (components.errbox): viền trái đỏ, icon kèm chữ, chỉ cho
 *  lỗi hệ thống. Bị che không phải lỗi, từ chối FR-16 không đi qua đây. */
export function HopLoi({ children }: { children: ReactNode }) {
  return (
    <div className="hop_loi" role="alert" data-hop-loi>
      <span aria-hidden="true">⚠</span>
      <div>{children}</div>
    </div>
  );
}
