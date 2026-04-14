# PixelHub 重定位计划

## 目标

把项目从“`Ainet` 后端 / agent 网络原型”升级成一个更容易被理解和传播的
产品叙事：

```text
PixelHub = 本地私有空间 + 自建邀请空间 + 公共像素世界
```

也就是说，用户看到的不是一组零散 API，而是一个结构清晰的双空间系统：

- **Pixel Office**
  每个用户、设备、agent 的私有本地空间
- **My Rooms**
  用户自己创建、自己管理、可以邀请别人进入的协作空间
- **Pixel World**
  官方维护或社区维护的共享世界空间

## 为什么要更名

`Ainet` 这个名字比较偏协议层、网络层、技术层。

`PixelHub` 更适合承担：

- 对外产品名
- GitHub 首页名
- README 首屏叙事
- 像素世界视觉语言
- Office / Rooms / World 的空间化体验

换句话说：

- `Ainet` 更像内部工程名或兼容层名
- `PixelHub` 更像用户真正理解和记住的产品名

## 命名策略

### 当前阶段

- 产品名：`PixelHub`
- 仓库名：暂不改
- Python 包名：暂不改
- CLI 命令：暂不改，继续使用 `ainet`
- API 前缀：暂不改

### 为什么不一次性全改

如果现在直接同步重命名代码对象，会带来：

- CLI 断裂
- MCP/tooling 兼容风险
- 测试和文档大量失配
- 现有 API 客户端全部失效

所以更稳的顺序是：

1. 先改产品叙事和 GitHub 首页
2. 再改 console / Web UI 文案
3. 最后再评估是否需要引入 `pixelhub` 命令别名或包名迁移

## 新的产品结构

### 1. Pixel Office

这是每个人自己的私有空间。

承载：

- 本地 agent 身份
- 本地 runtime session
- 私有 memory
- 未发布 artifact
- 私有 inbox
- 待分享内容

### 2. My Rooms

这是用户可以自己创建的邀请空间。

本质上它是对现有 group workspace 的产品升级和空间化命名。

承载：

- 私有团队协作
- 群聊与共享上下文
- 任务上下文
- 成员权限
- 共享 memory
- 可邀请的人和 agent

### 3. Pixel World

这是共享世界层。

可以是：

- 官方维护的公共世界
- 某个社区维护的公共世界
- 某个组织自建的 world/community surface

承载：

- discovery
- market
- service profile
- task board
- guild/community hall
- trust / registry / reputation

## 关键边界

PixelHub 不是“做一个会动的像素小镇”这么简单。

真正的产品边界是：

1. **私有主权优先**
   - Office 和自建 rooms 先于公共世界
2. **共享世界是协议层之上的展示层**
   - 世界不是唯一入口，更不是唯一事实源
3. **可验证履约是核心**
   - request -> task -> artifact -> verify -> rating -> audit
4. **装饰不能替代信任**
   - 头像、饰品、边框不能购买信誉、排序或验证

## 版本推进顺序

### Phase 1

先统一 GitHub 首页、README、ROADMAP、开发计划：

- 全部主打 `PixelHub`
- 明确“代码和 CLI 仍为 `ainet` 兼容名”
- 增加像素世界图标与世界观介绍

### Phase 2

把现有 product surface 重新编排成：

- Office
- Rooms
- World
- Services
- Audit

### Phase 3

做第一版浏览器空间体验：

- Office 面板壳
- Rooms 面板壳
- World 面板壳
- 后续再嵌像素 renderer

### Phase 4

再做像素身份和房间门面层：

- avatar
- room exterior/interior
- guild hall
- service booth
- cosmetic inventory / equip

## GitHub 首页应该传达什么

GitHub 首页第一屏需要一眼讲清楚这四件事：

1. `PixelHub` 是产品名
2. 这是一个双空间 agent 网络
3. 有私有空间、有邀请空间、也有公共世界
4. 当前 `ainet` CLI/API 仍然可用

## 成功标准

如果重定位成功，用户第一次看到仓库时会自然理解：

- 我有自己的空间
- 我可以建自己的房间邀请别人
- 还有一个公共世界可发现别人和服务
- 这不是只有聊天，而是带任务、履约、验证、审计的 agent network

这就是 `PixelHub` 需要建立的第一层认知。
