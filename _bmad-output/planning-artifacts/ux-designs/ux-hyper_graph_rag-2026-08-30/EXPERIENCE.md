---
name: Copilot IT
status: final
updated: 2026-08-30
sources:
  - ../../prds/prd-hyper_graph_rag-2026-08-29/prd.md
  - ../../prds/prd-hyper_graph_rag-2026-08-29/addendum.md
  - ../../briefs/brief-hyper_graph_rag-2026-08-27/brief.md
  - ../../briefs/brief-hyper_graph_rag-2026-08-27/addendum.md
---

# Copilot IT - Experience Spine

Nhận diện thị giác và token màu/chữ ở `DESIGN.md`. Mockup tham chiếu trong [mockups/](mockups/). Spine thắng khi mâu thuẫn với mockup.

## Foundation

- **Form-factor**: web desktop, khung nội dung tối đa {spacing.page-max} (dựng cho màn 1400-1500px). Bối cảnh trình chiếu là máy chiếu hội trường ngày bảo vệ, nên mọi bề mặt phải đọc được từ xa. Không cam kết responsive/mobile.
- **UI system**: không dùng design system ngoài, tự dựng theo DESIGN.md.
- **Stack**: Next.js/React; đồ thị bằng Cytoscape.js, thêm plugin khi cần cho kiểu vẽ paper HyperGraphRAG (vòng tròn hyperedge, mũi tên tỏa entity; kiểu vẽ tiếp nhận từ [imports/ref-knowledge-hypergraph.png](imports/ref-knowledge-hypergraph.png), chi tiết ở DESIGN.md Components).
- **Nguyên tắc nền**: UI chỉ hiển thị dữ liệu đã lọc quyền từ tầng truy hồi (FR-12). Slab bôi đen và node mờ là cách hiển thị phần đã che, không phải cơ chế che; không endpoint nào trả slot thô rồi che bằng giao diện.

## Hiển thị theo quyền

Bảng ngữ nghĩa L0/L1/L2 trên từng bề mặt. Quy tắc gốc: mức là thuộc tính của cặp (vai hiện tại, nội dung) theo bảng chính sách, không phải của vai. L0 vô hình ở MỌI bề mặt và không để lại dấu vết nào phân biệt được với "không có dữ liệu".

| Bề mặt | L2 | L1 | L0 |
|---|---|---|---|
| Thân câu trả lời | Đầy đủ | Slab "[slot: che]" inline đúng vị trí + dòng hạn chế dưới lượt | Không xuất hiện; nếu toàn bộ ngữ cảnh bị chặn thì render template từ chối duy nhất (FR-16) |
| Danh sách trích dẫn | Cite-row đầy đủ, badge L2 | Cite-row nghiêng hổ phách "một phần bị hạn chế", badge L1 | Không có hàng nào |
| Số đếm ("n trích dẫn") | Đếm | Đếm | Không đếm |
| Đồ thị | Node và nhãn bình thường | Node mờ 45%, nét đứt, KHÔNG hiện tên (nhãn ngoài thay bằng "•••"), mũi tên nét đứt; hover mới hiện tooltip "Cần quyền L2" | Không vẽ node; hyperedge mà mọi đỉnh ngoài quyền thì không vẽ cả vòng |
| Tên hyperedge trên đồ thị | Hiện | Tên node cấu trúc cũng đi qua tầng che FR-12 (tên có thể chính là nội dung nhạy cảm) | Không vẽ |
| Break-glass | Không cần | Placeholder/dòng hạn chế là điểm xin duy nhất | Không có kênh xin |

Định nghĩa nhãn mức trên cite-row: badge Lx = mức truy cập của VAI HIỆN TẠI với nguồn đó. Không được đọc là "câu trả lời này đang ở mức Lx". Tooltip nhắc lại định nghĩa này.

Slot "người phụ trách" luôn hiện ở mức vai/nhóm ("nhóm DevOps"), không tên cá nhân, trên cả chat lẫn đồ thị (FR-10, FR-14).

## Information Architecture

Các surface có mockup, cam kết trên đường demo:

