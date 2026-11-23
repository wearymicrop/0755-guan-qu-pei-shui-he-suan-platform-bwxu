# 数据字典

| 输入表 | 关键字段 | 单位及约束 |
|---|---|---|
| config | batch、root、start、end、supply、unit、quantum_l | 批号和渠名为文本，最小刻度为正整升，渠首供水为非负整升 |
| gates | channel、start、end、state | 状态 `open` 或 `closed`，闸令须完整覆盖轮灌区间 |
| channels | channel、parent、inflow、loss、unit | 渠首上游为 `null`，损耗不超过入流，子渠入流和不超过上游净流量 |
| rights | outlet、channel、version、start、end、minimum、ceiling、unit、priority、weight | 保留编码前导零，保底和上限按最小刻度填报，优先级 1 最高，权重为正整数 |
| sources | source、kind、channel、offered、unit | 可选表。`kind` 取 `fresh`（清水）或 `reclaimed`（再生水），channel 须为可达渠段，offered 为非负整升 |
| restrictions | outlet、purpose | 可选表。登记果园、饮水池等再生水受限斗口，outlet 须有本轮有效权证 |

时间含偏移，计算统一为 UTC，采用左闭右开区间。水量支持 `L`、`m3`、`m³`，千位分隔符须成组。空串、水量哨兵和小数升拒收。结果 `_l` 为升，理论配额可为精确分数字符串。

同一渠道按实测子渠入流与损耗计算本段可用量。先按优先级保底，同优先级短缺按保底值比例。所有级别保底后才按级别和权重分配余量。达到权证上限后，对尚未触顶的斗口重新计算权重。最后在本渠按最大余数落整，余数相同时依次比较优先级、斗口文本编码。整数刻度之外的水留在原渠。上游不供水时下游读数留在证据中，水量暂留可核实上游。

`MATCHED` 为对平且无异常，`REVIEW` 为对平但存在需复核事项，`DIFFERENCE` 为计算差异。回执仅在 `MATCHED` 时可下发。交付回执草案与证据文件，不连接闸控设备。

## 双水源汇流规则（sources/restrictions 表存在时启用）

- 再生水厂按注入口渠段申报。系统先求每段的受限子树标记：该段或其任一后代渠段上存在 restrictions 登记的有效斗口即为受限。
- 注入口子树含受限斗口时执行**方案B 保护缓注**：本轮准入量为 0，申报量整体计入"未启用再生水余量"（`reclaimed_withheld_l`），保证果园、饮水池不错过本轮清水供水。
- 注入口子树无受限斗口时执行**方案A 立即补水**：全额准入，沿渠系与清水混合，替代等量清水。
- 汇流后各段按清水/再生水两份账并行核算：损耗、支渠取流、斗口实配、余量均为整升，比例拆分用最大余数守恒。斗口实配再按本段再生水占比拆为 `fresh_l` 与 `reclaimed_l`，逐口满足两者之和等于实配。
- 硬护栏 `RESTRICTED_CONTACT`：受限斗口所在段一旦检出再生水可配量，立即阻断该段受限斗口并留证，回执转为待审。
- 全局恒等式：清水供水 + 外补清水 + 准入再生水 = 清水损耗 + 再生水损耗 + 实配清水 + 实配再生水 + 清水余量 + 再生水余量。`fresh_saved_l` 等于实配中的再生水量，即本轮少取的清水。
- 重试与改派：`POST /api/runs` 可带 `idempotency_key`，同键不同来源输入返回 `IDEMPOTENCY_CONFLICT`。实配确认以 `(run_id, outlet)` 为主键，重复提交返回 `created=false` 且不重复累加，确认量不等于归档实配返回 `CONFIRM_MISMATCH`。
