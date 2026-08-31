# vendor/hypergraphrag

- Nguồn: https://github.com/LHRLAB/HyperGraphRAG.git
- Commit ghim: `d587cdf8c3fe2be7719557f845324cb3a321f5e2`
- Cách lấy: clone mới upstream, `git checkout d587cdf`, copy nguyên thư mục package `hypergraphrag/` vào đây (bỏ `__pycache__`). Không symlink, không sửa file nào.
- Quy ước: không sửa `vendor/hypergraphrag/`. Mở rộng bằng subclass trong `adapters/` (override `_get_storage_class()`), không import ngược từ vendor vào code dự án.
