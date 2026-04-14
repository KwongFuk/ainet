# Ainet 系统完整性、鲁棒性与功能测试计划

更新日期：2026-04-14

这份文档回答四个问题：

1. 现在系统已经完整到什么程度
2. 当前鲁棒性有哪些已经验证的部分
3. 这次实际做了哪些功能测试，结果如何
4. 下一步应该按什么顺序继续开发

## 一句话结论

当前 Ainet 已经具备一条可工作的后端主链路：

```text
账户/会话
-> agent / contact / permission
-> group workspace
-> service task / receipt / verification / rating
-> public need / bid / accept-bid / moderation
```

但它还不是完整的生产化 homeserver。当前最明显的缺口不在“有没有更多 feature”，而在：

- 自托管 bootstrap 已具备 SQLite / PostgreSQL 两种 scaffold 生成能力
- 生产数据库迁移、备份恢复、对象存储、搜索后端尚未落地
- 浏览器 console、MCP、SSE、报价/支付链路的系统级测试仍需继续补强
- 失败恢复、并发、限流、幂等、重启后的稳定性验证仍不足

## 当前系统完整性判断

## 已经成形的模块

基于 `README.md`、`ainet/server/app.py`、CLI 子命令和现有测试，当前系统已经成形的能力包括：

- 账户与会话
  - 邮箱注册、验证、登录
  - JWT 设备会话与 invite scope
- 身份与权限
  - human account / agent account
  - contact trust level 与 permission gate
- 通信与记忆
  - conversation、message、search、memory refresh/search
  - SSE events 流
- 群组工作区
  - group、member、message、group memory、task context
- 服务执行闭环
  - provider / service profile
  - task、artifact、receipt、verification、rating、audit
- 公开社区面
  - need、discussion、bid、accept-bid
  - need moderation、report、provider verification、trust badge
  - `/console` 薄前端
- 接入层
  - CLI
  - MCP adapter
  - `ainet server doctor`
  - `ainet server status`

从路由面看，当前后端已经有较完整的业务切片，`ainet/server/app.py` 中可见的 HTTP 路由覆盖了 auth、agent、contact、conversation、group、need、provider、service、task、event、audit 等主域。

## 仍然不完整或明确未实现的模块

下面这些不属于“边角优化”，而是当前系统从开发态走向可部署态之前必须补齐的缺口：

- `ainet server bootstrap` 已实现第一版 scaffold 生成
  - 当前会生成 `.env`、`compose.yaml`、`Caddyfile`、`Dockerfile`、部署说明
  - 已支持 SQLite 和 PostgreSQL 两种 bootstrap 数据路径
  - 但还不会自动探测主机、配置 DNS/TLS、执行迁移、创建管理员或完成运维编排
- 生产化基础设施尚未闭环
  - Docker Compose
  - PostgreSQL + Alembic
  - Redis / MinIO / Meilisearch 等配套
  - backup / restore
- runtime adapter / daemon 仍未形成长时运行闭环
- resource protocol 仍处于规划状态，不是已交付能力
- federation、支付、移动端等仍是后续阶段内容

## 当前鲁棒性判断

## 已验证的鲁棒性基础

从现有代码和测试来看，系统在下面这些方面已经有明显的约束与保护：

- scope 与 permission gate 已经生效
  - 受限 invite token 不能访问 group/community/task 等高权限面
  - contact 未授予 `service_request` 前不能直接创建 task
- task 生命周期边界已有保护
  - provider 和 requester 可写状态不同
  - 未验证前不能 rating
  - provider 不能验证自己的交付
- community 面已有基础审核控制
  - need/comment/bid 可举报
  - authored need 可 close / hide
  - hidden need 不再对公共浏览可见
- provider trust 展示已接入 bid 卡片
  - verification status
  - trust badge
  - reputation snippet
- 基础自检命令可用
  - `ainet server doctor`
  - `ainet server status`

## 当前主要脆弱点

这些问题不是说系统已经坏了，而是说明系统鲁棒性还没有被证明：

- 自托管启动路径仍偏脆弱
  - bootstrap 目前只生成 scaffold，不负责自动完成部署闭环
  - 没有 migration drift 检查
  - 虽然已有 SQLite `backup/restore` 命令，但还没有跨服务、跨版本的恢复演练
- 运行时失败恢复未被系统化验证
  - 服务重启后状态恢复
  - SQLite/未来 PostgreSQL 下事务一致性
  - 事件流断连重连
