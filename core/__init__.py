"""Tầng ACL thuần của hyper-rag-copilot.

Chỉ dùng stdlib, không I/O. Chiều import là luật: core/ không import
adapters/, api/, vendor/. Nội dung (lọc, gán mức, lược đồ 8 slot,
PermissionContext, hàm che, chuẩn hóa id, audit port) vào từ story 1.2.
"""
