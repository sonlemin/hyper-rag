---
name: Copilot IT
description: Console doanh nghiệp nền sáng cho AI Copilot hỏi đáp tiếng Việt trên kho tri thức IT nội bộ có phân quyền mức hyperedge. Tự dựng theo spine này, không dùng design system ngoài.
status: final
updated: 2026-09-07
sources:
  - ../../prds/prd-hyper_graph_rag-2026-08-29/prd.md
  - ../../prds/prd-hyper_graph_rag-2026-08-29/addendum.md
  - ../../briefs/brief-hyper_graph_rag-2026-08-27/brief.md
  - ../../briefs/brief-hyper_graph_rag-2026-08-27/addendum.md
colors:
  # Nền và bề mặt
  surface-outer: '#DFE4E9'
  surface-app: '#EEF1F4'
  surface-card: '#FFFFFF'
  surface-nav: '#F7F9FB'
  surface-stream: '#FBFCFD'
  # Mực và viền
  ink: '#1B2733'
  ink-muted: '#5A6B7C'
  ink-faint: '#8795A3'
  border: '#D7DEE5'
  border-strong: '#C4CCD4'
  # Xanh thép (màu hành động)
  primary: '#1F5AA8'
  primary-deep: '#16406F'
  primary-tint: '#E3ECF7'
  primary-tint-soft: '#F2F7FD'
  primary-border: '#C9DAEF'
  # Cảnh báo
  danger: '#B3261E'
  danger-bg: '#FBEAE9'
  danger-border: '#E5B5B1'
  # Hai màu ngữ nghĩa mức tiết lộ (L0 là VẮNG MẶT, không có màu, xem Colors)
  level-l2: '#0E7A4E'
  level-l2-bg: '#E5F3EC'
  level-l2-border: '#BFE0D0'
  level-l1: '#9A6700'
  level-l1-bg: '#FFF4D6'
  level-l1-border: '#EAD79A'
  level-l1-ink: '#6B4E00'
  # Slab bôi đen FR-15
  redact-bg: '#2B3947'
  redact-ink: '#F4C84A'
  # Đồ thị
  graph-hover: '#D9A21B'
  graph-hover-halo: '#F4C84A'
  graph-entity-fill: '#EEF1F4'
  graph-entity-border: '#1B2733'
  # Dải màu vòng hyperedge, story 4.6 chọn (mockup chỉ khai hai màu), xem Colors
  graph-ring-1: '#1F5AA8'
  graph-ring-2: '#0E6F76'
  graph-ring-3: '#8C2F6B'
  graph-ring-4: '#7A4419'
  graph-ring-5: '#3D4A57'
  # 5 tầng FR-33, xem Colors trong body
  trust-1: '#5B3E96'
  trust-2: '#7C63AE'
  trust-3: '#9D89C4'
  trust-4: '#BFB1D9'
  trust-5: '#DFD8EC'
typography:
  base:
    fontFamily: '-apple-system, "Segoe UI", Roboto, Arial, sans-serif'
    fontSize: 15px
    lineHeight: '1.55'
  answer-body:
    fontSize: 15.5px
    lineHeight: '1.6'
  question:
    fontSize: 16px
    lineHeight: '1.55'
  heading-block:
    fontSize: 17px
    fontWeight: '700'
  heading-page:
    fontSize: 18px
    fontWeight: '700'
  brand-login:
    fontSize: 26px
    fontWeight: '700'
    letterSpacing: '.3px'
  nav-item:
    fontSize: 14.5px
  meta-chip:
    fontSize: 13.5px
    fontWeight: '600'
  caption-min:
    fontSize: 13px
  mono:
    fontFamily: '"SF Mono", Consolas, "Liberation Mono", Menlo, monospace'
    fontSize: 13.5px
rounded:
  sm: 3px
  md: 4px
  lg: 6px
  xl: 8px
  full: 9999px