| Surface | Vào từ | Mục đích | Mockup |
|---|---|---|---|
| Đăng nhập (FR-17) | URL gốc | JWT, vai gắn tài khoản; không đăng ký, không quên mật khẩu | [screen-login.html](mockups/screen-login.html) |
| Chat chính (FR-13/14/15/16) | Sidebar "Hỏi đáp" | Hỏi đáp tiếng Việt, trích dẫn co giãn theo quyền, slab bôi đen | [mockup-chat-console.html](mockups/mockup-chat-console.html) |
| Drawer đồ thị (FR-19) | Nút "Đồ thị" hoặc bấm trích dẫn | Hypergraph của lượt trả lời mới nhất, theo quyền của vai đang xem, hover từ trích dẫn | [mockup-chat-console.html](mockups/mockup-chat-console.html) trạng thái B |
| Bộ chọn vai "xem như" (FR-18) | Nút "⇄ Xem như" trên topbar | Đổi vai trong phiên, chỉ tài khoản demo/admin | [screen-role-switcher.html](mockups/screen-role-switcher.html) |
| Break-glass phía người xin (FR-20) | Nút trên dòng hạn chế L1 | Modal xin, trạng thái chờ, trạng thái đã cấp | [screen-breakglass-requester.html](mockups/screen-breakglass-requester.html) |
| Hàng chờ duyệt của owner (FR-20) | Sidebar "Break-glass" của Trưởng nhóm | Duyệt hoặc từ chối yêu cầu; owner cấp chủ động được | [mockup-chat-console.html](mockups/mockup-chat-console.html) màn phụ cuối |
| Kiểm thử bảo mật (FR-21) | Sidebar "Kiểm thử bảo mật" | Chạy red-team live, bảng PASS/FAIL RT-01..RT-05 | [screen-redteam.html](mockups/screen-redteam.html) |
| Toggle demo live/offline (FR-29) | Thanh đầu khung chat | Chuyển live sang cache offline khi mất mạng | [screen-demo-mode.html](mockups/screen-demo-mode.html) |

Surface spine-only (chỉ đặc tả trong spine, xây sau M2 hoặc vào chương 4 dạng thiết kế, theo thứ tự cắt PRD):

| Surface | FR | Ghi chú spine |
|---|---|---|
| So sánh 2 cột | FR-18 (S) | Cùng câu hỏi, hai vai cạnh nhau; chi tiết chọn vai và cuộn đồng bộ chưa đặc tả |
| Bảng chính sách | FR-22 (S) | Bảng nhóm quyền × loại nội dung → L0/L1/L2, admin chỉnh ngoại lệ; nơi chứng minh chính sách là dữ liệu cấu hình |
| Nhật ký kiểm toán | FR-23 (màn hiển thị C) | Ghi là MUST ở backend; màn hiển thị cắt được |
| Quản lý người dùng | FR-24 (C) | Danh sách, tạo, gán vai, tối giản |
| Tình trạng hệ thống | FR-25 (C) | 4 phụ thuộc ngoài, số hyperedge/entity/tài liệu, chi phí LLM lũy kế, thời gian truy vấn trung bình |
| Nhãn tin cậy 5 tầng | FR-33 (C) | Xem section riêng bên dưới, không cam kết build |

Sidebar là điều hướng duy nhất giữa surface, hai trạng thái (mở / dải icon). Modal chỉ một lớp.

## Voice and Tone

Tiếng Việt toàn bộ. Giọng ngắn, mô tả sự thật, không rào đón, không emoji trong nội dung trả lời (icon trạng thái ⏳ ✔ 🔒 được phép trong note). Quy ước dự án áp cho mọi microcopy: không em dash, không "không chỉ... mà còn...", từ đơn giản, hạn chế dấu hai chấm giữa câu.

Microcopy chuẩn:

