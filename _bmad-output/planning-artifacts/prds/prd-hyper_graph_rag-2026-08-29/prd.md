---
title: PRD - AI Copilot hỏi đáp tiếng Việt trên HyperGraphRAG với phân quyền hyperedge
status: final
created: 2026-08-29
updated: 2026-08-29
---

# PRD - Trợ lý AI tri thức nội bộ trên HyperGraphRAG với kiểm soát truy cập mức hyperedge

Tên đề tài: "Nghiên cứu và xây dựng Trợ lý AI tri thức nội bộ doanh nghiệp trên nền HyperGraphRAG với cơ chế kiểm soát truy cập ở mức hyperedge". Tên tiếng Anh: "Permission-Aware Retrieval over Knowledge Hypergraphs: Partial Hyperedge Disclosure for Enterprise Knowledge Assistants".

## 1. Tầm nhìn và bối cảnh

### 1.1 Tầm nhìn

Kinh nghiệm xử lý sự cố của nhân viên IT hiện nằm rải rác trong runbook, ticket, log và trong đầu người làm lâu năm. Khi người đó nghỉ việc, tri thức mất theo. Sản phẩm giữ lại tri thức này dưới dạng hypergraph, mỗi sự thật là một quan hệ n-ngôi đầy đủ ngữ cảnh (triệu chứng, nguyên nhân, điều kiện, hành động, người phụ trách), nên không bị vỡ vụn hay sai lệch khi lưu. Người mới hoặc ít kinh nghiệm hỏi đáp bằng tiếng Việt và nhờ đó xử lý công việc ở mức cao hơn năng lực hiện có.

Câu định vị (lặp 3 lần khi bảo vệ): **"Giữ lại kinh nghiệm xử lý sự cố dưới dạng hypergraph có phân quyền, để người mới làm việc ở mức kinh nghiệm cao hơn mà bí mật vẫn an toàn."** Cách nói đời thường khi demo: "Trợ lý AI cho công ty, không sợ nó lỡ mồm nói ra bí mật."

### 1.2 Đóng góp cốt lõi

Muốn tri thức dùng chung được thì phải dám nạp cả tài liệu nhạy cảm, và đó là chỗ mọi hệ hiện nay dừng lại. Định vị đóng góp của khóa luận: **đơn vị phân quyền trùng đơn vị truy hồi**. Mỗi sự thật là một hyperedge n-ngôi mang nhãn tiết lộ 3 mức (L0 vô hình, L1 biết tồn tại nhưng phần nhạy cảm bị che, L2 đọc đầy đủ), nên câu trả lời và trích dẫn tự co giãn theo quyền người hỏi. Dữ liệu không đủ quyền bị lọc ngay tại tầng vector trước khi được tính điểm, nên với kho tri thức nội bộ, LLM không thể trích dẫn nội dung chưa từng vào ngữ cảnh (hệ không tuyên bố gì về suy đoán từ tri thức nền của model - giới hạn ghi ở chương Thảo luận). ACL mức tài liệu bảo vệ được kho, không bảo vệ được phép suy luận sau khi tri thức đã trộn nguồn.

Ba đóng góp dự kiến: (1) cơ chế phân quyền 3 mức tiết lộ ở đơn vị hyperedge cho RAG dựa trên đồ thị; (2) tầng phân quyền tách rời cho HyperGraphRAG, kết nối vector DB và graph DB chuyên dụng; (3) bộ dữ liệu kiểm thử song ngữ cảnh cùng 3 phép đo tái lập được. Sáu đóng góp chi tiết ĐG1-ĐG6 ở addendum A10. Một lợi thế kiến trúc cần nói rõ với hội đồng: Neo4j Community không có kiểm soát truy cập chi tiết và không fork nào có adapter sẵn, nên adapter, phần bắt buộc phải tự viết, trở thành đúng chỗ chèn cơ chế phân quyền; ranh giới "phần nào của em" nhờ vậy rất rõ.

### 1.3 Vì sao chưa ai làm (khác biệt so với hiện trạng)

- Sản phẩm thương mại (Microsoft 365 Copilot, Amazon Q Business, Glean) và các công trình học thuật 2024-2026 về permission-aware RAG đều phân quyền ở mức tài liệu hoặc chunk. Sau khi GraphRAG trộn nhiều nguồn thành một entity, ACL mức tài liệu mất dấu.
- Prior art phân quyền mức triple chỉ tồn tại trong triple store truyền thống (Oracle Label Security cho RDF, GraphDB), tách rời pipeline RAG.
- Trong phạm vi khảo sát (nguồn ở `research-boi-canh.md` trong workspace này, tính đến 08/2026) chưa tìm thấy công trình nào (a) phân quyền ở mức hyperedge n-ngôi, (b) đưa quyền vào pre-filter tại tầng vector retrieval, (c) với chính sách tiết lộ nhiều mức dạng dữ liệu cấu hình. Cách diễn đạt giữ nguyên mức bằng chứng: "chưa có lời giải được tài liệu hóa công khai trong các hệ thống production", không tuyên bố "bài toán mở".

### 1.4 Hai tầng phạm vi, không được nhầm