spacing:
  topbar-height: 52px
  sidebar-open: 216px
  sidebar-mini: 52px
  drawer-width: 38%
  page-max: 1400px
  pad-content: 20px
  pad-card: 16px
  gap-turn: 16px
components:
  button-primary:
    background: '{colors.primary}'
    foreground: '#FFFFFF'
    radius: '{rounded.md}'
  button-breakglass:
    background: '{colors.level-l1}'
    foreground: '#FFFFFF'
    radius: '{rounded.sm}'
  chip-role:
    background: 'rgba(255,255,255,.13)'
    foreground: '#FFFFFF'
    radius: '{rounded.sm}'
  chip-impersonation:
    background: '{colors.level-l1-bg}'
    border: '{colors.level-l1-border}'
    foreground: '{colors.level-l1-ink}'
    radius: '{rounded.md}'
  chip-grant:
    background: '{colors.level-l2-bg}'
    border: '{colors.level-l2-border}'
    foreground: '{colors.level-l2}'
    radius: '{rounded.md}'
  slab-redact:
    background: '{colors.redact-bg}'
    foreground: '{colors.redact-ink}'
    radius: '{rounded.sm}'
  note-l1:
    background: '{colors.level-l1-bg}'
    border: '{colors.level-l1-border}'
    accent-left: '{colors.level-l1}'
    foreground: '{colors.level-l1-ink}'
    radius: '{rounded.md}'
  badge-level-l2:
    background: '{colors.level-l2-bg}'
    foreground: '{colors.level-l2}'
    radius: '{rounded.sm}'
  badge-level-l1:
    background: '{colors.level-l1-bg}'
    # Chữ trên nền hổ phách dùng level-l1-ink theo luật ở mục Colors; level-l1 trên
    # nền này chỉ đạt 4,44:1, dưới sàn 4.5:1 (đo ở story 4.1, sửa 07/09/2026).
    foreground: '{colors.level-l1-ink}'
    radius: '{rounded.sm}'
  turn-question:
    background: '{colors.primary-tint}'
    border: '{colors.primary-border}'
    radius: '8px 8px 2px 8px'
  turn-answer:
    background: '{colors.surface-card}'
    border: '{colors.border}'
    radius: '8px 8px 8px 2px'
  graph-hyperedge:
    stroke-width: 4px
    fill: 'none'
    label: 'trong lòng vòng tròn, đậm, cùng màu viền'
  graph-entity:
    fill: '{colors.graph-entity-fill}'
    stroke: '{colors.graph-entity-border}'
    radius: '{rounded.full}'
  graph-entity-masked:
    fill: '{colors.graph-entity-fill}'
    stroke: '{colors.graph-entity-border}'
    stroke-style: 'dashed'
    opacity: '0.45'
    label: '•••'
  errbox:
    background: '{colors.danger-bg}'
    border: '{colors.danger-border}'
    accent-left: '{colors.danger}'
    foreground: '{colors.danger}'
    radius: '{rounded.md}'
---

# Copilot IT - Design Spine

Mockup chuẩn: [mockups/mockup-chat-console.html](mockups/mockup-chat-console.html) (v7) cùng 5 màn phụ trong [mockups/](mockups/). Spine thắng khi mâu thuẫn với mockup.

## Brand & Style

Copilot IT [ASSUMPTION tên tạm, chưa chốt visual identity] là console nội bộ cho nhân viên IT và cho buổi bảo vệ khóa luận. Cá tính là "console doanh nghiệp nền sáng": mật độ thông tin cao nhưng chữ đủ lớn, bề mặt trắng trên nền xám xanh nhạt, một màu xanh thép duy nhất cho hành động. Không trang trí, không gradient, không minh họa. Thứ được phép nổi bật là ngữ nghĩa phân quyền: slab bôi đen, hổ phách L1, lục L2. Sản phẩm phải đọc được từ hàng ghế hội đồng qua máy chiếu, nên mọi lựa chọn thị giác ưu tiên tương phản và cỡ chữ hơn sự tinh xảo.