| Ngữ cảnh | Câu chữ |
|---|---|
| Placeholder L1 trong trích dẫn | "còn một phần bị hạn chế, liên hệ [nhóm chịu trách nhiệm]" (luôn mức vai/nhóm, không tên cá nhân) |
| Slab bôi đen trong câu | "[nguyên nhân: che]", "[hành động khắc phục: che]", dạng chung "[tên slot: che]" |
| Dòng hạn chế L1 | "Còn n phần bị hạn chế (tên các slot) - liên hệ nhóm X" + nút "Xin truy cập khẩn cấp" |
| Template từ chối duy nhất (FR-16) | "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi này." (chốt ở story 3.5, `docs/adr/ADR-015-wording-template-tu-choi-fr-16.md`; hằng `api.hoi_dap.TEMPLATE_TU_CHOI`) - dùng chung cho ca không có đáp án và ca L0, không kèm trích dẫn, không placeholder, không gợi ý break-glass |
| Đang truy vấn | "Đang truy vấn..." kèm chỉ báo ba chấm trong bong bóng trả lời |
| Empty-state drawer đồ thị | "Chưa có dữ liệu đồ thị cho lượt trả lời này" (một chuỗi duy nhất cho mọi lý do trống) |
| Hàng chờ owner trống | "Không có yêu cầu nào đang chờ" |
| Phiên hết hạn | "Phiên làm việc đã hết hạn, đăng nhập lại để tiếp tục" |
| Tooltip node mờ trên đồ thị | "Cần quyền L2" (chỉ báo mức, không mời bấm) |
| Tooltip badge mức trên cite-row | "Mức truy cập của vai hiện tại với nguồn này" |
| Chip đang mượn vai | "Đang xem như: [Tên vai]" + ✕ |
| Divider đổi vai trong chat | "Đã đổi sang xem như [vai] · câu hỏi giữ nguyên" |
| Trạng thái chờ break-glass | "Đã gửi yêu cầu #[mã], đang chờ nhóm [X] duyệt" |
| Trạng thái đã cấp | "Đã được cấp quyền L2 với '[tên hyperedge]' · còn [mm:ss]" + nút "Hỏi lại câu này" |
| Lỗi đăng nhập | "Sai tài khoản hoặc mật khẩu" (gộp chung, không nói rõ trường nào sai, chống dò tài khoản) |
| Banner offline | "Chế độ offline - chọn câu hỏi từ danh sách, trả lời lấy từ cache đã dựng sẵn" |

Thuật ngữ giữ nguyên theo PRD 1.6: phân biệt "vai người dùng" (5 vai) và "vai slot" (8 slot) trong mọi nhãn; "RAG dựa trên đồ thị", không dùng "GraphRAG".

## Component Patterns

Hành vi; spec thị giác ở DESIGN.md, mục Components.

