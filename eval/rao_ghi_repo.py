"""Một cửa dùng chung cho luật "space nào được ghi vật có commit vào cây repo".

Ba công cụ `eval/` sinh ra một file **có commit** mang nguyên văn tên thực thể
hoặc giá trị slot: ảnh chụp đồ thị (`eval/chup_do_thi.py`), trang CT-03
(`eval/ct03.py`, ảnh PNG của nó có commit), và file đề xuất bí danh
(`eval/de_xuat_bi_danh.py`). Cả ba chịu **cùng một** luật, vì cả ba hỏng theo
cùng một cách: một `--space real` rồi ghi vào cây repo là đưa nội dung tài liệu
công ty vào lịch sử git, đúng thứ Policy của `AGENTS.md` cấm.

Trước story 2.12 luật đó sống ở **ba** bản `frozenset` chép tay. Hai bản được
`tests/test_ct03.py` ghim vào nhau; bản thứ ba, thêm ở 2.12, không có gì canh.
Retro Epic 2 tìm ra chỗ đó, và nó là lần thứ hai cùng một khiếm khuyết xuất
hiện: retro Epic 1 đã ghi cửa "tập khóa rỗng" viết ba hình dạng ở ba adapter.
Cửa che thì gom được về `adapters/mask_contract.py` từ story 1.3 và giữ nguyên
suốt hai epic - module này là cùng một phép gom, cho cùng một loại luật.

**Danh sách cho phép, không danh sách cấm.** Một space mới không tự động được
ghi vào repo; người thêm nó phải sửa file này và giải thích vì sao nó an toàn.
Chiều ngược lại - danh sách cấm - làm space mới mặc định an toàn, tức mặc định
sai.

Chỉ stdlib, không nhập gì từ `adapters/`. Đó là ràng buộc thật chứ không phải
gọn gàng: `eval/de_xuat_bi_danh.py` chạy trên máy dev và không được kéo driver
Neo4j vào chỉ để đọc một hằng số.

Từng module vẫn giữ chú thích riêng nói *nó* ghi ra vật gì, vì lý do an toàn
giống nhau nhưng vật sinh ra thì khác nhau. Cái phải là một bản duy nhất là
**giá trị** của danh sách.
"""

from __future__ import annotations

# Hai space dựng được ghi vật có commit vào cây repo.
#
# `synth` là corpus dựng của story 2.8, tài liệu do người viết trong repo.
#
# `khao_sat` thêm ở story 2.10: 50 bản ghi khảo sát ba tỷ lệ n-ngôi cũng là tài
# liệu **giả lập** dựng trong repo (`eval/khao_sat/`), không phải dữ liệu công
# ty. Ảnh chụp của nó *phải* có commit vì nó là nguồn duy nhất của ba con số mà
# chương 4 báo cáo, và ADR-012 đòi người đọc repo tính lại được ba tỷ lệ mà
# không cần kho đang chạy.
#
# `real` và `that_khu` **không** nằm ở đây và không được thêm vào: cả hai chứa
# tài liệu công ty, kể cả bản đã khử (ADR-013 giữ nguyên rào này). Chúng vào
# repo được ở **dạng rút gọn có muối**, và đó là một đường khác, không đi qua
# danh sách này.
SPACE_GHI_TRONG_REPO: frozenset[str] = frozenset({"synth", "khao_sat"})