Dự án doanh nghiệp (BFC-AI-COPILOT-SCOPE v1.1, 41 hạng mục) là bối cảnh nghiệp vụ. Khóa luận là lát cắt nghiên cứu, chỉ giải bài toán phân quyền trên tri thức dẫn xuất; phần lớn hạng mục giai đoạn 2-3 của dự án được chủ động để ngoài phạm vi.

### 1.5 Người dùng và vai

Người dùng của sản phẩm là nhân viên IT nội bộ, thu gọn còn 4 vai nghiệp vụ + 1 vai quản trị, mỗi vai kích hoạt một tình huống phân quyền khác nhau. Bên cạnh đó, PRD ghi nhận hội đồng bảo vệ là đối tượng đánh giá chính, tiếp cận hệ qua demo 4 nhịp 90 giây; điều này chi phối ưu tiên UI (mục 2.7) chứ không thay thế người dùng thật.

| Vai | Vai trò trong hệ | Tình huống phân quyền đại diện |
|---|---|---|
| DevOps | Kỹ sư vận hành, quyền kỹ thuật cao | L2 với hầu hết tri thức kỹ thuật; vai demo chính |
| Tech Support | Tuyến 1, cần biết có tồn tại để chuyển tiếp | Vùng L1 chủ đạo: thấy sự thật tồn tại, phần nhạy cảm bị che |
| Sale/BA | Ngoài kỹ thuật | L0 với chi tiết hạ tầng và bảo mật; vai "bị chặn" trong demo |
| Trưởng nhóm | Bức tranh đầy đủ, owner duyệt break-glass | Người phê duyệt truy cập khẩn cấp |
| Admin | Quản trị chính sách và tài khoản, không phải vai nghiệp vụ | Chỉnh bảng chính sách, xem nhật ký kiểm toán |

7 nhóm người dùng của dự án công ty (DevOps, Vận hành, Tech Support, PO/RD, Data Center, Sale/BA/QA, CIO) ánh xạ được về 4 vai này về sau, vì bảng chính sách là dữ liệu cấu hình, thêm vai không sửa code.

Phản hồi GVHD: chưa có, chờ bản tóm tắt 1 trang gửi tuần 1. Khi có phản hồi sẽ cập nhật PRD theo quy trình correct-course.

## 2. Tính năng và yêu cầu chức năng

Tính năng lõi có tên là **Permission-Aware Citation**: hỏi đáp có trích dẫn và chặn rò rỉ L0/L1/L2 là một tính năng, không phải hai. Trích dẫn tự co giãn theo quyền, chỗ L1 hiện placeholder kèm người phụ trách, chỗ L0 biến mất không dấu vết. Hỏi đáp không có phân quyền là RAG tầm thường; phân quyền không có hỏi đáp thì không có gì để demo.

Ưu tiên ghi theo MoSCoW của brief. Mọi FR viết ở mức capability; cơ chế cài đặt nằm trong `addendum.md`.

### 2.1 Nạp và dựng tri thức

- **FR-01** (M) Nạp tài liệu bằng import thư mục. Không có connector tới hệ thống ngoài; ACL nguồn mô phỏng bằng metadata trong corpus (ADR-009).
- **FR-02** (M) Trích xuất sự thật n-ngôi từ văn bản tiếng Việt kỹ thuật theo lược đồ 8 vai (chủ thể, triệu chứng, nguyên nhân, điều kiện, hành động khắc phục, nguồn, thời điểm, người phụ trách). LLM bị buộc xuất JSON đúng lược đồ; bản ghi sai lược đồ bị loại (ADR-006).
- **FR-03** (M) Lưu hypergraph dạng đồ thị hai phía: hyperedge là node mang thuộc tính, nối tới entity thành viên bằng cạnh có nhãn vai. Không phân rã quan hệ n-ngôi thành các cạnh nhị phân. Nhãn vai trên cạnh là phần mở rộng của khóa luận so với upstream (upstream lưu cạnh không nhãn).
- **FR-04** (M) Quan hệ nhị phân là trường hợp suy biến của cùng cơ chế (hyperedge chỉ điền 2 vai), không cần đường xử lý riêng.
- **FR-05** (M) Mỗi hyperedge khi dựng được gắn metadata phân quyền (scope, độ nhạy theo loại nội dung) và provenance nguồn (`source_id`). Thuộc tính phân quyền thu về một khóa lọc duy nhất, là hàm thuần của thuộc tính dữ liệu, phục vụ pre-filter (NFR-06).
- **FR-06** (M) ACL đồng bộ sang payload của vector store để pre-filter được. Trường phân quyền phải được khai báo trước khi nạp dữ liệu. Có test đồng bộ hai nơi (vector store và graph store) chạy trong CI (NFR-03); đây là điểm dễ sinh lỗi nhất của kiến trúc.
- **FR-31** (M) Hai bộ dữ liệu, mỗi bộ cho một loại chứng minh (ADR-008): tài liệu thật đã khử nhạy cảm chứng minh trích xuất n-ngôi tiếng Việt (ĐG6); corpus dựng có chủ đích ~40 tài liệu chứng minh rò rỉ/ACL. Khử nhạy cảm bằng công cụ của công ty với bí danh nhất quán trên mọi tài liệu (App01 → SRV-A); bảng ánh xạ bí danh giữ riêng, không nộp kèm khóa luận.
- **FR-32** (S) Chuẩn hóa thực thể khi trích xuất: dùng CMDB làm từ điển thực thể chuẩn để gộp bí danh (App01, app01.company.vn); bảng thuật ngữ nội bộ đưa vào prompt trích xuất; bảng bí danh do LLM đề xuất, người xác nhận.