| Component | Hành vi |
|---|---|
| Sidebar | Toggle giữa mở ({spacing.sidebar-open}) và dải icon ({spacing.sidebar-mini}) kiểu VS Code, nhớ trạng thái trong phiên. Icon Break-glass mang badge số: đỏ khi có yêu cầu chờ (phía owner), hổ phách khi chính người dùng đang chờ duyệt, lục khi đang giữ quyền tạm. |
| Drawer đồ thị | Mặc định ĐÓNG, chat chiếm toàn màn. Mở bằng nút "Đồ thị" trên header chat hoặc bấm vào số trích dẫn [n]. Trượt ra từ phải, rộng mặc định {spacing.drawer-width}, kéo giãn bằng grip trái, đóng bằng ✕. Hiển thị hyperedge của lượt trả lời mới nhất, render theo quyền của vai đang xem; re-render ngay khi đổi vai và khi có lượt trả lời mới. |
| Meta lượt trả lời | Dòng "Copilot · trả lời theo quyền [vai] · n trích dẫn". Tên vai luôn một màu cố định ({colors.ink-muted}), bất kể vai có quyền đầy đủ, bị che hay bị chặn. Lượt từ chối FR-16 bỏ vế "· n trích dẫn"; hai ca từ chối (không có đáp án, L0) giống nhau từng pixel. |
| Divider đổi vai | Mỗi lần đổi vai chèn một divider "Đã đổi sang xem như [vai] · câu hỏi giữ nguyên". Lịch sử chat giữ nguyên qua mọi lần đổi, các lượt cũ giữ nguyên trên màn; an toàn vì xem như chỉ có ở tài khoản demo/admin. |
| Hover trích dẫn (FR-19 MUST) | Khi drawer đang mở, hover số [n] hoặc cite-row làm vòng hyperedge tương ứng sáng viền {colors.graph-hover} kèm quầng; cite-row hiện chú thích "→ đang sáng HE-xx". Rời hover thì trả về màu thường. |
| Khối nguồn | Lượt trả lời MỚI NHẤT luôn mở danh sách trích dẫn; lượt cũ tự thu gọn thành "Nguồn (n) ▸", bấm để mở lại. |
| Cite-row | Hàng nguồn gồm số, tên nguồn, loại tài liệu, badge mức của vai hiện tại với nguồn. Nguồn L1 in nghiêng hổ phách kèm chữ "một phần bị hạn chế". Bấm số mở drawer và focus hyperedge. |
| Slab bôi đen + dòng hành động | Slab inline hiện MẶC ĐỊNH ngay trong câu (FR-15 MUST, không thêm cú bấm); ngay dưới lượt là dòng hạn chế L1 gom danh sách phần bị che và nút "Xin truy cập khẩn cấp". Muốn đổi hình thức bôi đen phải sửa FR-15 trước. |
| Chip "Đang xem như" | Xuất hiện trên topbar suốt phiên mượn vai, chip vai thật mờ bên cạnh; ✕ thoát về vai thật. Người dùng phải luôn biết mình đang mượn vai. |
| Dropdown "Xem như" | Liệt kê đủ 5 vai (DevOps, Tech Support, Sale/BA, Trưởng nhóm, Admin) kèm một dòng mô tả vùng quyền bằng lời, vai đang giả có dấu ✓, mục "Thoát xem như" tách riêng ở đáy. Chỉ tài khoản đánh dấu demo/admin thấy nút; tài khoản thường không thấy và API cũng từ chối. Mọi lần đổi vai ghi nhật ký kèm cả tài khoản thật lẫn vai giả. |
| Toggle live/offline | Hai nấc trên thanh đầu khung chat. Sang offline: banner mỏng xuất hiện, ô nhập tự do bị THAY HẲN bằng danh sách câu cố định (không phải disable). Về live: composer trở lại. |
| Composer | Ô nhập tự do + nút Gửi, chỉ ở chế độ live. |
| Danh sách câu cố định offline | Mỗi câu là một nút bấm-để-hỏi kèm tag kịch bản; không có đường gõ tự do (lý do ở mục Chế độ demo). Cache dựng theo cặp (câu hỏi, vai) nên "xem như" vẫn hoạt động. |
| Modal xin break-glass | Mở từ nút trên dòng hạn chế L1 (điểm khởi phát DUY NHẤT, FR-20; nội dung L0 vô hình nên không có kênh xin). Phạm vi k=0 và thời hạn 60 phút khóa sẵn, chỉ ô lý do bắt buộc điền. Gửi xong ghi nhật ký. M3 chốt mức sàn MUST k=0; k=1 (mặc định trong PRD) và cho chọn thời hạn thuộc phần SHOULD, ngoài phạm vi spine này. |
| Hàng chờ owner | Card yêu cầu ghi ai xin (kèm tài khoản thật nếu đang xem như), hyperedge, phạm vi k, thời hạn, lý do; hai nút Duyệt / Từ chối. Trống thì hiện "Không có yêu cầu nào đang chờ". |
| Chip quyền tạm | Hiện trên topbar khi grant break-glass đang hiệu lực với vai hiện tại (xem State Patterns "Grant qua đổi vai"), ghi tên hyperedge và đếm ngược mm:ss, theo người dùng sang mọi surface. Hết hạn chip biến mất. |
| Bảng red-team | Nút "Chạy toàn bộ" chạy lại bộ RT tại chỗ; từng hàng có badge PASS/FAIL/đang chạy/chờ lượt và thời gian chạy; bấm ▸ mở chi tiết vai chạy test, câu hỏi, dòng assert trên ngữ cảnh truy hồi. Kết quả ghi nhật ký kèm thời điểm. |

## Chế độ demo

