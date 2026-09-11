"""
local-edit-agent 核心模块（库模式集成）。

提供一套模仿 Trae 局部文件修改机制的安全编辑工具：
- matcher      三级降级匹配（精确→空白标准化→difflib 滑动窗）
- hashing      MD5 乐观锁校验
- staging      暂存区（按 resume_id 分桶）
- snapshot     快照备份 + 回滚
- syntax       语法校验（Python/JSON/YAML/JS/HTML）+ 自动回滚
- differ       unified diff 生成
- fs           路径安全校验
"""
