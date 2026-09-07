import { NextResponse, type NextRequest } from "next/server";

// Proxy (tên Next 16 của middleware) chạy trước render, chỉ cho một đường:
// trang mẫu `/mau` là dev-only, ở production trả thẳng 404 với thân rỗng.
// Vì sao không dựa vào `notFound()` trong page: nó ném sau khi shell HTML đã
// stream nên mã HTTP giữ 200 (đo trên máy chủ 07/09/2026). Matcher là hằng để
// Next phân tích tĩnh lúc build; mọi route khác không đi qua đây.
export function proxy(_request: NextRequest) {
  if (process.env.NODE_ENV === "production") {
    return new NextResponse(null, { status: 404 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/mau",
};
