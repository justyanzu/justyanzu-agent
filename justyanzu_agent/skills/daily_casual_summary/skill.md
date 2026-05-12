# Casual 每日总结（22:00）

## 用途

在宿主进程按配置的时间（默认本地 **22:00**）触发一次 **今日对话总结**。数据来源由运行器自动拼接，你（模型）只需根据下方材料输出总结。

## 数据来源（由运行器注入，无需自行读盘）

1. **当前会话内存**：`casual_agent` 在进程内的 `Memory` 列表中，已按「今日」规则筛选后的 `user` / `assistant` 片段。  
2. **今日已保存存档**：运行器会扫描 `conversations/casual_agent/memory_*.txt`（JSON 数组），仅保留 `time` 字段以 **当日 `YYYY-MM-DD`** 开头的条目，跨文件合并、按时间排序、去重。

若某条消息无 `time`（例如部分 OpenRouter 存档），运行器对 **当前内存** 中本会话且 `session` 起始日即为今日时，可整段纳入；已保存文件侧无 `time` 的条目将被跳过以避免误标日期。

## 输出要求

- 使用与用户一致的语言（一般为 **中文**）。  
- 结构清晰，建议包含：今日 **主要话题**、**用户目标或问题**、**已给出的要点或结论**（如有）、**未决/可跟进事项**（如有）。  
- **严禁编造**：材料中未出现的内容不要写进总结。  
- 长度适中（例如 200～600 字），除非材料极多可适当加长。  
- 不要输出「以下为总结」以外的元废话；不要假装执行了读文件以外的操作。

## 辅助脚本（人工 / 调试）

目录内 `collect_today_memory.py` 可单独运行，将「今日磁盘存档正文」打印到 stdout，供检查拼接结果：

```bash
python skills/daily_casual_summary/collect_today_memory.py
python skills/daily_casual_summary/collect_today_memory.py --date 2026-03-29
```

## 配置（config.ini）

在 `[MAIN]` 中开启并可选调整时间：

```ini
daily_casual_summary = True
daily_casual_summary_hour = 22
daily_casual_summary_minute = 0
```

宿主需在 **长期运行** 的 CLI/API 进程中才会按时触发；进程未运行则不会执行。
