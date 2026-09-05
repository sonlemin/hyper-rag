# ADR-013 - Bản đã khử được phép ra API ngoài; ràng buộc cục bộ gắn với space, không với bộ dữ liệu

**Bối cảnh.** Story 2.11 khử nhạy cảm 50 tài liệu công ty, nạp chúng vào space `real` bằng Qwen 2.5 7B cục bộ, rồi đếm ba tỷ lệ n-ngôi. Kết quả: *Overall N-ary* 369/369 = 100,0% và *Sensitive N-ary* 144/144 = 100,0% - hai con số không nói gì về tri thức, vì bộ trích xuất cục bộ điền vai đều tay tới mức không sinh ra một hyperedge 2 vai nào. Cột `real` vì vậy không lấy lại được mỏ neo Composition-Risk mà story 2.10 mất khi mẫu số chuyển sang bản ghi giả lập.

Đợt đó còn tốn 5 giờ trên máy chủ không GPU và mất 9 trong 50 tài liệu.

Gốc của cả ba thiệt hại là **một lỗi đọc**, và ADR này tồn tại để chốt cách đọc đúng.

NFR-05 viết: *"tài liệu thật **chưa khử nhạy cảm** không được gửi lên API bên thứ ba. Hoặc khử trước bằng công cụ của công ty theo FR-31 [...], hoặc dùng model local. Không có lựa chọn thứ ba."* Đó là **hai đường ngang nhau**, và điều kiện của đường thứ nhất là *đã khử*.

AD-12 của spine buộc space `real` chỉ bind provider cục bộ. Story 2.11 đọc ràng buộc của **một space** thành một cấm đoán cho **cả bộ dữ liệu**, rồi chọn đường cục bộ cho một tập tài liệu đã đi trọn đường khử từ nhiều ngày trước. Đường thứ nhất mở sẵn mà không ai đi.

**Quyết định (05/09/2026).**

1. **Bản đã khử được gửi ra API ngoài.** Điều kiện là *đã đi qua công cụ khử* (`scripts/khu_nhay_cam.py`) và *đã qua kiểm tay* theo thủ tục bắt buộc của NFR-05 (ít nhất 5 tài liệu đầu: tên khách hàng, IP, credential, tên cá nhân). Với 50 tài liệu của story 2.11, cả hai điều kiện đã thỏa từ 04/09 và nhật ký kiểm tay nằm ở `extra/khao-sat-50/nhat-ky-lay-mau.md` (ba lỗ tìm được ngày 04/09 đã sửa và có ca test).

2. **Ràng buộc "chỉ provider cục bộ" gắn với tên space, không với nội dung.** `core.ids.la_space_real` là chỗ luật đó sống, và nó đọc *tên space*. Một bộ dữ liệu đi vào hai space khác nhau chạy hai đường provider khác nhau, và đó là hành vi đúng chứ không phải một lỗ: space là đơn vị cách ly dữ liệu của hệ, còn "đã khử hay chưa" là một tính chất của tài liệu mà không tầng nào của hệ kiểm được tự động.

3. **Space `that_khu`** (story 2.13) chứa **đúng 50 tài liệu đã khử đó**, cùng nội dung từng byte với lần nạp `real`, trích bằng `deepseek-v4-flash`. Tên nó cố ý **không** khớp `la_space_real` (không phải `real`, không kết thúc `_real`), vì nó chạy provider API ngoài có chủ đích. `tests/test_wrapper_llm.py` khóa cả hai chiều: `la_space_real("that_khu")` là `False`, còn `la_space_real("that_khu_real")` vẫn là `True`.

4. **Space `real` giữ nguyên và giữ đường cục bộ.** Nó không bị xóa, không nạp lại, ba tỷ lệ của nó không đổi. Hai space cạnh nhau là cả giá trị của story 2.13: cùng một thư mục nguồn, khác đúng bộ trích xuất, nên chênh giữa hai cột là một **phép đo có đối chứng** cho chênh Qwen/DeepSeek mà story 2.11 chỉ mô tả được bằng ba dấu vân tay trên hai tập khác nhau.

