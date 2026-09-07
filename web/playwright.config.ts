import { defineConfig, devices } from "@playwright/test";

// Lưới test trình duyệt của `web/` (story 4.1). Chạy trên máy dev bằng
// `npm run test:e2e`; **không** vào `uv run pytest` (máy chủ CI không có node).
// `webServer` là `next dev`; mọi `/api/**` chưa mock bị chặn ở `beforeEach`
// của spec, trừ ca health thật (chạy khi đặt `API_NOI_BO` trỏ máy chủ).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    // Máy dev dùng lại server đang chạy; CI luôn dựng server mới của chính nó.
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