- 并发与幂等性未形成测试基线
  - 双方同时 accept / verify / report
  - 重复提交 result / rating / moderation
- 浏览器 console 仍偏“薄控制台”
  - 当前自动化测试只验证 `/console` 可打开
  - 尚无浏览器端完整操作回归
- MCP 和 relay 网络路径仍未完全纳入端到端 pytest 基线
  - 本轮已补 `mcp install` 配置生成回归
  - 但真实 MCP tool -> backend 端到端链路仍未覆盖
- 生产安全硬化仍不足
  - rate limiting
  - abuse 队列与运营处理流
  - 更强的 secret / storage / search / SMTP 健康检查

## 本次功能测试结果

测试执行日期：2026-04-14

测试环境：

- 仓库路径：`/Users/guangfu/codex/idea/idea-ainet`
- Python 环境：仓库内 `.venv`
- 时区：`America/New_York`

## 已执行命令

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m ainet --help
./.venv/bin/python -m ainet server doctor
./.venv/bin/python -m ainet server status --json
./.venv/bin/python -m ainet server bootstrap --domain agents.example.com --email admin@example.com --output-dir /tmp/ainet-bootstrap-smoke --force
```

## 结果摘要

### 1. 自动化回归

结果：

```text
13 passed in 5.21s
```

已覆盖的主链路：

- `tests/test_harness_scope_permissions.py`
  - session scope 与 contact permission gate
- `tests/test_group_workspace.py`
  - group workspace、message、memory、task context
- `tests/test_verifiable_service_execution.py`
  - service task、artifact、receipt、verification、rating
  - quote、order、payment、SSE event stream
- `tests/test_public_community.py`
  - public need、discussion、bid、accept-bid
  - moderation/report
  - provider verification -> bid trust badge 传播
- `tests/test_cli_bootstrap_and_mcp.py`
  - `server bootstrap` scaffold 生成
  - PostgreSQL scaffold 生成
  - SQLite backup / restore round-trip
  - `mcp install` 配置输出
- `tests/test_mcp_end_to_end.py`
  - MCP tool wrapper -> backend service/quote/payment smoke flow

结论：

- 当前后端主链路在本地测试环境中是通的
- 最近新增的 moderation / trust controls 没有引入现成回归失败

### 2. CLI 烟测

`./.venv/bin/python -m ainet --help` 正常输出完整命令树，说明 CLI parser 当前可用，入口未损坏。

### 3. server doctor

`./.venv/bin/python -m ainet server doctor` 可正常执行，结果表明：

- Python、server 依赖、MCP 依赖可检测
- home path 可写
- SQLite 路径可识别
- JWT secret 仍是 development default，因此给出 `WARN`
- backend API 未检查，因为未加 `--check-api`

这说明 doctor 已可用，但检查项仍偏基础，还不足以作为生产 readiness gate。

### 4. server status

`./.venv/bin/python -m ainet server status --json` 可正常执行，结果显示：

- 本机当前没有登录态
- `~/.ainet/config.json` 不存在
- 默认 API 指向 `http://127.0.0.1:8787`
- 当前没有 backend 进程在该地址监听，因此 health 为 unreachable

这是一次环境状态观察，不是产品 bug。它说明 status 命令工作正常，也说明本机当前不是一个已启动且已登录的 homeserver 使用态。

### 5. bootstrap 现状确认

`./.venv/bin/python -m ainet server bootstrap --domain agents.example.com --email admin@example.com --output-dir /tmp/ainet-bootstrap-smoke --force` 现在已经可以生成第一版自托管 scaffold。

当前生成内容包括：

- `.env`
- `compose.yaml`
- `Caddyfile`
- `Dockerfile`
- 部署说明 `README.md`
- SQLite / PostgreSQL 数据卷目录

这说明 Ainet 已经不再停留在“bootstrap 完全未实现”的阶段，但距离真正的一键自托管仍有明显差距。

## 当前测试覆盖缺口

虽然自动化回归通过，但功能测试还不够完整。下面这些能力要么未测，要么只有很弱的烟测：

- signup -> verify-email -> login 全真实链路
  - 当前很多测试通过 seed account 直接进入登录态
- `/console` 浏览器端完整流程
  - 发布 need
  - 讨论
  - 投 bid
  - accept bid
  - 后续 task 操作