- **Live là mặc định** (FR-29): hội đồng gõ câu tự do được, 5-10 câu mồi chỉ là gợi ý. Chip "● Demo live" và "Cache offline sẵn sàng" trên thanh đầu chat.
- **Offline là fallback khi mất mạng**: luật riêng là "chọn từ danh sách cố định, không gõ tự do", vì cache tra theo chuỗi, lệch một ký tự là trượt. Toàn bộ đường demo 4 nhịp chạy được offline (NFR-07), gồm cả nhịp 3 Sale/BA bị chặn (bắt buộc có trong bộ cache) và đổi vai xem như.
- [ASSUMPTION] Chỉ tài khoản đánh dấu demo/admin thấy toggle (đề xuất dùng cùng cờ với nút "xem như" FR-18); tài liệu chưa đặc tả ai bật.
- Câu chữ của danh sách câu cố định sẽ chốt khi dựng bộ cache T8; danh sách trong mockup là minh họa từ corpus 3 kịch bản.

## State Patterns

| Trạng thái | Bề mặt | Xử lý |
|---|---|---|
| Chat trống lần đầu | Chat | Chỉ composer với placeholder "Đặt câu hỏi về kho tri thức IT...", không màn chào riêng |
| Đang truy vấn | Chat | Chỉ báo ba chấm trong bong bóng trả lời tại vị trí lượt sắp tới, kèm chuỗi theo bảng Voice and Tone. Không stream ở M3, câu trả lời hiện trọn một lần (giữ assert trên ngữ cảnh truy hồi trọn vẹn). Không đặt timeout cứng phía UI (NFR-08 không đặt SLA); lỗi backend thì thay bằng hộp lỗi đỏ |
| A. Phiên vai thật | Chat | Chip "Tên · Vai", mọi lượt theo quyền vai thật; không lẫn lượt của vai khác |
| B. Đang xem như, có L1 | Chat | Chip "Đang xem như", divider đổi vai, lượt mới có slab + dòng hạn chế; các lượt cũ trước divider giữ nguyên trên màn; drawer nếu mở thì re-render ngay theo vai đang xem |
| C. Vai bị chặn (L0) | Chat | Template từ chối duy nhất, không trích dẫn, không placeholder, không dấu vết; meta không có vế "· n trích dẫn", tên vai màu meta cố định; lịch sử và divider đổi vai giữ nguyên trên màn; nút Đồ thị vẫn hiện, drawer dùng empty-state trung tính duy nhất |
| Drawer đồ thị trống | Drawer đồ thị | Một empty-state trung tính duy nhất (chuỗi theo bảng Voice and Tone), dùng chung cho mọi lý do trống (chưa có lượt trả lời, lượt không có hyperedge, toàn bộ hyperedge ngoài quyền); không phân biệt được các lý do, chống kênh dò |
| Break-glass 1: đang xin | Modal | k=0, 60 phút khóa sẵn, lý do bắt buộc |
| Break-glass 2: chờ duyệt | Chat + sidebar | Dòng hạn chế đổi nội dung tại chỗ thành chuỗi trạng thái chờ (theo bảng Voice and Tone) + nút Hủy yêu cầu; badge hổ phách trên icon Break-glass để tìm lại khi lượt đã cuộn khuất. Không thông báo đẩy (ngoài phạm vi), cập nhật khi tải lại hoặc qua polling |
| Break-glass 3: đã cấp | Chat + topbar | KHÔNG tự viết lại câu trả lời cũ (NFR-09, quyền hiệu lực ở truy vấn kế tiếp); dòng lục trạng thái đã cấp (chuỗi theo bảng Voice and Tone) + nút "Hỏi lại câu này" tạo lượt mới; chip đếm ngược 60 phút trên topbar theo mọi surface |
| Break-glass hết hạn | Toàn app | Quyền tự thu về mức cũ, chip biến mất, lượt trả lời kế tiếp quay lại có slab và dòng hạn chế |
| Grant qua đổi vai | Toàn app | Grant gắn với (tài khoản thật, vai tại thời điểm xin), chỉ hiệu lực khi đang ở đúng vai đã xin. Thoát xem như thì grant ngủ, chip đếm ngược ẩn; quay lại vai đó trong hạn thì grant dùng tiếp, chip hiện lại với thời gian còn lại; hết 60 phút thu về dù đang ở vai nào. Vai đang xem vốn đã L2 thì grant không đổi gì. Nhật ký ghi cả tài khoản thật lẫn vai giả (FR-23) |
| Hàng chờ owner | Break-glass owner | Card yêu cầu + Duyệt/Từ chối; owner cấp chủ động được từ màn của mình; trống thì hiện chuỗi theo bảng Voice and Tone |
| Red-team đang chạy | Kiểm thử bảo mật | Hàng đang chạy có spinner, hàng chưa tới ghi "chờ lượt"; bảng cập nhật từng hàng để hội đồng thấy chạy thật |
| Red-team PASS/FAIL | Kiểm thử bảo mật | Badge lục PASS / đỏ FAIL từng kịch bản + ô tổng n/5; đích trình diễn là 5/5 PASS |
| Lỗi đăng nhập | Đăng nhập | Một thông điệp gộp (chuỗi theo bảng Voice and Tone), cả hai ô viền đỏ, ô mật khẩu được xóa trống |
| Phiên JWT hết hạn | Toàn app | Về màn đăng nhập với thông báo trung tính (chuỗi theo bảng Voice and Tone). Không dùng hộp lỗi đỏ; hết phiên không phải lỗi hệ thống, không được lẫn với fail-closed (NFR-10) |
| Fail-closed (NFR-10) | Chat | Truy vấn thiếu ngữ cảnh quyền bị từ chối bằng LỖI HỆ THỐNG nhìn thấy được (hộp lỗi đỏ), khác hẳn template từ chối; không bao giờ trả lời như thể tầng lọc quyền không tồn tại |
| Offline | Chat | Banner + danh sách câu cố định thay composer |

