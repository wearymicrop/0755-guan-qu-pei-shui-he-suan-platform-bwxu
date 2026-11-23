# 接口与证据

- `GET /api/health` 返回项目和规则版本。
- `GET /api/{模块}/{样例}` 单独计算到该阶段。模块与样例见深度登记，样例含 `clean`、`dirty`、`dual`。
- `POST /api/runs` 接收 `{"sample":"clean"}`、`{"sample":"dirty"}`、`{"sample":"dual"}` 或 `{"data":{…}}`，可附 `idempotency_key`，返回完整计算和归档 ID。同键绑定不同来源输入返回 422 `IDEMPOTENCY_CONFLICT`，同键同输入重试复用同一归档。
- `GET /api/runs/{id}` 查询不可变归档。`POST /api/runs/{id}/rerun` 用归档输入与当前规则运行。相同规则与来源复用原记录。
- `GET /api/runs/{id}/export` 下载 JSON 证据。内含批次设置、各输入表、原行号、各阶段计算及规则版本。
- `POST /api/runs/{id}/confirmations` 提交 `{"outlet":"201","amount_l":2700}` 确认斗口实配。确认量必须等于归档实配，否则 422 `CONFIRM_MISMATCH`；同一 `(run_id, outlet)` 重复提交不重复累加，返回 `created=false`。`GET /api/runs/{id}/confirmations` 查询已确认清单与累计量。

行号从 1 开始，按各 JSON 数组的位置计。归档键由项目、规则版本、来源名和规范化输入 JSON 计算。输入摘要为规范化 JSON 的 SHA-256。耗时与生成时刻只在首次提交时落库，便于重启后比较同一份记录。
