# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

样例 `switch.csv` 自动携带 `SWITCH_PARAMS`（含跨调整时点的 `fares` 票价窗）；请求显式传 `parameters` 时以请求为准。票价窗存在缝隙/重叠返回422 `FARE_WINDOW_INVALID` 且不写库。run_id 由输入摘要、参数、规则版本内容寻址，同调整重跑幂等复用同一批次，已复核批次的 payload 不会被重跑覆盖。导出证据含 accepted、quarantine、fare_window、settlement_version 四类行。
