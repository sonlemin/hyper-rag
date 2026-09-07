import { Suspense } from "react";

import { ManDangNhap } from "./ManDangNhap";

/** Màn đăng nhập: cửa vào duy nhất của console.
 *
 *  Server component chỉ để bọc `Suspense`. `ManDangNhap` đọc `?ly_do=het_han`
 *  bằng `useSearchParams`, và hook đó đòi một ranh giới `Suspense` lúc Next
 *  prerender tĩnh route này; thiếu ranh giới là `next build` đỏ. `fallback` là
 *  `null` chứ không phải một khung giả: card nhấp nháy rồi biến mất trông giống
 *  một lỗi hơn là một lần tải. */
export default function TrangDangNhap() {
  return (
    <Suspense fallback={null}>
      <ManDangNhap />
    </Suspense>
  );
}