Không dùng design system ngoài. Toàn bộ token trong file này là nguồn duy nhất.

## Colors

- **Xanh thép {colors.primary}** là màu hành động duy nhất: nút chính, liên kết, số trích dẫn [1], viền hyperedge thường, hàng đang hover. Bản đậm {colors.primary-deep} chỉ dùng cho topbar và chữ thương hiệu. Nền nhấn nhẹ {colors.primary-tint} cho item nav đang chọn, bong bóng câu hỏi, hàng cite đang hover.
- **Ba màu mức tiết lộ** là ngữ nghĩa, không phải trang trí:
  - **L2 lục {colors.level-l2}** nghĩa là "đọc đầy đủ": badge L2 trên cite-row, thông báo đã được cấp quyền, nút Duyệt. Không dùng cho tên vai trong meta lượt trả lời.
  - **L1 hổ phách {colors.level-l1}** nghĩa là "biết tồn tại nhưng bị che": badge L1, dòng hạn chế dưới lượt trả lời, chip "Đang xem như", divider đổi vai, nút xin break-glass. Nền {colors.level-l1-bg}, viền {colors.level-l1-border}, chữ trên nền hổ phách {colors.level-l1-ink}.
  - **L0 không có màu hiển thị**, vì L0 là vô hình: không node, không badge, không placeholder, không số đếm, không màu meta riêng. Tên vai trong meta lượt trả lời luôn dùng {colors.ink-muted}, bất kể vai có quyền đầy đủ, bị che hay bị chặn; kết quả phân quyền không bao giờ được mã hóa vào màu meta.
- **Slab bôi đen {colors.redact-bg} / chữ {colors.redact-ink}**: riêng cho vùng bôi đen FR-15 trong câu trả lời. Không dùng cặp màu này cho bất cứ thứ gì khác.
- **Vàng hover đồ thị {colors.graph-hover}** với quầng {colors.graph-hover-halo} ở opacity 30%: chỉ cho vòng hyperedge đang được trích dẫn hover làm sáng.
- **Dải màu vòng hyperedge {colors.graph-ring-1} đến {colors.graph-ring-5}**: màu viền và màu chữ trong vòng, gán theo thứ tự trích dẫn của lượt (vòng của trích dẫn thứ nhất lấy {colors.graph-ring-1}, vòng thứ sáu quay vòng lại). Mockup chỉ khai hai màu vòng nên story 4.6 chọn dải, với ba ràng buộc: mỗi màu đạt tối thiểu 4.5:1 trên nền trắng (6,80 · 5,91 · 7,68 · 7,87 · 9,07), không màu nào trùng {colors.graph-hover} vì vàng chỉ dành cho vòng đang hover, và dải tránh hẳn lục L2, hổ phách L1, đỏ lỗi và tím tin cậy để không màu nào của đồ thị bị đọc thành một mức tiết lộ. {colors.graph-ring-1} cố ý bằng {colors.primary} để khớp mockup. Hover đổi **viền và quầng**, không đổi màu chữ trong vòng: {colors.graph-hover} trên nền trắng chỉ 2,30:1, dưới cả sàn 3:1 cho chỉ báo phi văn bản.
- **Đỏ {colors.danger}**: lỗi hệ thống, badge FAIL, badge số yêu cầu chờ, thông điệp đăng nhập sai. Không dùng cho trạng thái phân quyền, bị che không phải là lỗi.
- **Dải tin cậy {colors.trust-1} đến {colors.trust-5}** [ASSUMPTION hex chưa duyệt]: dải tím từ đậm về nhạt cho 5 tầng nhãn tin cậy FR-33 (spine-only). Tầng 1 đậm nhất vì được thẩm định cao nhất. Dải này cố ý không trùng lục L2, hổ phách L1, xám trung tính và xanh thép, để mức tiết lộ và độ tin cậy không bao giờ bị đọc lẫn.

