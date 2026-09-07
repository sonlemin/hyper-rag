import type { NextConfig } from "next";

// Gốc API nội bộ mà Next chuyển tiếp tới. Trình duyệt chỉ nói chuyện với origin
// của web (`/api/*`), không bao giờ gọi thẳng cổng 8000: cùng origin nên không
// CORS, và địa chỉ API không lộ ra client.
//
// Mặc định `http://api:8000` là tên service trong network compose. Rewrite được
// đóng băng lúc `next build` (nằm trong routes-manifest của bản standalone), nên
// giá trị điều khiển nó là biến lúc **build**: `web/Dockerfile` nhận
// `ARG API_NOI_BO` từ `build.args` của compose. Máy dev đặt
// `API_NOI_BO=http://103.69.194.185:8000` (hoặc tunnel) trước `next dev`.
const API_NOI_BO = (process.env.API_NOI_BO ?? "http://api:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Bản standalone: `web/Dockerfile` chỉ chép `.next/standalone` + `.next/static`.
  output: "standalone",
  // Tắt nút Dev Tools nổi góc dưới trái của `next dev`: nó đè lên nút gập của
  // sidebar (cũng ở góc dưới trái) và chặn click trong bài Playwright.
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_NOI_BO}/:path*` }];
  },
};

export default nextConfig;
