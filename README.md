# lark-agent

飞书私聊自主智能体最小闭环,2026-07-04 凌晨与 Claude 一起实操验证跑通(3 轮对话,端到端 2.0-2.4s/条)。

```
你在飞书发消息
  → lark-cli 事件流(WebSocket 长连接,零公网/零 webhook)   ← 耳朵
  → agent.py 组装上下文
  → LiteLLM 网关(ssh 隧道 → dev 127.0.0.1:4000)            ← 大脑
  → lark-cli im +messages-reply                              ← 嘴
  → 飞书里收到"小爪"的回复
```

## 前置条件

- Mac 上已装并登录 `lark-cli`(应用 claude-cli,bot 身份)
- dev 主机上的 LiteLLM 网关在跑(只绑本机回环)

## 快速开始

```bash
# 1. 打通大脑:本地 14000 → dev litellm 4000
ssh -f -N -L 14000:127.0.0.1:4000 dev

# 2. 配置(key 不进 git)
cp .env.example .env   # 填 LITELLM_API_KEY(dev 上 LITELLM_MASTER_KEY)

# 3. 跑
python3 agent.py                 # 默认 15 分钟窗口,不限条数
python3 agent.py --minutes 0     # 常驻,Ctrl-C 退出
python3 agent.py --only-sender ou_xxx   # 只理特定的人
```

然后在飞书给 claude-cli 机器人私聊发消息即可。

## 配置项(.env 或环境变量)

| 变量 | 默认 | 说明 |
|------|------|------|
| `LITELLM_API_KEY` | 必填 | LiteLLM 网关 key |
| `LITELLM_BASE_URL` | `http://127.0.0.1:14000/v1` | OpenAI 兼容端点 |
| `LARK_AGENT_MODEL` | `deepseek/deepseek-chat` | 换 kimi/qwen/minimax 改这里 |
| `LARK_AGENT_MINUTES` | `15` | 运行窗口,0=常驻 |
| `LARK_AGENT_MAX_MSGS` | `0` | 处理条数上限,0=不限 |
| `LARK_AGENT_ONLY_SENDER` | 空 | 发送者 open_id 白名单 |

## 部署在 dev(生产常驻)

小爪跑在 dev 主机的 **systemd user service** 里,和它未来要接管的
`openclaw-gateway.service` 并排落户。选 systemd 而非 Docker 的原因:litellm 绑在宿主机
`127.0.0.1:4000`(容器要 host 网络才够到)、lark-cli 登录态是 `~/.lark-cli` 原生文件、
`event consume` 有本地 bus daemon——裸机 systemd 零网络翻译、零挂载卷,最省心;dev 本就"全 systemd"。

```
~/lark-agent/
  agent.py  cookbook.md  run.sh  memory.db  .env
~/.config/systemd/user/lark-agent.service   # ExecStart=run.sh, Restart=always
```

登录态:lark-cli 在无头 Linux 上把 master.key 落成**文件**(非 keychain),
`config init --app-id … --app-secret-stdin` + `auth login --domain all` 即可;
app secret 从开发者后台复制,user token 走设备码(点一次 URL)。Mac 与 dev 各持独立 token,
各自 7 天滚动续期,互不依赖。

运维命令:
```bash
systemctl --user status   lark-agent      # 状态
systemctl --user restart  lark-agent      # 重启
journalctl --user -u lark-agent -f        # 或 tail -f ~/lark-agent/agent.log
```

## 已知局限

- 排队中(还没开始处理)的消息在进程重启时会丢——事件是瞬时的,不重投给新进程。
- 极端崩溃时序下宁可保守:确认后崩溃 → 操作可能没执行(重新说一遍即可),绝不会重复执行。
- 停进程用 SIGTERM(systemd stop 已是 SIGTERM),**别 kill -9**(会泄漏 lark-cli 服务端订阅)。
- **启动竞态**:`event consume` 冷启动时偶发 exit code=2(bus daemon 初始化未就绪),
  看门狗指数退避重启会在 ~30s 内连上;崩溃自愈重启通常一次到位。

## 愿景与成长路线

**定位:飞书生态的对话入口。** 小爪的耳朵和嘴已经是 lark-cli,手也应该是 lark-cli——
200+ 命令 / 18 个业务域(文档、多维表格、日历、邮件、妙记、任务、审批……)就是现成的工具箱。
终局:接管 openClaw 的飞书通道职责(审批卡/群路由),openClaw 退役。

| 阶段 | 目标 | 验收 |
|------|------|------|
| 1. 生态之手 | 给小爪一个受控执行 lark-cli 的工具:**读操作放行,写操作"预览→飞书里确认→带 --yes 执行"**(复用 CLI 自带的 dry-run / exit-10 安全协议)。同步验证 user 身份调用 + token 续期(生态大半在 user 身份下,2h 过期是常驻的命门) | "明天有什么安排" / "把这段记进实践手记" / "台账里昨天几条 critical",一句话跑通 |
| 2. 站稳 | 无界 consume 流式消费(消除漏消息缝隙)、SQLite 持久记忆、断线自愈 | 连跑 72h 不漏、不崩、重启不失忆 |
| 3. 搬家上 dev ✅ | ~~bot 登录态无头迁移~~(重新设备码授权,token 不绑机)、~~docker 化~~→**systemd user service** 钉版 lark-cli 1.0.65、litellm 直连(免隧道);租户问题 phase 3 不涉及(仍用 claude-cli 个人应用),留待 phase 5/6 | ✅ Mac 关机小爪照跑;崩溃 systemd 5s 自愈实测 |
| 4. 卡片 | 交互卡片 + card.action.trigger 回调实测;写操作确认从"回消息"升级成"点按钮" | 点卡片按钮,小爪收到回调并执行 |
| 5. 试点 | 接管一条非关键链路(巡检日报),与 openClaw 并行灰度一个月 | 一个月零事故 |
| 6. 接管 | 层2恢复审批卡双发灰度 → 切换 → openClaw 下线 | 生产闭环在小爪上稳定运行 |

依赖:1、2 可并行;3 在 4 前(卡片要在常驻环境测);5、6 串行。
最大不确定性:~~user token 续期(阶段1)~~已证、~~登录态迁移(阶段3)~~已证(文件化+重授权)、卡片回调实测(阶段4)、租户迁移(阶段5/6 接管 openClaw 时)。