### 2.2 Truy hồi có phân quyền (lõi đóng góp)

- **FR-07** (M) Pre-filter tại tầng vector: bộ lọc quyền áp dụng ngay trong quá trình tìm kiếm, dữ liệu không đủ quyền không bao giờ được tính điểm tương đồng (chốt 2, brief §6). Post-filter không được dùng thay cho pre-filter; cho phép thêm một bước post-check xác nhận lại quyền trên tập đã truy hồi làm phòng vệ chiều sâu chống lệch ACL giữa hai nơi lưu.
- **FR-08** (M) Mọi đường truy hồi (vector và duyệt graph) đi qua một điểm chèn quyền duy nhất ở tầng ứng dụng; truy vấn graph được tiêm điều kiện lọc quyền.
- **FR-09** (M) Bảng chính sách dạng dữ liệu cấu hình, gồm hai tầng: (a) nhóm quyền × loại nội dung → mức tiết lộ mặc định L0/L1/L2; (b) vai slot → che/hiện ở mức L1. Hoán đổi bảng chính sách không sửa code (chốt 3, brief §6). Không lưu cứng mức tiết lộ lên hyperedge.
- **FR-10** (M) Ở mức L1, hệ che đúng đỉnh mang vai nhạy cảm theo chính sách và giữ các đỉnh còn lại. Chính sách mặc định phủ đủ 8 vai: triệu chứng, điều kiện, thời điểm công khai; nguyên nhân, nguồn, chủ thể hạ tầng, hành động khắc phục nhạy cảm (thường chứa lệnh và ngữ cảnh hạ tầng); người phụ trách hiện ở mức vai/nhóm, không hiện tên cá nhân. Admin chỉ chỉnh ngoại lệ.
- **FR-11** (M) Xử lý ca đa nguồn khác quyền: hyperedge hoặc entity tổng hợp từ nhiều tài liệu có quyền khác nhau phải mang mức tiết lộ an toàn. Mức sàn chấp nhận được (để MUST luôn có đường về đích): biến thể bảo thủ, artifact đa nguồn nhận mức hạn chế nhất trong các nguồn, đủ pass Đo 1; spike T1-T3 tìm phương án ít mất recall hơn. Đo 1 có test riêng cho ca này. [NOTE FOR PM: chưa có pattern công khai; không coi là đã có lời giải, xem R1.]
- **FR-12** (M) Lọc quyền hoàn tất trước khi lắp ngữ cảnh cho LLM: cả loại bỏ hyperedge L0 lẫn che slot nhạy cảm của hyperedge L1 đều xảy ra trước, ngữ cảnh gửi LLM là bản đã che. Không dùng lọc phía LLM hay lọc lúc sinh câu trả lời làm cơ chế kiểm soát.

### 2.3 Hỏi đáp và trích dẫn

- **FR-13** (M) Hỏi đáp tiếng Việt, mỗi câu trả lời kèm danh sách trích dẫn nguồn.
- **FR-14** (M) Permission-Aware Citation: danh sách trích dẫn co giãn theo quyền người hỏi. Sự thật L1 hiện dạng placeholder "còn một phần bị hạn chế, liên hệ [nhóm chịu trách nhiệm]"; placeholder luôn hiện ở mức vai/nhóm (ví dụ DevOps), không hiện tên cá nhân, kể cả khi slot người phụ trách bị che. Sự thật L0 không xuất hiện trong ngữ cảnh, trong danh sách trích dẫn lẫn trong số đếm kết quả; điều này kiểm tất định ở tầng truy hồi.
- **FR-15** (M) Phần nội dung bị che ở mức L1 hiển thị thành vùng bôi đen trong câu trả lời, người dùng thấy rõ mình đang bị che cái gì ở vị trí nào. Vùng bôi đen chỉ là cách hiển thị phần đã bị che từ tầng truy hồi (FR-12), không phải cơ chế che.
- **FR-16** (M) Khi ngữ cảnh truy hồi không chứa đáp án, hệ từ chối trả lời thay vì bịa. Đo bằng nhóm N7 trong Đo 2 (tiêu chí "không bịa"), không thuộc phạm vi assert tất định của Đo 1 vì đây là hành vi đầu ra LLM.
- **FR-33** (S) Nhãn tin cậy 5 tầng tô màu cho nguồn trích dẫn. Định nghĩa cụ thể 5 tầng chưa có trong tài liệu nguồn, chốt ở bước UX (câu hỏi mở, mục 6.2).

### 2.4 Danh tính, quản trị và giao diện

