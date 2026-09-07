import { notFound } from "next/navigation";

import { BoMau } from "./BoMau";

/** Trang mẫu dev-only để soát khung bằng mắt: bảng màu kèm tỷ lệ tương phản,
 *  thang chữ, chip, nút, errbox, modal. Ở production trả 404, nên nó là ngoại lệ
 *  có tên duy nhất của phép canh sidebar-route trong `tests/test_web_khung.py`.
 *
 *  Hai rào cho production. Rào thật là `src/proxy.ts` trả 404 trước khi render:
 *  một mình `notFound()` ở đây chỉ cho ra thân trang 404 với mã HTTP 200 (đo
 *  trên image standalone ở máy chủ 07/09/2026, prerender tĩnh). `notFound()`
 *  giữ lại làm rào thứ hai cho ca ai bỏ proxy. */
export default function TrangMau() {
  if (process.env.NODE_ENV === "production") notFound();
  return <BoMau />;
}
