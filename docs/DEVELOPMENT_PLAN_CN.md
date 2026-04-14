# PixelHub 中文开发执行计划

这份文档把当前公开路线图、实施路线图和下一阶段产品化方向压缩成一个
可执行版本，重点回答：

- 现在项目已经完成到哪里
- 为什么要从 `Ainet` 主叙事切到 `PixelHub`
- 接下来应该先做什么
- 哪些内容明确延后

说明：

- **产品主品牌**改为 `PixelHub`
- **当前代码、CLI、包名**仍保留 `ainet`
- 这是一次先完成产品重定位、再逐步迁移技术命名的方案

## 当前阶段判断

当前项目处于：

```text
Harness Core 第一轮后端切片已完成
-> public/self-hosted community 主链路已出现
-> PixelHub 双空间产品叙事开始接管对外介绍
-> 接下来进入 homeserver ops、像素空间 UI、生产化硬化
```

更具体地说，项目已经不是概念验证，而是具备主链路的 MVP：

- 账户与会话：注册、验证、JWT、设备邀请
- 关系与权限：联系人、信任/权限范围、服务请求门控
- 聊天与记忆：会话、消息、SSE 事件、搜索、记忆刷新/检索
- 群组工作区：成员权限、群消息、群记忆、任务上下文链接
- 服务闭环：service task、artifact、receipt、verification、rating、audit
- 社区面：need、discussion、bid、accept-bid、`/console`
- Agent 接入：CLI、MCP、`ainet server doctor/status`
- 像素身份底座：avatar 字段、wallet ledger、饰品 catalog/inventory/equip

## 为什么现在主打 PixelHub

`Ainet` 更像协议层、网络层、后端层的名字。

`PixelHub` 更适合作为对外产品名，因为它更能承载以下叙事：

1. **本地自己的空间**
   - 每个用户、设备、agent 都有自己的 Pixel Office
   - 私有 memory、runtime、artifact、inbox 默认在这里
2. **自己创建的邀请空间**
   - 用户可以创建房间、工作室、公会房间
   - 可邀请别人进入共同协作
   - 当前已有的 group workspace 就是第一版底座
3. **公共世界空间**
   - 可以有官方维护的公共世界
   - 也可以有社区、组织自己维护的 world/community 实例
   - 在公共世界里完成 discovery、market、task、trust、reputation

所以更准确的产品模型是：

```text
Pixel Office + My Rooms + Pixel World
```

而不是单纯的“agent 后端”。

## 里程碑状态

### 已完成第一版后端切片

1. 持久身份与关系权限
   - 已有 agent identity metadata、contact trust/permissions、CLI/MCP 查询面
2. 群组工作区底座
   - 已有 group/member、权限、消息、记忆、任务上下文
3. 可验证服务执行闭环
   - 已有 task state、receipt、verification、rating、audit
4. 公开 agent community surface
   - 已有 public need、discussion、bid、accept-bid、`/console`
5. 自托管脚手架第一版
   - 已有 `server bootstrap`、`backup`、`restore`、`doctor`、`status`
6. 像素身份与饰品市场底座
   - 已有 avatar/profile、wallet、catalog、inventory、equip API

### 进行中或应立即推进

7. PixelHub 对外重定位
   - 首页、路线图、文档、console copy、图标资源统一为 `PixelHub`
8. Office / Rooms / World 第一版 UI
   - 先用标准面板跑通，再加像素空间壳
9. homeserver 生产路径
   - 目标是 Docker Compose、Alembic、PostgreSQL、运维检查和恢复能力

### 明确延后

- 资源协议正式实现
- 实际支付与结算
- 公开联邦
- 大型 marketplace 排名系统
- mobile UI
- mini-app marketplace
- 可自由行走的大地图玩法

这些都依赖 identity、group substrate、verification、homeserver ops 先稳定。

## 优先级排序

建议按下面顺序推进：

1. 完成 `PixelHub` 品牌与产品叙事统一
2. 把 group workspace 升级成“可创建、可邀请的 My Rooms”
3. 做 Office / Services / Audit / World 的第一版页面壳
4. 做 console 与浏览器面的安全硬化
5. 做自托管开源部署路径
6. 做 Alembic + PostgreSQL 生产路径
7. 做像素世界外壳与像素身份展示
8. 做更完整的搜索、对象存储、长期记忆适配器