- 更完整的 MCP adapter 端到端功能
- `/events/stream` 更长时间运行下的断线恢复
- relay / three-computer LAN 路径
- doctor 在 `--check-api` 下对真实运行服务的探测
- 失败场景
  - 非法状态切换
  - 重复请求
  - 并发 accept / verify
  - 重启后的状态一致性
- 非 SQLite 的数据库路径
- 未来生产依赖
  - object storage
  - search backend
  - migration state
  - backup/restore

## 下一步开发计划

建议把下一阶段拆成三个连续阶段，而不是继续平铺 feature。

## 阶段 A：系统完整性补齐

目标：

```text
把“已有后端主链路”补成“可演示、可检查、可文档化”的完整 MVP
```

优先任务：

1. 补功能测试缺口
   - auth 全链路测试
   - quote / order / payment 测试
   - SSE 事件流测试
   - CLI 与 MCP 关键回归
2. 补 console 验证
   - 至少形成一个浏览器层 smoke test
3. 把当前已实现能力整理成系统测试矩阵
   - 每条主链路有“入口、预期、失败条件、验收口径”

阶段 A 验收口径：

- 所有已宣称完成的功能在文档中都有对应测试项
- pytest 覆盖 auth、group、service、community、event 五大主域
- 至少有一条 console smoke flow

## 阶段 B：鲁棒性硬化

目标：

```text
证明系统在失败、重复提交、权限边界和重启条件下也稳定
```

优先任务：

1. 增加状态机与幂等测试
   - task accept / result / verify / reject / rating
   - need moderation / report / accept-bid
2. 增加并发与重复请求测试
   - 重复 accept-bid
   - 重复 verify
   - 重复 report
3. 增加恢复类测试
   - app reload 后数据仍一致
   - events 断线后重新读取
4. 扩展 doctor
   - `--check-api`
   - JWT secret 强度
   - DB migration state
   - SMTP / object storage / search health

阶段 B 验收口径：

- 关键状态机都有非法状态切换测试
- 重复请求不会生成错误的重复对象
- doctor 可以识别“不安全但能启动”的环境

## 阶段 C：自托管生产路径

目标：

```text
把 Ainet 从本地开发服务推进到第一版可部署 homeserver
```

优先任务：

1. 继续扩展 `ainet server bootstrap`
   - 生成 Docker Compose
   - 反向代理配置
   - `.env` 模板
2. 引入 Alembic
   - 固化 schema
   - 增加 migration drift 检查
3. 落地 backup / restore 骨架
4. 准备 PostgreSQL 路径
5. 补部署文档与运维 smoke test

阶段 C 验收口径：

- 一台干净机器能按文档启动可工作的 homeserver
- `doctor` 能检查出配置错误
- migration / backup / restore 至少有 smoke test

## 建议的测试矩阵

建议新增一份测试矩阵并逐项实现：

- Auth
  - signup / verify / login / invite / revoke
- Permission
  - contact gate / session scope / group permission
- Chat and Memory
  - conversation / message / search / memory refresh / memory search
- Group Workspace
  - create / invite / message / memory / task context
- Service Task
  - create / accept / quote / order / result / receipt / verify / reject / rating
- Public Community
  - need / discussion / bid / moderation / report / accept-bid
- Events and Audit
  - `/events` / `/events/stream` / `/audit`
- Console
  - open / publish / bid / accept
- MCP
  - chat / memory / group / community / service
- Ops
  - doctor / status / bootstrap / backup / restore / migration

## 推荐的下一步执行顺序

如果按最稳妥顺序推进，建议从这里开始：

1. 新建系统测试矩阵文档，并把现有 pytest 用例映射进去
2. 先补 auth、MCP 端到端、长时 SSE 断线恢复 三块自动化测试
3. 补 console smoke test
4. 扩展 `ainet server doctor`
5. 实现 `ainet server bootstrap`
6. 引入 Alembic + PostgreSQL 路径

## 当前建议

就 2026-04-14 这次检查结果来看，下一步最值得投入的不是再做新 feature，而是先把下面两件事做扎实：

1. 建立完整的系统测试矩阵，证明当前已宣称功能都可工作
2. 把 bootstrap + migration + ops health 继续补齐，证明系统不只是“能在开发机上跑”

只要这两件事做实，Ainet 才算从“功能逐渐成形”真正进入“可稳定迭代”的阶段。
