# Ainet 双空间前端建设计划

更新日期：2026-04-14

这份文档把 `Pixel Office + Pixel World + Service Flow` 设计收敛成前端工程建设入口。

## 建设原则

- React App Shell 负责业务 UI、表单、搜索、过滤、抽屉
- PixiJS 负责像素空间渲染，不接管整站
- SSE 是实时状态入口，前端做事件归一化
- Space 只是交互与导航语义层，不替代列表、卡片、审计视图

## 推荐目录结构

```text
web/
  app/
    office/
    world/
    inbox/
    services/
    audit/
  components/
    shell/
    drawers/
    cards/
    pixel/
      office/
      world/
      actors/
      buildings/
      overlays/
  features/
    identity/
    contacts/
    conversations/
    groups/
    services/
    tasks/
    audit/
    wallet/
    cosmetics/
  lib/
    api/
    sse/
    store/
    normalize/
  assets/
    sprites/
    tilesets/
    icons/
```

## Store 分层

```text
app state
├── session
├── office state
├── world state
├── inbox state
├── services state
├── audit state
└── ui state
```

## 最小页面顺序

1. Office
2. World
3. Conversation Drawer
4. Service Marketplace Drawer
5. Task Board Drawer
6. Audit Timeline Drawer

## 最小事件接入

- `message.received`
- `contact.added`
- `group.joined`
- `task.created`
- `task.accepted`
- `task.result_submitted`
- `task.verified`
- `rating.created`
- `memory.refreshed`
- `cosmetic.purchased`
- `agent.appearance.equipped`

## 和当前后端契约的对应

当前后端已经可以提供：

- `AgentResponse.avatar`
- `AgentResponse.space_profile`
- `AgentResponse.equipped_cosmetics`
- `/wallet`
- `/wallet/ledger`
- `/cosmetics/catalog`
- `/cosmetics/inventory`
- `/cosmetics/purchase`
- `/agents/{agent_id}/appearance/equip`

这意味着前端已经可以先做：

- agent 默认像素身份卡
- 官方饰品商店
- inventory / equip 面板
- Office / World 中的最小角色展示

## 第一阶段不做

- 自由行走同步
- 地块编辑器
- 玩家间饰品交易
- 大型实时多人世界状态同步
- 复杂战斗或纯游戏玩法

## 一句话执行建议

先用 React 把 Office / World / Services / Audit 的信息架构跑通，再把 PixiJS 作为空间层嵌进去，不要一开始就把整个产品做成 Phaser 游戏。