- **FR-17** (M) Đăng nhập bằng JWT với vai trò gắn tài khoản. Admin tạo tài khoản, không có đăng ký công khai, không làm luồng quên mật khẩu/email/2FA. Tài khoản demo và vai khởi tạo bằng cấu hình seed, không phụ thuộc màn quản lý người dùng (FR-24).
- **FR-18** (M) Nút "xem như" đổi vai ngay trong phiên (impersonation, không đăng xuất) và chế độ so sánh 2 cột cùng câu hỏi giữa 2 vai.
- **FR-19** (M tối thiểu / S mở rộng) Panel hypergraph (Cytoscape.js): phần tối thiểu phục vụ demo nhịp 1 là MUST - hover một trích dẫn làm sáng hyperedge tương ứng, vẽ đúng cấu trúc hai phía đang lưu; phần khám phá đồ thị mở rộng là SHOULD.
- **FR-20** (M tối thiểu / S mở rộng) Break-glass: luồng cơ bản xin - owner duyệt - tự hết hạn phục vụ demo nhịp 4 là MUST; phần mở rộng (chọn thời hạn linh hoạt, đính kèm ngữ cảnh) là SHOULD. Phạm vi cấp là vùng lân cận hyperedge: các hyperedge cách hyperedge bị chặn tối đa k bước trên đồ thị hai phía (k chốt ở bước kiến trúc). Có ô lý do; mọi lần cấp đều được ghi nhật ký để hậu kiểm. Không có tự động cấp: mọi truy cập khẩn cấp phải được owner xác nhận trước khi mở. Phương án "tự cấp trước, hậu kiểm sau" chỉ bàn trong chương Thảo luận, không cài đặt.
- **FR-21** (M tối thiểu / S mở rộng) Màn kiểm thử bảo mật: chạy bộ test red-team trước hội đồng, hiển thị PASS/FAIL theo kịch bản là MUST; phần chỉnh ngoại lệ trực tiếp trên màn là SHOULD.
- **FR-22** (S) Màn cấu hình chính sách: bảng nhóm quyền × loại nội dung → mức tiết lộ mặc định, admin chỉnh ngoại lệ. Đây là nơi chứng minh chính sách là dữ liệu cấu hình.
- **FR-23** (M phần ghi / C màn hiển thị) Việc ghi sự kiện vào nhật ký (ai hỏi, chạm hyperedge nào, bị chặn ở mức nào, break-glass cấp cho ai) là MUST vì hậu kiểm của FR-20 và bằng chứng Đo 1 cần nó. Màn hiển thị nhật ký kiểm toán là COULD, cắt được nếu thiếu thời gian.
- **FR-24** (C) Quản lý người dùng tối giản (danh sách, tạo, gán vai).
- **FR-25** (C) Màn tình trạng hệ thống: trạng thái 4 phụ thuộc ngoài, số hyperedge/entity/tài liệu, token và chi phí LLM lũy kế, thời gian truy vấn trung bình (ADR-010; không làm giám sát tài nguyên đầy đủ).
- **FR-26** (C) Các tính năng dự bị nếu dư thời gian sau M2: phát hiện tri thức lỗi thời mức hyperedge (ca SSL), Knowledge Gap, vùng thường trú tri thức, phòng vệ cảm ứng. Không cam kết; định nghĩa trong addendum.

### 2.5 Đo lường và vận hành khóa luận

- **FR-27** (M) Bộ unit test bảo mật assert trực tiếp trên ngữ cảnh truy hồi (không trên câu trả lời LLM), chạy trong CI, viết trước khi cài đặt cơ chế (chốt 1, brief §6; ADR-007).
- **FR-28** (M) Hệ chạy được 3 cấu hình đo (tắt phân quyền / nhị phân / L0-L1-L2) chỉ bằng thay bảng chính sách, không sửa code, không dựng hệ thứ hai. Baseline nhị phân là policy ép L1 xuống L0.
- **FR-29** (M) Chế độ demo offline: cache toàn bộ truy vấn của kịch bản demo, chạy không cần mạng; kèm video demo dự phòng quay sẵn.
- **FR-30** (M) Đo chi phí LLM thực tế trên 3-5 tài liệu tại T1 để ngoại suy toàn corpus trước khi chốt cấu hình trích xuất.

### 2.6 Sản phẩm quá trình (deliverable khóa luận, không phải tính năng hệ thống)

Corpus ~40 tài liệu (3 kịch bản sự cố + nhiễu) · bộ dữ liệu thật đã khử nhạy cảm (FR-31) · bộ câu hỏi 7 nhóm ~52 câu, mỗi câu gắn vai người hỏi · bộ vàng 30 câu gán nhãn tay (tập con của bộ 52 câu) · nhãn truy hồi vàng: với mỗi câu trong bộ đo, danh sách hyperedge cần xuất hiện trong ngữ cảnh theo từng vai (ground truth tất định cho Đo 3) · 3 phép đo (mục 5) · thí nghiệm CT-03 kèm ảnh chụp màn hình (mô tả ở mục 5.4), bằng chứng lõi cho ĐG3 · mục "Phương pháp xây dựng bộ dữ liệu thử nghiệm" trong thuyết minh · bản tóm tắt 1 trang gửi GVHD tuần 1.

Bốn phụ lục khóa luận: nhật ký ADR 25-40 bản ghi · quy trình người-AI kèm prompt log của phần lõi · bảng thuật ngữ · bộ câu hỏi và đáp án vàng.

### 2.7 Đường demo 4 nhịp (ràng buộc ưu tiên UI)