5. **Phép đối chứng đứng trên tập tài liệu có mặt ở cả hai kho, không trên thư mục nguồn** (chốt 05/09 sau vòng review đối kháng). Hai thư mục đúng là cùng 50 file từng byte, nhưng hai *kho* thì không: Qwen làm rơi 9 tài liệu nên kho `real` chỉ có 41. So 41 với 50 là trộn vào chênh lệch cả phần chỉ một vế có, dưới một câu tự khẳng định hai vế bằng nhau. Nên **hai mẫu số, và cả hai đều đúng**: ba tỷ lệ của `that_khu` báo cáo trên **cả 50 tài liệu** (phép đo tốt nhất về hình dạng tri thức thật - không có lý do gì bỏ 9 tài liệu chỉ vì một bộ trích xuất khác đánh rơi chúng), còn **khối đối chứng tính lại trên 41 tài liệu chung**, và trang nói ra chỗ hai mẫu số khác nhau. Phép hạn chế tính được **ngay trong repo** vì hai ảnh rút gọn dùng chung một muối: `doc_key` đã băm của cùng một tên file là cùng một chuỗi. Đó là lợi ích thứ hai của luật cùng muối, và nó là lý do `muoi_id` lệch nhau bị từ chối cả đợt.

**Ranh giới của quyết định này - bốn thứ nó *không* cho phép.**

- **Không** cho bản thô ra API ngoài, kể cả một lần thử. Bản thô ở `txt/` và `tai_lieu_*/` không rời máy; nguồn hợp lệ duy nhất của `that_khu` là thư mục đã dùng cho `real`.
- **Không** nới `la_space_real`. Rào fail-closed của space `real` còn nguyên; ADR này thêm một space, không sửa một luật.
- **Không** cho nội dung tài liệu công ty vào git, kể cả bản đã khử. Ảnh chụp đồ thị của `that_khu` vào repo **chỉ ở dạng rút gọn có muối**, cùng luật với `real` (`.gitignore` chặn `eval/anh_do_thi/that_khu*.json` rồi mở lại `!*_rut_gon.json`; `eval/chup_do_thi.ly_do_tu_choi_dich` chặn ở phía ghi).
- **Không** biến "đã khử" thành một cờ mà code tự tin. Không hàm nào trong hệ kiểm được một tài liệu đã khử hay chưa. Cái đứng giữa bản thô và API ngoài là **thư mục nguồn** cộng file `.space` của nó, tức một quyết định của người chạy có dấu vết đọc lại được, không phải một suy luận của chương trình.

**Phương án đã loại.**

- *Nạp lại `real` bằng DeepSeek, đè lên space cũ.* Mất luôn cột đối chứng. Ba tỷ lệ của `real` là số đã chốt của story 2.11 và chúng có giá trị đúng vì chúng ở lại để so.
- *Đặt tên space là `real_deepseek` hay `real2`.* `real_deepseek` không khớp `la_space_real` (đoạn cuối là `deepseek`) nên nó *chạy được*, nhưng nó đọc như một biến thể của `real` và người soát sẽ tin nó chịu cùng ràng buộc. Tên phải nói ra rằng đây là một space khác, chạy một đường khác.
- *Nới `la_space_real` thành một danh sách cho phép provider theo từng space trong YAML.* Đúng hướng về lâu dài, sai thời điểm: nó đổi một rào bảo mật đang chạy để phục vụ một phép đo. Rào giữ nguyên, phép đo đi vòng qua bằng một space mới - đường mà chính NFR-05 mở ra.

**Hệ quả.**