## Interaction Primitives

Demo trên máy chiếu nên chuột là chính, target lớn, hover là tương tác lõi.

- **Hover** số trích dẫn / cite-row: sáng hyperedge (khi drawer mở). Hover node mờ: tooltip "Cần quyền L2".
- **Click** số trích dẫn: mở drawer + focus hyperedge. Click "Nguồn (n) ▸": mở danh sách. Click placeholder/nút trên dòng hạn chế: mở modal break-glass.
- **Double-click** entity trên đồ thị: mở rộng lân cận (FR-19 SHOULD).
- **Drag** grip drawer: kéo giãn độ rộng. Drag nền đồ thị: pan.
- **Phím tắt**: ⌘K focus ô hỏi. Esc đóng modal và dropdown.
- **Cấm**: hover-only cho thông tin bắt buộc (slab và dòng hạn chế hiện mặc định, không nấp sau hover); modal chồng modal; thao tác chỉ làm được bằng phím.

## Accessibility Floor

Sàn tối thiểu cho bối cảnh demo hội trường và người dùng nội bộ:

- Đọc được từ khoảng 5m khi chiếu: thân chữ {typography.answer-body}, không chữ nào dưới 13px, kể cả nhãn đồ thị.
- Không dựa màu đơn lẻ cho trạng thái che: slab có chữ "[slot: che]", node mờ có nét đứt + nhãn "•••" + tooltip, nguồn hạn chế có chữ "một phần bị hạn chế" bên cạnh badge. Người mù màu vẫn phân biệt được che/không che bằng hình và chữ.
- Lỗi có icon + chữ, không chỉ viền đỏ.
- Tương phản: chữ trắng trên {colors.primary-deep}, {colors.redact-ink} trên {colors.redact-bg}, {colors.level-l1-ink} trên {colors.level-l1-bg} giữ tối thiểu 4.5:1.
- Focus bàn phím nhìn thấy được trên input và nút (viền {colors.primary}).

## Key Flows

### Flow 1 - Demo 4 nhịp 90 giây (Minh, người trình bày, trước hội đồng)

