# ADR-014 - Hai ô của bảng chính sách đầy đủ là quyết định, không phải hệ quả của A4

**Bối cảnh.** Story 3.2 dựng `config/policy-day-du.yaml`, bảng chính sách khai đủ 13 loại nội dung cho hai vai. Phần lớn bảng là **suy ra được**: bản đồ ACL của PRD addendum A4 khai sáu ràng buộc bằng chữ (SOP đã duyệt → L2 toàn công ty · runbook → DevOps · ticket và lịch sử sự cố → team + Tech Support · CMDB → L0 với người ngoài nhóm hạ tầng · log → nhóm hạ tầng · postmortem → hạn chế), và điều kiện (1) của AD-5 buộc mức tiết lộ không tăng theo hạng độ nhạy. Phép kiểm CSP của retro Epic 2 (05/09/2026) duyệt cả 3^13 phép gán và đếm được **15 phép gán khả thi cho `tech_support`, 17 cho `devops`** - tập khả thi không rỗng, nên thứ tự 13 hạng đã đóng băng diễn đạt được A4 mà không phải đảo hạng nào.

Tập khả thi không rỗng cũng nghĩa là nó **không phải một phần tử**. Bảng chạy hôm nay là một trong 15 × 17 lựa chọn, và hai ô của nó không đến từ A4 lẫn từ đơn điệu. ADR này ghi ra hai ô đó, vì chương 4 phải phân biệt được "bảng buộc phải thế" với "dự án chọn thế", và vì không có chỗ nào khác cho một quyết định không phải là code.

Hai hệ quả **bị ép**, ghi lại để đọc phần dưới không nhầm: `devops` bắt buộc L2 ở `troubleshooting` (hạng 8) và `runbook` (10) - A4 cho DevOps thấy runbook, đơn điệu kéo theo mọi hạng thấp hơn; `tech_support` bắt buộc L0 ở `log` (24), `cmdb` (26) và `bi_mat_ha_tang` (30) - hai cái đầu từ A4, cái thứ ba do đơn điệu kéo theo. Không ô nào trong năm ô ấy là một quyết định.

## Quyết định 1 - `devops` giữ L1 ở `bi_mat_ha_tang`, không lên L2

**A4 không ép `devops` xuống dưới L2 ở bất kỳ hạng nào, kể cả `bi_mat_ha_tang`.** Prose A4 một mình không chặn DevOps thấy tất; cả `L2` lẫn `L1` đều nằm trong 17 phép gán khả thi. Bảng chọn **L1**, che `[source, remediation]`.

Vì sao:

- Nó **kế thừa từ bảng tối giản của story 1.2**, và bảng đó là bảng mà cổng M1 đã đứng lên. Đổi ô này là đổi một mức tiết lộ mà một cổng đã nghiệm thu assert trên.
- Nó giữ cho hệ có **ít nhất một ô L1 ở vai rộng nhất**. Nếu `devops` L2 ở cả 13 loại thì mọi bằng chứng về cơ chế che theo slot chỉ còn ở `tech_support`, và một cơ chế chỉ chứng minh được ở đúng một vai là một cơ chế khó tin hơn.
- Quy tắc gán mức ĐG2 của A4 xếp "chi tiết hạ tầng, tài liệu bảo mật" vào nhóm bắt buộc L0 với người ngoài. `devops` **là** người trong, nên L0 không đúng; nhưng cho một vai đọc nguyên văn lệnh và đường vào hệ thống thì cũng không phải thứ nên mặc định. L1 che `[source, remediation]` là chỗ ở giữa: vai thấy có tài liệu gì, không đọc được đường vào.

Cái giá đã nhận, ghi ra để không ai đọc nhầm khi trình chương 4: `config/policy-toi-thieu-l1.yaml` (cấu hình 4) tự mô tả là "không chặn gì, chỉ che", và luận điểm đó **chỉ đúng trọn với `tech_support`**. Ở `devops` thì ô `bi_mat_ha_tang` giữ nguyên tập che hai slot của cấu hình 3, tức 5 trong 7 slot còn hở. Đó là hệ quả của phép biến đổi `L0 -> L1` (`devops` không có ô L0 nào để nâng), không phải một chỗ quên.

## Quyết định 2 - `tech_support` được L1 ở `canh_bao`