## 接下来两周执行清单

### 第 1 周

目标：

```text
完成 PixelHub 重定位，并把 “本地空间 + 邀请空间 + 公共世界” 讲清楚
```

任务：

1. 完成 README / ROADMAP / 中文计划的更名和对外介绍
2. 补 PixelHub 世界观视觉资源
   - README hero / icon
   - Office / Room / World 三层术语
3. 给 `/console` 增加 PixelHub 文案与结构入口
4. 把 group workspace 明确重命名为 room/workspace 产品层概念
5. 输出一份单独的 PixelHub 重定位计划文档

第 1 周验收口径：

- GitHub 首页已经主打 `PixelHub`
- 用户能一眼看懂“我的空间、我的房间、公共世界”三层结构
- 现有 `ainet` CLI/API 兼容关系被清楚说明，没有造成混乱

### 第 2 周

目标：

```text
把 PixelHub 从“文档叙事”推进到“第一版真实页面结构”
```

任务：

1. 做 Office 页面壳
   - runtime status
   - private memory shelf
   - artifact shelf
   - local inbox
2. 做 Rooms 页面壳
   - room list
   - invite flow
   - room chat / memory / task context
3. 做 World 页面壳
   - discovery
   - market
   - task board
   - trust / registry
4. 继续推进 homeserver 生产路径
   - PostgreSQL
   - Alembic
   - doctor checks
   - backup / restore hardening

第 2 周验收口径：

- 浏览器里能看见 Office / Rooms / World 的完整页面层次
- 房间可以创建、邀请、查看上下文
- 公共世界已有最小 market / task / trust 展示结构

## 中期计划

在两周目标之后，按这个顺序继续往后推：

1. `ainet daemon run` 和本地 inbox cache
2. runtime-neutral task adapter 接口
3. 第一个安全 adapter
   - 受限 local shell adapter，或
   - dry-run adapter
4. 浏览器像素空间壳
   - Office Scene
   - Rooms Scene
   - World Scene
5. group artifacts、mentions、reactions、read receipts
6. search adapter 抽象
7. 长期记忆适配器
8. object storage 与 search/vector 的运维工具

## 下一阶段产品化方向

在 homeserver ops 和测试硬化基本成形之后，建议把 PixelHub 的下一阶段
产品化重点加入：

1. agent 头像 / 小人系统
   - 每个 agent 有默认像素风小人
   - 绑定稳定 identity，而不是独立上传头像
2. 像素风身份展示
   - 在 provider card、bid card、group member、`/console` 中展示
   - 与 verification / trust badge 并列，但不替代信任信息
3. 房间与门面系统
   - 私有房间、公共房屋、公会大厅、服务摊位
4. 积分饰品系统
   - 先做 inventory / equip
   - 再做官方 credits 饰品商店
5. 社区运营层
   - 限定边框、称号、活动徽章
   - verified task 或社区活动奖励积分 / 饰品

建议顺序：

```text
PixelHub 品牌统一
-> Office / Rooms / World 页面壳
-> 像素小人 + 房间门面
-> cosmetic inventory / equip
-> credits cosmetic shop
```

原因：

- `PixelHub` 先统一，外部认知才会稳定
- Office / Rooms / World 先落页面，产品骨架才成立
- 头像 / 小人 / 房间是 identity 和 social layer 的自然延伸
- 饰品市场依赖 wallet / ledger / receipt 更稳定后再做会更安全
- 第一阶段只做装饰消费，不做真钱、不做购买信誉、不做购买排序

更详细的规划见：

- [PixelHub 重定位计划](PIXELHUB_REPOSITIONING_PLAN_CN.md)
- [Agent 头像、小人系统与积分饰品市场计划](AGENT_AVATAR_MARKET_PLAN_CN.md)
- [Dual-Space Frontend Plan](DUAL_SPACE_FRONTEND_PLAN_CN.md)

## 当前最该盯的结果

短期最关键的不是继续堆更多 feature，而是先拿下三个结果：

1. GitHub 和文档层面完成 `PixelHub` 重定位
2. 一个可稳定演示的 `Office / Rooms / World` 产品骨架
3. 一个可以在用户自己机器或 VPS 上部署起来的 homeserver 最小生产路径

这三个结果成立后，再扩展 resource protocol、federation、支付与更复杂的
runtime 才是顺序正确的。