1. Minh đăng nhập tài khoản demo, vai thật DevOps, màn chat sạch, chip "● Demo live". Một tab thứ hai đã đăng nhập sẵn tài khoản Trưởng nhóm, chuẩn bị cho đường duyệt ở nhịp 4.
2. **Nhịp 1**: Minh hỏi "App01 sập ngày 12/08 vì nguyên nhân gì, đã khắc phục thế nào?". Trả lời đầy đủ theo quyền DevOps, 3 trích dẫn. Minh bấm [1] mở drawer đồ thị, hover trích dẫn, vòng HE-01 sáng vàng trước hội đồng.
3. **Nhịp 2 (climax)**: không gõ lại câu hỏi, Minh bấm "⇄ Xem như", chọn Tech Support, hỏi lại cùng câu. Câu trả lời mới hiện ra và giữa câu là hai slab đen "[nguyên nhân: che]", "[hành động khắc phục: che]" đập vào mắt hội đồng, kèm dòng "Còn 2 phần bị hạn chế - liên hệ nhóm DevOps". Trên đồ thị đỉnh nguyên nhân mờ thành "•••", đỉnh hành động khắc phục biến mất. Cùng một sự thật, hai vai, hai câu trả lời, ngay trên một màn hình.
4. **Nhịp 3**: đổi sang Sale/BA, hỏi lại. Chỉ một dòng "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi này." Không trích dẫn, không dấu vết, không phân biệt được với chuyện dữ liệu không tồn tại.
5. **Nhịp 4**: quay về xem như Tech Support, bấm "Xin truy cập khẩn cấp" trên dòng hạn chế của nhịp 2 (dòng này vẫn còn trên màn vì lịch sử giữ nguyên qua đổi vai), điền lý do, gửi. Đường duyệt: Minh chuyển sang tab thứ hai đang đăng nhập Trưởng nhóm, mở hàng chờ, bấm Duyệt rồi quay lại tab chính; dùng cơ chế duyệt thật, chấp nhận thêm khoảng 10 giây. Chip lục "L2 tạm · 58:12" hiện trên topbar, Minh bấm "Hỏi lại câu này", lượt mới đọc được nguyên nhân. Minh nói với hội đồng rằng quyền này tự hết hạn sau 60 phút.
6. Ngay sau đó Minh mở màn Kiểm thử bảo mật, bấm "Chạy toàn bộ", bảng RT-01..RT-05 chạy live lên 5/5 PASS.

Đường lùi: mạng hỏng giữa buổi thì Minh gạt toggle sang Offline, banner hiện, danh sách câu cố định thay ô nhập, cả 4 nhịp đi tiếp bằng cache (câu hỏi, vai). Hỏng nữa thì video dự phòng.

### Flow 2 - Break-glass trọn vẹn (Lan, Tech Support tuyến 1)

1. Khách VIP hỏi nguyên nhân sự cố App01 qua ticket #4512. Lan (vai thật Tech Support) hỏi Copilot và nhận câu trả lời có slab "[nguyên nhân: che]".
2. Lan bấm "Xin truy cập khẩn cấp" trên dòng hạn chế. Modal mở, phạm vi "Sự cố App01 12/08, k=0" và hạn 60 phút khóa sẵn, Lan chỉ điền lý do "Khách VIP đang hỏi, cần biết nguyên nhân để trả lời ticket #4512" rồi gửi.
3. Dòng hạn chế đổi thành "Đã gửi yêu cầu #BG-07, đang chờ nhóm DevOps duyệt", icon Break-glass ở sidebar mang badge hổ phách.
4. Tuấn, Trưởng nhóm DevOps, thấy badge đỏ trên màn của mình, mở hàng chờ, đọc lý do và phạm vi k=0, bấm Duyệt.
5. **Climax**: bên màn Lan, dòng chờ đổi thành thông báo lục "Đã được cấp quyền L2 với 'Sự cố App01 12/08' · còn 59:41" và chip đếm ngược hiện trên topbar. Câu trả lời cũ vẫn nguyên slab; Lan bấm "Hỏi lại câu này" và lượt trả lời mới hiện đầy đủ nguyên nhân. Lan trả lời khách trong hạn 60 phút.
6. Hết hạn: chip biến mất, quyền thu về, câu hỏi tiếp theo về App01 lại có slab như cũ. Toàn bộ 6 bước đều nằm trong nhật ký kiểm toán.