## Typography

Font hệ thống {typography.base.fontFamily}, không nhúng webfont. Thang chữ (không có chữ nào dưới 13px):

| Vai trò | Token | Dùng cho |
|---|---|---|
| Thương hiệu màn đăng nhập | {typography.brand-login} | Tên sản phẩm trên card đăng nhập |
| Tiêu đề trang | {typography.heading-page} | Tiêu đề màn red-team, modal |
| Tiêu đề khối, breadcrumb đậm | {typography.heading-block} | Header drawer đồ thị, card đăng nhập |
| Câu hỏi người dùng | {typography.question} | Bong bóng câu hỏi |
| Thân câu trả lời | {typography.answer-body} | Nội dung trả lời của Copilot |
| Chữ nền UI | {typography.base} | Mặc định toàn app |
| Nav, cite-row, header nguồn | {typography.nav-item} | Sidebar, danh sách trích dẫn |
| Chip, metadata, chú thích | {typography.meta-chip} | Chip vai, meta lượt, legend |
| Sàn tối thiểu | {typography.caption-min} | Không chữ nào nhỏ hơn mức này |
| Mono | {typography.mono} | Dòng assert red-team, mã kịch bản |

Nhãn trong SVG/canvas đồ thị render tối thiểu 13px thực tế trên màn.

## Layout & Spacing

- Khung nội dung tối đa {spacing.page-max}; phạm vi màn hình và mức cam kết responsive theo Foundation ở EXPERIENCE.md.
- Topbar cao {spacing.topbar-height}, nền {colors.primary-deep}.
- Sidebar hai trạng thái: mở {spacing.sidebar-open}, thu gọn dải icon {spacing.sidebar-mini}.
- Drawer đồ thị mặc định {spacing.drawer-width} chiều ngang vùng main, kéo giãn được bằng grip.
- Đệm nội dung {spacing.pad-content}, đệm card {spacing.pad-card}, khoảng cách giữa các lượt chat {spacing.gap-turn}.

## Elevation & Depth

Bóng đổ tiết chế, chỉ ba mức: card nhẹ (0 4px 16px rgba(27,39,51,.10)), drawer trượt (-12px 0 28px rgba(27,39,51,.18)), modal (0 16px 48px rgba(27,39,51,.3)). Phân tầng chủ yếu bằng nền ({colors.surface-outer} → {colors.surface-app} → {colors.surface-card}) và viền, không bằng bóng.

## Shapes

Góc bo nhỏ, đọc là "công cụ": {rounded.sm} cho chip, badge, slab; {rounded.md} cho nút, input, note; {rounded.lg} cho card, dropdown; {rounded.xl} cho modal và bong bóng chat (bong bóng vát một góc 2px về phía người nói). {rounded.full} chỉ cho avatar và node entity trên đồ thị.

## Components

Spec thị giác; hành vi ở EXPERIENCE.md. Bullet nhóm theo surface, cùng thứ tự với bảng Component Patterns bên EXPERIENCE.

**Khung app**

- **Nút chính** {components.button-primary}: nền xanh thép, chữ trắng.
- **Sidebar**: nền {colors.surface-nav}, viền phải {colors.border}; item đang chọn nền {colors.primary-tint} với vạch phải 3px {colors.primary}; trạng thái thu gọn là dải icon {spacing.sidebar-mini} với ô 38px bo {rounded.lg}.
- **Chip vai** {components.chip-role}: trên topbar, chỉ ghi "Tên · Vai" (ví dụ "Minh · DevOps"). Không bao giờ gắn mức Lx.
- **Chip "Đang xem như"** {components.chip-impersonation}: nền hổ phách nhạt, chữ nâu, nút ✕ nền {colors.level-l1}. Chip vai thật mờ đi bên cạnh.
- **Dropdown "Xem như"**: card {rounded.lg} viền {colors.border-strong} bóng đậm; item hover nền {colors.primary-tint}; mục thoát ở đáy nền {colors.level-l1-bg} chữ {colors.level-l1-ink}.
- **Modal**: card {rounded.xl} rộng 560px, bóng modal, header và footer có viền {colors.border}, footer nền {colors.surface-nav}.
- **Card đăng nhập**: card trắng 400px bo {rounded.lg} trên nền {colors.surface-app}, thương hiệu {typography.brand-login} màu {colors.primary-deep} phía trên.
- **Hộp lỗi** {components.errbox}: viền trái đỏ, icon cảnh báo, chữ đỏ đậm.