UI cam kết trước hết cho đường demo 90 giây: (1) DevOps hỏi, hover trích dẫn làm sáng hyperedge; (2) không gõ lại câu hỏi, đổi vai sang Tech Support, câu trả lời tự viết lại, các đỉnh nhạy cảm của hyperedge mờ đi theo từng slot trong khi đỉnh công khai vẫn sáng (đúng ĐG4: che đúng đỉnh, không che cả cụm), hiện "còn 1 phần bị hạn chế, liên hệ nhóm DevOps"; (3) đổi sang Sale/BA bị chặn L0, im lặng hoàn toàn; (4) xin break-glass, owner duyệt, quyền tự hết hạn. Ngay sau 4 nhịp, màn kiểm thử bảo mật (FR-21) chạy bộ red-team live trước hội đồng, đích là bảng toàn PASS trên bộ RT-01..RT-05 cùng các biến thể chốt ở bước test design.

Màn không phục vụ đường này chỉ xây sau mốc M2 (đã rà soát, không màn COULD nào cần kéo lên); màn không kịp xây được đưa vào chương 4 dưới dạng thiết kế, không lặng lẽ biến mất.

## 3. Phạm vi

### 3.1 Trong phạm vi (theo ưu tiên)

- **MUST**: toàn bộ FR đánh dấu (M) ở mục 2, gồm POC phân quyền tuần 1 và mốc M1.
- **MUST bổ sung từ đường demo**: tập tối thiểu của FR-19 (hover-sáng hyperedge), FR-20 (luồng break-glass cơ bản), FR-21 (màn PASS/FAIL) và phần ghi nhật ký của FR-23 - vì kịch bản bảo vệ chính thức không được phép dựa hoàn toàn vào tính năng ở mức SHOULD.
- **SHOULD**: phần mở rộng của FR-19/20/21 · FR-22 màn cấu hình chính sách · FR-32 chuẩn hóa thực thể · FR-33 nhãn tin cậy 5 tầng. Hai màn ăn điểm giữ đến cùng: panel hypergraph (FR-19) và red-team live (FR-21).
- **COULD**: màn hiển thị nhật ký kiểm toán (FR-23) · FR-24 quản lý người dùng · FR-25 tình trạng hệ thống · FR-26 nhóm tính năng dự bị. Cắt được nếu thiếu thời gian mà không ảnh hưởng luận điểm khóa luận.

### 3.2 Ngoài phạm vi (WON'T, vào chương Hướng phát triển)

Connector thật tới Confluence/Jira/Git (thay bằng import thư mục; câu trả lời hội đồng: kế thừa ACL từ hệ nguồn là bài tích hợp đã có lời giải, không phải câu hỏi nghiên cứu) · ACL suy đoán bi quan qua webhook HR · RCA đa nguồn từ log · mọi dashboard và giám sát tài nguyên · định tuyến ticket · NebulaGraph (vào chương Khả năng mở rộng kèm bảng so sánh) · triển khai production đa người dùng · đa phương thức (giới hạn thừa nhận của upstream).

### 3.3 Nguyên tắc phạm vi

1. **Phạm vi corpus khác phạm vi hệ thống.** Hệ không hard-code danh sách loại tài liệu; loại nội dung là dữ liệu cấu hình. Hội đồng hỏi "còn loại khác thì sao" được trả lời bằng thiết kế, không bằng việc sinh thêm tài liệu.
2. **Đường demo trước đã.** Ưu tiên UI theo mục 2.7; mốc M3 (cuối T6) đóng băng tính năng, M4 (T8) không viết thêm code.

## 4. Yêu cầu phi chức năng và ràng buộc

### 4.1 An toàn và đúng đắn

- **NFR-01 Tất định:** phép đo bảo mật assert trên ngữ cảnh truy hồi (tất định), không trên đầu ra LLM (ngẫu nhiên).
- **NFR-02 Tái lập:** Đo 1 và Đo 3 tái lập chính xác (tất định); Đo 2 tái lập theo quy trình - ghim model và phiên bản judge, temperature 0, công bố toàn bộ transcript chấm, dao động nhỏ được báo cáo kèm. Kho tài liệu, bộ câu hỏi và phiên bản hệ thống đóng băng trước khi đo.
- **NFR-03 Nhất quán ACL hai nơi:** metadata quyền ở vector store và graph store không được lệch nhau; test đồng bộ bắt buộc trong CI.
- **NFR-04 Chính sách hot-swap:** đổi bảng chính sách có hiệu lực không cần dựng lại dữ liệu hay sửa code.
- **NFR-05 Bảo mật dữ liệu nguồn:** tài liệu thật chưa khử nhạy cảm không được gửi lên API bên thứ ba. Hoặc khử trước bằng công cụ của công ty theo FR-31, giữ văn phong tiếng Việt thật, hoặc dùng model local (Ollama + Qwen cho LLM theo ADR-008, bge-m3 cho embedding). Không có lựa chọn thứ ba.

### 4.2 Hiệu năng và độ tin cậy demo