**A4 không nhắc `canh_bao` (hạng 16).** Cả `L2`, `L1` và `L0` đều khả thi. Bảng chọn **L1**, che `[source, remediation]`.

Lý do là một lý do về **phép đo**, và nó phải được nói ra chứ không giấu trong một ô: đó là thứ duy nhất đưa nhóm câu hỏi N3 vào vùng L1.

PRD 5.3 phát biểu "recall(3) lớn hơn recall(2) trên các nhóm **N3 và N5**". Cấu hình 2 (nhị phân) và cấu hình 3 chỉ khác nhau ở đúng vùng L1, nên một nhóm không có cặp nào ở L1 sẽ cho recall(3) = recall(2) - một khoảng cách bằng 0 **vì bảng chính sách, không vì cơ chế**. Đếm trên ba file đã commit trước story 3.2: N3 có **0 cặp** ở L1, vì nó neo vào `runbook` (L2 với cả hai vai) và vào `canh_bao`/`sop` (chưa khai, L0). Một nửa phát biểu 5.3 khi đó không có bằng chứng, và đường ra duy nhất còn lại là soạn thêm câu N3 hoặc thu hẹp phát biểu về đúng N5.

Sau khi khai `canh_bao: L1`: N3 có **3 cặp ở L1** trong 15 cặp vào được ngữ cảnh, N5 có 6 trong 14. `tests/test_bo_cau_hoi.py::test_nhom_n3_co_cap_o_muc_l1_sau_bang_chinh_sach_day_du` ghim hai con số đó, và ca đối chứng ngay dưới nó khẳng định cả hai về 0 dưới `policy-nhi-phan.yaml`.

**Chỗ này phải trung thực trong chương 4.** Một ô chính sách chọn để một phép đo có bằng chứng là một quyết định đi rất gần ranh giới "dựng dữ liệu cho hệ mình thắng", và PRD 5.3 đã tự nêu phòng thủ cho chính rủi ro đó ("nhãn vàng, bảng chính sách và corpus cùng một người dựng"). Ba điều làm nó ở phía đúng của ranh giới, và cả ba kiểm lại được:

1. **Mức chọn hợp lý một cách độc lập.** Cảnh báo giám sát mang ngưỡng, kênh nhận và tên hệ thống đang yếu; cho Tech Support biết *có* một cảnh báo và triệu chứng của nó, mà che nguồn với thao tác khắc phục, là đúng quy tắc ĐG2 ("L1 nếu chỉ là phân vai nội bộ"). Nếu ô này phải bịa ra một mức phi lý để phép đo chạy được thì quyết định đã sai.
2. **`masked_slots` không được chọn cho dễ.** Nó bị điều kiện (2) của AD-5 ép lồng nhau: `canh_bao [source, remediation]` ⊆ `bao_cao_su_co [cause, source, remediation]` ⊆ `postmortem [subject, cause, source, remediation]`. Một tập che rộng hơn ở `canh_bao` là bảng bị validator từ chối.
3. **Nhãn truy hồi vàng không sửa theo.** Không một dòng nào của `eval/nhan_truy_hoi_vang.json` đổi ở story 3.2; chỉ bảng chính sách đổi, nên chênh đọc được là chênh của bảng. Lọc nhãn theo mức tiết lộ là thứ spec cấm thẳng, vì khi đó cả bốn cấu hình đều ra recall 100%.

## Ghi chú

- Thứ tự 13 hạng của `config/hang-do-nhay.yaml` **không đổi** ở story 3.2, và ba hạng đóng băng 10/20/30 giữ nguyên. Không có re-ingest: mức tiết lộ tính lúc truy vấn, không ghi lên dữ liệu.
- Hai ô này chỉ tồn tại ở cấu hình 3 và, qua phép biến đổi, ở cấu hình 4. Cấu hình 1 mở mọi ô lên L2 và cấu hình 2 ép mọi L1 xuống L0, nên không cấu hình nào trong hai cấu hình đó mang một quyết định riêng.
- Đổi một trong hai ô là đổi một con số của chương 4. `tests/test_chinh_sach.py::test_cot_devops_cua_cau_hinh_3_ghim_tuyet_doi` và `tests/test_bo_cau_hoi.py::test_nhom_n3_co_cap_o_muc_l1_sau_bang_chinh_sach_day_du` là hai chỗ đỏ lên khi ai đó thử.