**Chat**

- **Bong bóng chat** {components.turn-question} / {components.turn-answer}: câu hỏi lệch phải nền xanh nhạt, trả lời lệch trái nền trắng.
- **Meta lượt trả lời**: dòng "Copilot · trả lời theo quyền [vai] · n trích dẫn" cỡ {typography.caption-min}, tên vai in đậm; màu theo quy tắc ở Colors (một màu cố định cho mọi lượt, kể cả lượt từ chối FR-16); hành vi ở EXPERIENCE.md.
- **Cite-row**: hàng {typography.nav-item}, số thứ tự ô vuông 20px nền {colors.primary} chữ trắng; hover nền {colors.primary-tint}; hàng L1 chữ nghiêng {colors.level-l1} với số nền {colors.level-l1}.
- **Badge mức trên cite-row** {components.badge-level-l2} / {components.badge-level-l1}: nằm cuối hàng nguồn. Nghĩa là mức truy cập của vai hiện tại với nguồn đó.
- **Nhãn tin cậy** (spine-only, FR-33): chip nhỏ {rounded.sm} cạnh loại tài liệu trên cite-row, nền màu tầng {colors.trust-1}..{colors.trust-5}, chữ trắng ở tầng 1-2 và {colors.ink} ở tầng 3-5 (chữ trắng trên {colors.trust-3} chỉ đạt 3.08:1, dưới sàn 4.5:1).
- **Slab bôi đen** {components.slab-redact}: chữ đậm dạng "[nguyên nhân: che]" trên nền tối, inline ngay trong câu.
- **Composer**: ô nhập viền {colors.border-strong} bo {rounded.md} chữ {typography.base}, nút Gửi {components.button-primary}.

**Drawer đồ thị**

- **Drawer đồ thị**: nền {colors.surface-card}, viền trái {colors.border-strong}, bóng trượt; grip kéo giãn 12px nền {colors.surface-app} với ba chấm {colors.ink-faint}; legend và ghi chú hover ở đáy cỡ {typography.caption-min}.
- **Đồ thị kiểu paper HyperGraphRAG** (xem mockups/mockup-chat-console.html trạng thái B; kiểu vẽ tiếp nhận từ imports/ref-knowledge-hypergraph.png, ghi nhận ở reconcile-ref-knowledge-hypergraph.md):
  - **Vòng hyperedge**: vòng tròn lớn rỗng ruột {components.graph-hyperedge}, viền dày màu riêng từng hyperedge, tên viết bên trong cùng màu viền.
  - **Mũi tên**: tỏa từ mép vòng đến entity.
  - **Entity**: node tròn nhỏ {components.graph-entity}, nhãn đậm bên ngoài có halo trắng.
  - **Nhãn vai slot**: 13px màu {colors.ink-muted} đặt dọc mũi tên (không dùng {colors.ink-faint} vì dưới sàn tương phản 4.5:1).
  - **Đỉnh L1 mờ**: {components.graph-entity-masked} với mũi tên nét đứt mờ.

**Break-glass**