- **NFR-06 Hình dạng filter quyền:** khóa pre-filter tại tầng vector là một field keyword duy nhất, là hàm thuần của thuộc tính dữ liệu (scope × loại nội dung), tính lúc ingest và không phụ thuộc bảng chính sách. Bảng chính sách chỉ ánh xạ vai người hỏi ra tập khóa được phép và mức tiết lộ tại thời điểm truy vấn, nên đổi bảng không chạm payload (giữ trọn NFR-04 và chốt 3). Không dùng AND đa điều kiện hay ACL list per-user ở đường truy vấn chính; mỗi người dùng ánh xạ về số giá trị khóa nhỏ (chốt N ở bước kiến trúc). Số liệu nền tham chiếu (benchmark của Qdrant, không phải dự đoán cho hệ khóa luận): AND 2 điều kiện với selectivity 4% làm recall sụp còn 39,7%. Đây là ràng buộc thiết kế mô hình quyền, không phải tinh chỉnh hạ tầng.
- **NFR-07 Demo offline:** toàn bộ đường demo chạy được không cần mạng (cache, FR-29) vì hệ có 4 phụ thuộc ngoài tiến trình (2 dịch vụ tự vận hành + 2 API ngoài), mỗi cái là một điểm chết trong ngày bảo vệ.
- **NFR-08 Thời gian trả lời:** hiển thị thời gian truy vấn trung bình ở màn tình trạng hệ thống làm số liệu chương 4; không đặt SLA cứng, hiệu năng không phải câu hỏi nghiên cứu.
- **NFR-09 Độ trễ hiệu lực quyền:** thay đổi vai người dùng hoặc scope của hyperedge có hiệu lực chậm nhất ở truy vấn kế tiếp, không cần dựng lại index hay re-embed; payload mang phiên bản ACL để vô hiệu cache. Đây chính là khả năng mà nhịp 2-3 của demo và kịch bản red-team RT-03 (cửa sổ 15 phút sau khi nhân viên nghỉ) kiểm tra; Đo 1 có test đổi vai rồi hỏi lại, ngữ cảnh phải thu hẹp ngay.

### 4.3 Ràng buộc dự án

| Ràng buộc | Giá trị |
|---|---|
| Thời gian | 8 tuần từ 27/08/2026; M1 cuối T1, M2 cuối T4, M3 đóng băng cuối T6, M4 không code T8 |
| Nhân lực | 1 sinh viên + Claude Code (quy trình QT1-QT6, test viết trước, core/ 500-800 dòng tự giải thích được) |
| Nền tảng | Fork `hypergraphrag` (NeurIPS 2025), không sửa lõi truy hồi, tầng ACL tách rời (ADR-001) |
| Hạ tầng | Máy chủ tự vận hành, mọi dịch vụ chạy Docker (quy ước dự án); Neo4j Community (không có fine-grained AC, authz nằm ở adapter tự viết); Qdrant |
| Stack | Python + FastAPI + JWT · Next.js/React + Cytoscape.js · DeepSeek (vòng lặp) + GPT-4o (dựng cuối) · Ollama + Qwen local cho dữ liệu thật chưa khử · embedding API + bge-m3 local |
| Ngân sách API | Nền ~20 USD, không phải trần cứng; kỷ luật đo cost tại T1 (FR-30) |
| Phương án lùi | Vector store: ChromaDB · Graph store: Memgraph · Nền: LightRAG (chỉ khi hypergraph không còn là giá trị cốt lõi, hiện không đổi) |

## 5. Tiêu chí thành công

Khung phương pháp luận là chứng minh tính khả thi (existence proof), không phải benchmark cạnh tranh: không so đọ hiệu năng với hệ khác. Bằng chứng lõi là phản ví dụ, dựng một ca trong đó mọi tài liệu nguồn đều được phân quyền hoàn toàn đúng nhưng hệ không phân quyền hyperedge vẫn rò rỉ qua phép ghép 2-hop; một phản ví dụ là đủ giá trị khoa học. Tuyên bố giữ hẹp: "trong phạm vi tri thức sự cố IT nội bộ", không nói "hypergraph tốt hơn" chung chung.

Ba phép đo chạy ở T7 trên bộ câu hỏi 7 nhóm ~52 câu (N1 tra cứu đơn 6 · N2 tổng hợp đa nguồn 8 · N3 phụ thuộc điều kiện 12 · N4 ca tương tự 5 · N5 chạm quyền 10 · N6 phụ thuộc thời gian 5 · N7 không có đáp án 6). Ba nhóm then chốt: N3 chứng minh giá trị n-ngôi, N5 chứng minh ACL, N7 đo bịa đặt. Ví dụ xuyên suốt cả ba phép đo: sự cố App01 ngày 12/08.

### 5.1 Đo 1 - Bảo mật (tất định)

Unit test khẳng định trên ngữ cảnh truy hồi, chạy trong CI, gồm bốn lớp assert áp cho cả đường vector lẫn đường duyệt graph: (a) không chứa hyperedge L0 với vai đang hỏi; (b) không chứa nội dung các slot L1 đã bị che, kiểm theo danh sách slot bị che do tầng truy hồi xuất ra (không so khớp chuỗi thuần để tránh dương tính giả); (c) đổi vai rồi hỏi lại cùng câu, ngữ cảnh thu hẹp ngay ở truy vấn kế tiếp (NFR-09); (d) ca đa nguồn khác quyền: hyperedge dẫn xuất tôn trọng mức hạn chế nhất của các nguồn (FR-11). Đối chứng là chính hệ thống khi tắt cơ chế phân quyền; cấu hình tắt này dùng chung với cấu hình (1) của Đo 3. Kết quả kỳ vọng: 100% test pass; một test fail là lỗi chặn phát hành.

### 5.2 Đo 2 - Chất lượng câu trả lời

