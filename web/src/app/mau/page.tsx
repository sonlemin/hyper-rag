"use client";

import { notFound } from "next/navigation";

import { usePhien } from "@/khung/KhungApp";
import { BoMau } from "./BoMau";

/** Trang mẫu để soát khung bằng mắt: bảng màu kèm tỷ lệ tương phản, thang
 *  chữ, chip, nút, errbox, modal. Chỉ tài khoản có cờ `admin` xem được, ở mọi
 *  môi trường (quyết định 07/09/2026 thay cho rào theo môi trường build, vì máy chủ là nơi
 *  duy nhất sonlm mở giao diện); ai khác nhận 404 của Next. Nó là ngoại lệ có tên
 *  duy nhất của phép canh sidebar-route trong `tests/test_web_khung.py`.
 *
 *  Vì sao rào ở tầng client chứ không ở proxy: token sống trong sessionStorage,
 *  không đi kèm request HTML nên proxy không nhìn thấy phiên. Nội dung trang chỉ
 *  là token thiết kế (đã có trong CSS variables của mọi trang) và các component
 *  mẫu, không dữ liệu tri thức. */
export default function TrangMau() {
  const phien = usePhien();
  if (!phien?.admin) notFound();
  return <BoMau />;
}