Đường lùi: Tuấn từ chối thì dòng chờ đổi thành thông báo từ chối kèm lý do, và gợi ý liên hệ trực tiếp nhóm DevOps; Lan hủy được yêu cầu khi còn đang chờ.

## Nhãn tin cậy 5 tầng (spine-only, FR-33)

Bảng 5 tầng đã duyệt. Tầng đo độ thẩm định của NGUỒN, độc lập hoàn toàn với mức tiết lộ L0/L1/L2. Màu dùng dải riêng {colors.trust-1}..{colors.trust-5}, không trùng màu mức. Không cam kết build; đứng đầu danh sách cắt T5-T6, không kịp thì vào chương 4 dạng thiết kế.

| Tầng | Tên | Loại tài liệu | Màu |
|---|---|---|---|
| 1 | Chuẩn hóa | SOP, runbook | {colors.trust-1} |
| 2 | Đã thẩm định | postmortem, CMDB | {colors.trust-2} |
| 3 | Ghi nhận nghiệp vụ | lịch sử sự cố, vòng đời ticket, Known Issue | {colors.trust-3} |
| 4 | Biên soạn tham khảo | FAQ, troubleshooting, tài liệu sản phẩm | {colors.trust-4} |
| 5 | Máy sinh | log, cảnh báo | {colors.trust-5} |

Vị trí dự kiến: chip nhỏ cạnh loại tài liệu trên cite-row. Một nguồn L1 vẫn có nhãn tin cậy bình thường; nguồn L0 không xuất hiện nên không có nhãn.

## Khám phá đồ thị mở rộng (FR-19 SHOULD)

Phần MUST giữ đến cùng là hover trích dẫn làm sáng hyperedge. Phần SHOULD gồm ba mục dưới đây, vẫn nằm cuối thứ tự cắt PRD (bị cắt trước phần hover):

1. **Zoom/pan** vùng đồ thị (nút +/− và kéo chuột).
2. **Mở rộng lân cận một đỉnh**: bấm đúp một entity tải thêm các hyperedge lân cận QUA GRAPH STORE ĐÃ LỌC QUYỀN; kết quả trả về vẫn tuân bảng Hiển thị theo quyền (đỉnh L0 của hyperedge mới không về tới client).
3. **Lọc theo loại node**: bật tắt hiển thị theo loại (hyperedge, entity, theo vai slot).

## Open Questions

1. Số đỉnh hyperedge demo (5 hay 6): treo đến khi dựng corpus T2; mockup vẽ 6 hiện + 1 ẩn là giả định.
2. ~~Câu chữ template từ chối FR-16~~ **đã chốt** ở story 3.5 (`docs/adr/ADR-015-wording-template-tu-choi-fr-16.md`): giữ nguyên câu đề xuất của spine, và ADR ghi ba biến thể đã bị loại. Wording sống ở đúng một hằng `api.hoi_dap.TEMPLATE_TU_CHOI`, có test canh bản chép thứ hai.
3. Tên sản phẩm và visual identity: "Copilot IT" là tên tạm, chưa có logo.
4. ~~Ai được bật toggle live/offline~~ **đã chốt** ở AD-10 (ARCHITECTURE-SPINE, khớp action item retro Epic 3, đóng ở story 4.1): toggle demo và endpoint cache offline đòi claim `demo` hoặc `admin`, đọc từ token, không suy từ vai giả.
5. Tên và biến thể kịch bản red-team RT-01..RT-05: chốt ở bước test design; RT-02, RT-05 trong mockup là biến thể tự đặt.
6. Hex cụ thể của dải 5 tầng tin cậy {colors.trust-1}..{colors.trust-5}: dải tím là đề xuất chưa duyệt.
7. ~~Cơ chế owner biết có yêu cầu break-glass mới~~ **đã chốt** ở AD-14 (ARCHITECTURE-SPINE, đóng ở story 4.1): UI poll một endpoint trạng thái nhẹ theo chu kỳ cố định 5 giây, trả badge counts và `expires_at` tuyệt đối; endpoint đó là story 5.4. Badge trong mockup là cách hiển thị, không phải cơ chế.