Bộ vàng 30 câu (tập con gán nhãn tay của bộ 52 câu), chấm bằng LLM-as-judge chéo model (model chấm khác model sinh, chống self-preference; ghim model, phiên bản và temperature 0 theo NFR-02). Rubric 4 tiêu chí: đúng trích dẫn · đủ ý · không bịa (N7 phải từ chối) · tôn trọng quyền. [ASSUMPTION: rubric chưa chốt từng tiêu chí, chỉnh khi viết chương 3.] Neo bằng người: tự chấm tay 10-15 câu (~0,5 ngày), báo cáo tỷ lệ đồng thuận người-máy, bảng chấm vào phụ lục. Kèm bảng so sánh chất lượng trích xuất DeepSeek vs GPT-4o trên bộ vàng.

### 5.3 Đo 3 - Cái giá của an toàn

Recall của Đo 3 là recall truy hồi tất định, tính trên nhãn truy hồi vàng (mục 2.6): tỷ lệ hyperedge kỳ vọng xuất hiện trong ngữ cảnh truy hồi, tính theo từng vai người hỏi; không đo qua LLM. So 3 cấu hình trên cùng hệ thống, chỉ đổi bảng chính sách (một biến duy nhất): (1) tắt phân quyền, cho trần recall; (2) nhị phân thấy/không, tức policy ép L1 xuống L0, là baseline; (3) L0/L1/L2. Phát biểu cần chứng minh: recall(3) lớn hơn recall(2) trên các nhóm N3 và N5, báo cáo con số kèm khoảng tin cậy bootstrap; không đặt ngưỡng tuyệt đối (đã chốt đổi framing), sức thuyết phục nằm ở đồ thị "hai đường một khoảng cách" trong khi cả (2) và (3) đều pass Đo 1.

### 5.4 Kiểm chứng giả định nền (T1)

Đếm trên 50 bản ghi sự cố/SOP thật (~1 ngày): Overall N-ary Ratio, Sensitive N-ary Ratio, và Composition-Risk Ratio (tỷ lệ ca nhạy cảm hình thành từ ghép nhiều mảnh - con số chống lưng cho luận điểm an ninh). Kèm thí nghiệm CT-03 (30 phút): in mô tả entity sau khi dựng graph để chứng minh nó pha trộn nguồn, tái lập được luận điểm "ACL mức tài liệu mất dấu". Thế thủ nếu Overall thấp: cơ chế không yêu cầu dataset chủ yếu n-ngôi, binary là trường hợp suy biến, giá trị hypergraph là kiểm soát quan hệ tổng hợp như một đơn vị.

### 5.5 Counter-metrics

- Đo 3 chính là counter-metric của Đo 1: an toàn tuyệt đối mà recall sụp thì cơ chế vô dụng.
- Rò rỉ metadata của L1 là cái giá được thừa nhận có kiểm soát; đường cong recall so với mức rò rỉ vào chương Thảo luận.
- Chi phí LLM lũy kế hiển thị công khai (FR-25) để chứng minh tính khả thi kinh tế.

### 5.6 Mốc nghiệm thu

| Mốc | Thời điểm | Tiêu chí | Nếu trượt |
|---|---|---|---|
| M1 | Cuối T1 | Một truy vấn, hai tài khoản, hai kết quả khác nhau, trên dữ liệu dựng tay | Báo động đỏ: họp GVHD trong tuần, quyết theo nguyên nhân - lỗi upstream thì xét LightRAG, lỗi adapter thì lùi ChromaDB/Memgraph, lỗi thiết kế thì thu hẹp đề tài |
| M2 | Cuối T4 | Demo được toàn bộ cơ chế không cần UI (curl/Postman) | Cắt mọi COULD và phần mở rộng SHOULD, giữ tập tối thiểu demo |
| M3 | Cuối T6 | Đóng băng tính năng | Chỉ sửa lỗi |
| M4 | T8 | Không viết thêm dòng code nào | - |

## 6. Rủi ro và câu hỏi mở

### 6.1 Rủi ro chính