- Đợt nạp `that_khu` chạy đúng đường của `synth` và `khao_sat`, tức phút chứ không phải giờ, và ba tỷ lệ của nó đứng cùng một bộ trích xuất với cột mốc. Chênh của nó so với `synth` đọc được như một phát biểu về **hình dạng tri thức**, đó là mỏ neo mà story 2.10 mất. Số của đợt 05/09 (`6278dd87`): 50/50 tài liệu vào kho, 720 hyperedge, Overall N-ary 488/720 = **67,8%**, Sensitive 161/225 = **71,6%**, Composition-Risk 0/225. Trên 41 tài liệu chung với `real`: 405/630 = **64,3%** và 154/218 = **70,6%**, tức Qwen thổi hai tỷ lệ đầu lên **+35,7** và **+29,4 điểm phần trăm**.
- **Mỏ neo có, nhưng bị chặn trên bởi lỗ của story 2.12.** Composition-Risk 0/225 nay đọc được vì nó đo trên tài liệu thật bằng đúng bộ trích xuất của `synth`. Nhưng chỉ **6 trong 225** ca nhạy cảm có nổi *một* entity còn lộ ở vùng không nhạy cảm (`synth` 26/81, `khao_sat` 40/151), tức hai tài liệu thật gần như không bao giờ sinh chung một id entity. Số 0 đó nói **chuẩn hóa thực thể chưa làm**, không nói tri thức doanh nghiệp kín, và câu kết luận trên trang phải in chính con số 6/225 chứ không chỉ số 0.
- **50/50 tài liệu vào kho bác bỏ cách phân loại "3 ca giới hạn corpus" của soát tay 05/09.** DeepSeek trích được fact từ đúng ba tài liệu mà soát tay xếp là "bộ trích xuất nào cũng chịu", nên hao hụt của đợt `real` là **18%, cả 9 ca do bộ trích xuất**. Bài học rộng hơn: một suy luận "tài liệu này không còn nội dung" rút từ *một* bộ trích xuất trả rỗng thì không đứng được.
- **Hai thứ vẫn chưa khử được, và trang ba tỷ lệ phải nói cả hai.** Một: `real` và `that_khu` khác nhau **hai** thứ chứ không một - bộ trích xuất (`qwen2.5:7b` với `deepseek-v4-flash`) và model embedding (`bge-m3` với `text-embedding-3-small`). Ba định nghĩa đếm của ADR-012 đọc số vai được điền, hạng theo `content_type` và entity chung giữa các hyperedge, **không đọc một vector nào**, nên model embedding không vào phép đếm nào; nhưng câu "khác đúng một biến" không được đứng trần. Hai: `that_khu` và `synth` vẫn **không cùng trục loại nội dung**, và precision ghép cặp 70,7% đo trên corpus dựng của story 2.5 chứ chưa đo lần nào trên tài liệu công ty.
- Đường nạp API ngoài phải chịu được một đợt dài, nên story 2.13 vá hai lỗ trước khi tiêu tiền: `--uoc-tinh` xem trước chi phí (`api/do_chi_phi.py`), và thử lại 429/5xx ở **đúng một lớp trên mỗi đường gọi** (`adapters/thu_lai.py`, gắn ở `adapters/trich_xuat._trich_mot_chunk` và `adapters/llm_wrapper.bo_embedding`, **không** ở `bo_llm`). "Một lớp" phải đúng cả xuống dưới: `AsyncOpenAI` dựng với `max_retries=0`, vì mặc định 2 của SDK nằm dưới lớp này và nó vừa nhân số request lên ba lần vừa đi vòng qua chính `Retry-After` cùng trần chờ mà lớp trên tôn trọng.
- Ước tính trước đợt so được với hóa đơn, và **đã so**: `--uoc-tinh` đếm 73 lời gọi LLM, đợt thật gọi đúng 73 (số lời gọi là số đếm, không phải ước lượng); token vào ước 93.669 so với 120.848 thật, lệch **+29%** - đúng khoảng "bọc hội thoại của provider 25-30%" mà dòng in ra tự khai, và đúng chiều nó cảnh báo. Ba con số đó ghim ở `tests/test_cham_trich_xuat.py`.
- Ba tỷ lệ của `real` và 50 bản ghi giả lập của story 2.10 **không đổi**. Luật Never của hai story đó còn nguyên.

**Vì sao ADR này tồn tại là một lỗi đọc, và điều đó được ghi ra.** Cái mất của lần đọc nhầm: một đợt nạp 5 giờ trên máy không GPU, 9 tài liệu, và ba tỷ lệ không neo được gì. Cái được: một bộ đối chứng Qwen/DeepSeek trên cùng một thư mục nguồn mà không ai định dựng. Ghi cả hai vào đây để lần sau không ai suy lại từ ràng buộc của một space ra một cấm đoán cho cả bộ dữ liệu.

**Điều kiện đổi.** Quyết định 1 và 2 đổi được khi NFR-05 hoặc AD-12 đổi, và khi đó phải đổi ở PRD/spine trước rồi ADR này ghi lại. Quyết định 3 và 4 là chuyện của story: thêm một space chạy API ngoài trên tài liệu đã khử không cần mở lại ADR này, chỉ cần cùng ba rào - nguồn là thư mục đã khử, tên space không khớp `la_space_real`, ảnh chụp vào repo chỉ ở dạng rút gọn.
