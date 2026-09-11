"""
local-edit-agent MCP 服务包。

提供一套模仿 Trae 局部文件修改机制的 MCP 工具：
- view            读取文件指定行范围
- str_replace     精确/降级匹配的局部替换（核心工具）
- git_snapshot    修改前 git 快照备份
- validate_syntax 语法校验与自动回滚
- apply           用户确认后将暂存的 diff 落地写入
- rollback        回滚上一次快照

永不直接输出完整文件，所有改动通过局部替换工具完成。
"""