| # | Rủi ro | Mức | Đối sách |
|---|---|---|---|
| R1 | ACL trên tri thức dẫn xuất chưa có pattern công khai: entity/hyperedge tổng hợp từ nhiều nguồn khác quyền (FR-11) | Cao, rủi ro lớn nhất của đề tài | **Spike thiết kế riêng T1-T3** (đã chốt). Hai hướng khởi điểm: phân vùng theo scope để artifact kế thừa một scope duy nhất; hoặc lọc theo provenance nguồn, biến thể bảo thủ (phải đọc được toàn bộ nguồn). Không đưa vào kế hoạch như việc "đã có pattern". Trùng với ĐG3 nên vừa là rủi ro vừa là đóng góp |
| R2 | Trích xuất n-ngôi tiếng Việt kém | Cao | Ngưỡng báo động: precision bộ vàng dưới 60% ở T2 thì chuyển GPT-4o toàn phần, tăng few-shot, đơn giản hóa lược đồ vai |
| R3 | Fork không có adapter Qdrant/Neo4j (đã quét 71 fork, không fork nào có) | Trung bình | Tự viết T1, ước 2-4 ngày công (chưa kiểm chứng bằng code); donor LightRAG v1.1.1 `Neo4JStorage` + label scheme workspace của main; bẫy đã biết ghi trong addendum. Lùi: ChromaDB/Memgraph. Spike tích hợp đã chạy một phần (commit `5a8803e`) |
| R4 | ACL hai nơi (Qdrant payload, thuộc tính Neo4j) lệch nhau | Trung bình | Test đồng bộ bắt buộc trong CI (NFR-03); điểm dễ sinh lỗi nhất |
| R5 | Chữ ký cho phép dùng dữ liệu thật trễ (dự kiến 28/08/2026) | Thấp (lãnh đạo đã đồng ý, chờ chữ ký) | Fallback 100% corpus dựng; khóa luận vẫn đứng vững, chỉ mất phần văn phong thật của ĐG6 |
| R6 | Demo chết vì mạng (4 phụ thuộc ngoài) | Trung bình | Chế độ offline có cache + video dự phòng, bắt buộc, làm ở T7 (FR-29) |
| R7 | Phình phạm vi UI | Trung bình | Đường demo trước đã (2.7) + M3 đóng băng |
| R8 | Chi phí API vượt dự toán | Thấp | Đo cost T1 trên 3-5 tài liệu (FR-30); DeepSeek dựng một domain cỡ paper chỉ ~0,3-0,8 USD |
| R9 | Giả định nền "sự cố IT chủ yếu n-ngôi" chưa kiểm chứng | Trung bình | Đếm 50 bản ghi thật ở T1 (5.4); thế thủ đã dựng sẵn, Composition-Risk Ratio là con số chống lưng |
| R10 | Upstream không phải production-track: không release/tag, không PyPI, không Docker, push cuối 05/2026, đội một lab | Trung bình | Ghim commit cụ thể, vendor vào repo khóa luận, tự viết Dockerfile. Đây là lựa chọn có ý thức vì hypergraph là giá trị cốt lõi của đóng góp; chỉ xét lại LightRAG nếu M1 trượt vì upstream chứ không vì thiết kế |

### 6.2 Câu hỏi mở (chương Thảo luận, không phải việc phải giải)

1. Break-glass khi owner vắng mặt: đã chốt sản phẩm không tự động cấp; đánh đổi giữa sẵn sàng dịch vụ và an toàn bàn trong chương Thảo luận.
2. Đường cong recall so với rò rỉ metadata của L1; rò rỉ có kiểm soát là lý do L0 tồn tại.
3. ACL trên artifact dẫn xuất tổng quát: khóa luận giải lát cắt hyperedge, không tuyên bố giải cả lớp bài toán.
4. Định nghĩa 5 tầng của nhãn tin cậy: chốt ở bước UX (chưa có định nghĩa trong tài liệu nguồn).
5. Hành vi recall và độ trễ khi filter là danh sách `match_any` dài (người dùng nhiều scope) và tương tác với ACORN: chưa được tài liệu hóa công khai; đo nhanh nếu số khóa mỗi người dùng vượt ngưỡng chốt ở bước kiến trúc.

## 7. Kế hoạch 8 tuần

| Tuần | Trọng tâm | Mốc |
|---|---|---|
| T1 | Dồn toàn lực cho rủi ro tích hợp (R3): adapter Qdrant/Neo4j (trước khi port: đọc lại seam storage, đối chiếu donor v1.1.1 với main, xác minh `full_scan_threshold`) + POC phân quyền xuyên suốt trên dữ liệu dựng tay với lược đồ vai tối giản 2-3 vai (10-20 tài liệu, 2 nhóm quyền); phác 2 hướng spike R1 (nửa ngày); đo cost; bản 1 trang gửi GVHD | M1 (hẹp: một truy vấn, hai tài khoản, hai kết quả, trên dữ liệu dựng tay) |
| T2 | Lược đồ 8 vai đầy đủ, prompt trích xuất tiếng Việt, bộ vàng 30 câu + nhãn truy hồi vàng, corpus ~40 tài liệu; đo 3 chỉ số n-ngôi + CT-03 trên 50 bản ghi; phần chính spike R1; viết chương 1-2 | |
| T3 | Lõi đóng góp: bảng chính sách L0/L1/L2, ca đa nguồn khác quyền (chốt kết quả spike R1), test bảo mật viết trước; viết chương 3 | |
| T4 | Backend hoàn chỉnh, Permission-Aware Citation, chạy Đo 3 lần đầu; xong chương 3 | M2 |
| T5-T6 | UI theo đường demo, bộ 52 câu, Đo 2; màn đăng nhập và quản lý người dùng (FR-17, FR-24) đóng khung 2-3 ngày. Nếu kẹt, cắt theo thứ tự định sẵn: FR-33 nhãn tin cậy → so sánh 2 cột của FR-18 → FR-22 → phần mở rộng FR-19 (giữ hover tối thiểu) | M3 |
| T7 | Chạy chính thức 3 phép đo (đóng băng kho + câu hỏi + phiên bản); demo offline + video; chương 4 | |
| T8 | Chương 5, slide, diễn tập demo 4 nhịp ít nhất 3 lần có bấm giờ | M4 |

Quy trình làm việc người-AI (ràng buộc nhân lực ở mục 4.3): test viết trước làm đặc tả, AI viết code sau; nhật ký ADR làm phụ lục (mục 2.6), chống câu hỏi "AI code hết thì em làm gì".