- **Nút xin break-glass** {components.button-breakglass}: nền hổ phách đậm, chữ trắng, luôn nằm trong dòng note-l1 hoặc footer modal.
- **Dòng hạn chế L1** {components.note-l1}: một dòng dưới lượt trả lời, viền trái hổ phách, icon khóa, chứa nút xin break-glass. Khung này giữ nguyên qua trạng thái chờ duyệt và đã cấp, chỉ đổi nội dung.
- **Card yêu cầu break-glass (hàng chờ owner)**: card nền {colors.surface-card} viền {colors.border} bo {rounded.md} đệm {spacing.pad-card}; tiêu đề "Yêu cầu break-glass #[mã]" đậm với thời gian tương đối {colors.ink-faint} bên phải; dòng phạm vi (ai xin, hyperedge, k, thời hạn, lý do) màu {colors.ink-muted}; hai nút bo {rounded.sm}: Duyệt nền {colors.level-l2} chữ trắng, Từ chối viền {colors.border-strong} chữ {colors.ink-muted}.
- **Chip quyền tạm** {components.chip-grant}: nền lục nhạt, hiện tên hyperedge được cấp và đồng hồ đếm ngược.

**Red-team**

- **Badge kết quả red-team**: PASS dùng cặp {colors.level-l2-bg}/{colors.level-l2}, FAIL dùng {colors.danger-bg}/{colors.danger}, đang chạy dùng {colors.primary-tint}/{colors.primary}, chờ lượt dùng {colors.surface-app}/{colors.ink-faint}.
- **Bảng red-team**: bảng trên nền {colors.surface-card}, viền hàng {colors.border}; mỗi hàng gồm mã kịch bản (đậm), tên, vai chạy, thời gian chạy {colors.ink-muted} và badge kết quả ở cuối; caret ▸ đầu hàng mở phần chi tiết nền {colors.surface-nav} chứa câu hỏi và dòng assert bằng {typography.mono}.

**Demo offline**

- **Toggle live/offline**: hai nấc chữ {typography.meta-chip}; nấc live đang bật dùng {colors.level-l2-bg}/{colors.level-l2}, nấc offline đang bật dùng {colors.surface-app}/{colors.ink-muted}.
- **Nút câu hỏi offline**: khối {rounded.md} nền {colors.primary-tint-soft} viền {colors.primary-border} chữ {colors.primary-deep}, số thứ tự vuông như cite-row; hover nền {colors.primary-tint}.

## Do's and Don'ts

Checklist tra nhanh; nguồn chuẩn là các section ở trên.

| Nên | Không |
|---|---|
| Chip vai chỉ ghi tên vai; mức chỉ hiện gắn với nội dung cụ thể (badge trên nguồn, tooltip node) | Gắn mức Lx cố định lên chip vai, dropdown vai hay tên vai ở bất cứ đâu |
| Tên vai trong meta lượt trả lời luôn một màu {colors.ink-muted}, mọi lượt | Mã hóa kết quả phân quyền vào màu meta vai - hai ca từ chối FR-16 phải giống nhau từng pixel |
| Dải tin cậy dùng riêng dải tím {colors.trust-1}..{colors.trust-5} | Dùng lục, hổ phách, xám trung tính hay xanh thép cho nhãn tin cậy, hai hệ màu không được lẫn |
| L0 thể hiện bằng vắng mặt hoàn toàn, mọi bề mặt | Vẽ node xám, ô khóa hay bất kỳ dấu vết nào cho nội dung L0 |
| Cặp {colors.redact-bg}/{colors.redact-ink} chỉ cho slab bôi đen | Dùng nền tối chữ vàng cho thành phần khác |
| Đỏ chỉ cho lỗi hệ thống và FAIL | Dùng đỏ cho trạng thái bị che, bị che không phải lỗi |
| Dash thường hoặc dấu phẩy trong mọi microcopy | Em dash trong microcopy (quy ước dự án) |
| Vàng {colors.graph-hover} chỉ cho hyperedge đang được hover từ trích dẫn | Dùng vàng hover làm màu viền cố định của hyperedge |
| Chữ tối thiểu 13px, kể cả nhãn đồ thị | Chữ dưới 13px ở bất cứ đâu |
