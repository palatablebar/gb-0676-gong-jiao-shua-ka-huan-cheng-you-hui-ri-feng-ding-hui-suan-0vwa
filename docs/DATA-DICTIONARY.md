# 数据定义

刷卡事件以event_id去重，card保留前导零。route支持1路/01等别名。event_time必须带偏移；业务日为Asia/Shanghai。result仅success可作为行程，失败刷卡隔离。reported为实扣人民币元。票价F1至2026-11-01前为2元，F2为2.50元。

跨线路换乘必须在上一次实际付费行程后60分钟内，恰好60分钟排除。同线路无优惠；零付费行程不能延长换乘锚点。先扣1元换乘优惠，再对卡号业务日施加6元封顶。每条基本票价=实算扣费+换乘优惠+封顶优惠。

业务ID和超大整数按文本保形；Decimal参与数量金额计算，对外序列化为字符串。哨兵集合定义在app/values.py，缺失值不能当零。所有时间带UTC偏移，先转UTC比较，业务日按指定地区划分。区间统一[start,end)。重复业务键保留第一条、完全相同行计重复；值冲突行隔离且保留原值。空文件、全空白、仅表头分开拒绝。

运行清单包括输入sha256、规则版本、参数、生成时刻与耗时。源行编号以CSV解析器的物理结束行号表示，引号内换行不增加记录数。输入超过4MB返回413，非法表头和类型返回422，失效版本复核返回409。

## 票价版与跨版换乘链（TRAP-27）

票价窗由参数 `fares` 给出，每条含 `version/start/end/amount`，区间统一半开 `[start,end)`；整表必须无缝且不重叠，否则 `FARE_WINDOW_INVALID` 整批失败、不写库。每条腿在刷卡时点选版，派生字段：

- M3：`fare_version`、`base_fare`、`fare_effective_from/to`、`fare_basis`（选版依据）。
- M4：`chain_id`（同卡同业务日一条链）、`chain_versions`（链内版本序）、`chain_cross_version`（是否跨版）、`chain_basis`。
- M5：`anchor_fare_version`（锚点所属版，仅用于时间窗/换线）、`discount_fare_version`（本腿优惠口径版）、`version_basis`；可选 `version_params` 按版覆盖 `transfer_discount/transfer_minutes/daily_cap`，缺省回退全局参数；日封顶跨版累计不清零。
- M6：`per_version` 分版应扣/实扣/差额，分版合计等于总额。
- M7：`fare_windows` 与 `settlement_versions`（复用 M6 分版口径）并入封存 `sha256`。

证据导出在 accepted/quarantine 外增加 `fare_window`、`settlement_version` 两类证据行。`switch.csv` 的票价窗随 `SWITCH_PARAMS` 注入，调整时点为 2026-11-16T08:00:00+08:00。