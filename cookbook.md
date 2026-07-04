R=只读直接执行,W=写操作会被安全闸拦下转人工确认

## im
- [W] `im +messages-send --chat-id <oc_xxx> --text "<内容>" --as bot`
  发文本消息到群;user/bot 均可;--user-id <ou_xxx> 可发私聊(与 --chat-id 互斥);支持 --idempotency-key 防重发
- [W] `im +messages-send --chat-id <oc_xxx> --markdown "<md文本>" --as bot`
  发 markdown 富文本(自动包装为 post);也支持 --image/--file/--video(本地相对路径或 URL,绝对路径被拒);user/bot 均可
- [W] `im +messages-reply --message-id <om_xxx> --text "<内容>" --as bot`
  回复某条消息;--reply-in-thread 进话题流;同样支持 --markdown/--image/--file;user/bot 均可
- [R] `im +chat-search --query "<群名关键词>" --as user`
  按关键词搜可见群拿 chat_id;user/bot 均可(--exclude-muted 仅 user);默认还会按成员名搜,可 --disable-search-by-user
- [R] `im +chat-list --as bot --page-size 100`
  列出当前身份已加入的群;--types=p2p,group 含单聊(p2p 仅 user 身份);--sort active_time 按活跃排序
- [R] `im +chat-messages-list --chat-id <oc_xxx> --start <ISO8601> --end <ISO8601> --order desc --as user`
  读群消息(默认附 reactions,--no-reactions 关闭);bot 身份可能解析不出发送者姓名(显示 open_id),建议 --as user;--user-id 可读 P2P;--download-resources 下载附件到 ./lark-im-resources/
- [R] `im +messages-search --query "<关键词>" --chat-id <oc_xxx> --start 2026-06-01T00:00:00+08:00 --page-all --as user`
  跨群搜消息;仅 user 身份;可按 --sender/--sender-type/--chat-type/--is-at-me/--include-attachment-type 过滤;时间必须带时区偏移
- [R] `im +messages-mget --message-ids <om_xxx,om_yyy> --as user`
  按 ID 批量取消息(最多 50 条),自动展开 thread 回复;user/bot 均可
- [R] `im +threads-messages-list --thread <om_xxx|omt_xxx> --as user`
  列话题(thread)内消息,自动把消息 ID 解析成 thread_id;user/bot 均可;默认 asc
- [R] `im +chat-members-list --chat-id <oc_xxx> --as bot`
  列群成员,分 users[]/bots[] 两桶;user/bot 均可;--page-all 全量分页
  ⚠ 响应信封 {ok, identity, data},数据取 .data;通用 flags:--as user|bot、--jq、--format、--dry-run。搜消息(+messages-search)仅 user 身份;bot 读消息时发送者姓名可能显示为 open_id(可见范围问题),读消息优先 --as user。发文件/图片用 cwd 相对路径,绝对路径和 .. 会被拒;时间参数用 ISO 8601 且搜索必须带时区偏移。

## calendar
- [R] `calendar +agenda --as user`
  查今天日程(默认今天整天)。必须 --as user,bot 身份只会拿到空日历
- [R] `calendar +agenda --as user --start 2026-07-04T00:00:00+08:00 --end 2026-07-04T23:59:59+08:00`
  查明天/指定日期日程;--start ISO 8601,--end 默认为 start 当天结束。--as user 必须
- [R] `calendar +agenda --as user --start 2026-06-29T00:00:00+08:00 --end 2026-07-05T23:59:59+08:00`
  查本周日程(周一为一周首日),跨天用 start+end 覆盖整周。--as user 必须
- [R] `calendar +search-event --as user --query <关键词> --start 2026-07-01 --end 2026-07-31`
  按关键词/时间范围搜日程,仅返回 event_id/主题/时间;详情走 events get。仅支持 --as user
- [R] `calendar +freebusy --as user --start 2026-07-03T09:00:00+08:00 --end 2026-07-03T18:00:00+08:00`
  查忙闲+RSVP 状态;--user-id ou_xxx 可查他人,默认当前用户。user/bot 均可但查用户日程用 --as user
- [R] `calendar +suggestion --as user --start 2026-07-03T14:00:00+08:00 --end 2026-07-03T18:00:00+08:00 --duration-minutes 60 --attendee-ids ou_xxx,ou_yyy`
  根据模糊时间范围推荐可用时间块;查会议室前无明确时间必须先走这一步
- [W] `calendar +create --as user --summary <标题> --start 2026-07-04T14:00:00+08:00 --end 2026-07-04T15:00:00+08:00 --attendee-ids ou_xxx,oc_xxx --description <描述>`
  创建日程并邀请参会人(ou_用户/oc_群/omm_会议室);时间 ISO 8601;--as user。风险级 write,不需 --yes
- [W] `calendar +update --as user --event-id <event_id> --start <ISO> --end <ISO> --add-attendee-ids ou_xxx --remove-attendee-ids ou_yyy`
  更新日程/增删参会人;--start 与 --end 必须成对;重复日程须用具体实例 event_id;--notify 默认 true。write
- [R] `calendar events get --as user --calendar-id <cal_id> --event-id <event_id> --need-attendee`
  获取日程完整详情(search 结果只有摘要);--need-attendee 为存在即 true 的布尔 flag
- [R] `calendar calendars primary --as user`
  查用户主日历,拿 calendar_id 供 events get 等使用。--as user
- [R] `calendar +room-find --as user --dry-run ...`
  针对明确时间块找可用会议室;无明确时间禁止直接调,先 +suggestion。read
  ⚠ 默认加 --as user:bot 日历是空的,+agenda/+freebusy 用 bot 会拿空结果,+search-event 只支持 user。时间一律 ISO 8601 带时区(+08:00);日期↔时间戳转换必须用 date 命令算,禁止心算。响应信封 {ok,identity,data},数据在 .data;可加 -q '<jq>' 过滤;修改后 API 最终一致,验证前等 2 秒。

## docs
- [R] `docs +search --as user --query "<关键词>" --page-size 20`
  搜索文档/Wiki/表格文件(Search v2);仅支持 --as user,bot 不可用;结果在 .data 下,分页用 --page-token
- [R] `docs +fetch --as user --doc "<文档URL或token>"`
  读整篇文档内容,默认 scope=full、detail=simple、XML 输出;文档操作默认 --as user
- [R] `docs +fetch --as user --doc "<URL>" --doc-format markdown`
  以 Markdown 导出文档正文,适合给 LLM 阅读或转发
- [R] `docs +fetch --as user --doc "<URL>" --scope outline`
  只列文档标题大纲,长文先看结构;--max-depth 可限层级
- [R] `docs +fetch --as user --doc "<URL>" --scope keyword --keyword "foo|bar" --context-before 1 --context-after 1`
  按关键词(支持 | 分支/正则回退)局部读取,附带前后邻块上下文
- [R] `docs +fetch --as user --doc "<URL>" --detail with-ids`
  读取并带 block_id,做局部编辑(block_insert_after/replace/delete)前必跑
- [W] `docs +create --as user --title "<标题>" --doc-format markdown --content @notes.md`
  用本地 Markdown 文件创建文档;--content 支持 @file 和 - (stdin);--parent-token 指定文件夹/Wiki 节点
- [W] `docs +create --as user --title "<标题>" --content '<p>正文</p>'`
  用 DocxXML 创建文档(默认格式,支持更丰富块类型);普通 write,无需 --yes
- [W] `docs +update --as user --doc "<URL>" --command append --doc-format markdown --content @append.md`
  往已有文档末尾追加 Markdown 内容;overwrite 同形式但整篇覆盖(慎用)
- [W] `docs +update --as user --doc "<URL>" --command str_replace --pattern "<旧文本>" --content "<新文本>"`
  精准替换文本(XML 模式 pattern 为行内文本);--content 为空则删除匹配
- [W] `docs +update --as user --doc "<URL>" --command block_insert_after --block-id <blockId> --content '<p>新段落</p>'`
  在指定 block 后插入内容;block-id 需先 +fetch --detail with-ids 获取;-1 表示文档末尾
- [W] `docs +update --as user --doc "<URL>" --command block_delete --block-id <id1>,<id2>`
  批量删除 block;overwrite/replace/delete 后旧 block ID 失效,须重新 fetch
  ⚠ docs 域默认 --as user(+search 只支持 user);创建/导入用 Markdown 方便,局部精修(str_replace/block_*)官方要求默认 XML;--content 支持 @file/stdin,长内容优先 @file 避免 shell 转义;所有响应数据在 .data 下,--dry-run 可预览请求。

## task_mail
- [W] `task +create --as user --summary "<标题>" --description "<描述>" --due "+2d" --assignee <ou_xxx> --tasklist-id <tasklist_guid>`
  创建任务;user/bot 均可,但要放进个人清单/给人分派建议 --as user(bot 身份跨租户加成员会失败);--due 支持 ISO/YYYY-MM-DD/+2d/ms
- [R] `task +get-my-tasks --as user --complete=false --due-end "+7d" --page-all`
  列出分配给我的任务(仅支持 --as user);--complete=false 只看未完成,--query 可按标题模糊筛
- [R] `task +get-related-tasks --as user --created-by-me --include-complete=false`
  与我相关的任务(创建/关注,仅 --as user);无关键字的范围类查询优先用它而非 +search
- [R] `task +search --as user --query "<关键词>" --completed=false --assignee <ou_xxx>`
  按关键字搜任务(仅 --as user);支持 --creator/--follower/--due start,end 组合过滤
- [W] `task +complete --as user --task-id <task_guid>`
  标记任务完成;guid 是全局 GUID(applink ?guid= 里的值),不是 t104121 这种编号;+reopen 同参数反向
- [R] `task +tasklist-search --as user --query "<清单名>"`
  按关键字搜清单(仅 --as user);无关键字只有范围条件时改用 task tasklists list --as user 再本地筛 creator/created_at
- [R] `task tasklists tasks --as user --path-tasklist_guid <tasklist_guid>`
  取某清单下的任务列表(原生 API,flags 先跑 lark-cli schema task.tasklists.tasks 确认,--path 参数名以 schema 为准)
- [W] `task +tasklist-create --as user --name "<清单名>" --member <ou_xxx>`
  创建清单,--data 可传 JSON 数组顺带建任务;user/bot 均可但个人可见清单用 --as user
- [R] `mail +triage --as user --max 50 --filter '{"folder":"INBOX"}'`
  邮件摘要列表(date/from/subject/message_id),读未读/收件箱扫读首选;--query 全文搜(≤50字),--print-filter-schema 看全部 filter 字段(含 label/发件人过滤);邮箱是个人的,必须 --as user
- [R] `mail +message --as user --message-id <message_id> --html=false`
  读单封邮件全文(纯文本省流量);多封用 +messages --message-ids id1,id2(自动分批);必须 --as user 且需 mail:user_mailbox.message:readonly 等 scope
- [R] `mail +thread --as user --thread-id <thread_id>`
  按会话读整个邮件往来(含回复/草稿,时间序);--print-output-schema 先看字段再解析;--as user
  ⚠ 响应信封 {ok,identity,data},列表数据在 .data 下,用 -q 配 jq 提字段。task 的列表/搜索类 shortcut 全部只支持 --as user;+create/+complete 等 user|bot 均可但 bot(tenant token)不能跨租户加成员。mail 域整体需要 user 身份的 mail:user_mailbox.message:readonly / address:read / subject:read / body:read 等 scope,缺了会返回 missing_scope 并给出 auth login --scope 提示(本机当前恰好缺这些 mail scope,首用需补授权);写邮件类 +send/+reply 默认只存草稿,--confirm-send 才真发,严禁自动加。

## base
- [R] `base +url-resolve --url "<base_or_wiki_url>" --as user`
  把 Base/Wiki/记录分享 URL 解析成 base_token/table_id/view_id;任何后续命令的入口,别把 URL 或 wiki token 直接当 --base-token;默认走 --as user
- [R] `base +title-resolve --title "<短关键词>" --as user`
  按标题关键词(<=30字符)搜 Base 拿 base_token;多候选先让用户消歧;需 --as user(走 Drive 搜索)
- [R] `base +table-list --base-token <base_token> --as user`
  列出 Base 内数据表拿 table_id;user/bot 均可,取决于谁对该 Base 有权限
- [R] `base +field-list --base-token <base_token> --table-id <table_id> --as user`
  列字段(名称/类型/选项/ID),写记录前必跑,确认可写字段与 select 可选值;默认输出 json
- [R] `base +record-list --base-token <base_token> --table-id <table_id> --filter-json '{"logic":"and","conditions":[["Status","==","Done"]]}' --sort-json '[{"field":"Updated","desc":true}]' --field-id Name --field-id Status --limit 50`
  按条件列记录;filter 三元组 [字段,操作符,值]:文本等值 ==、包含 intersects、数字 ==、日期 "ExactDate(2026-06-02)"、多选 ["Tags","intersects",["P0"]];--field-id 投影省上下文;分页 has_more=true 时结果非全量;user/bot 皆可
- [R] `base +record-search --base-token <base_token> --table-id <table_id> --keyword Alice --search-field Name --filter-json '{"logic":"and","conditions":[["Title","intersects","urgent"]]}' --limit 20`
  关键词搜索(--keyword+--search-field 必填,除非 --json 传完整体),可叠加 --filter-json/--sort-json;--filter-json 覆盖 --view-id 的视图筛选;user/bot 皆可
- [R] `base +record-get --base-token <base_token> --table-id <table_id> --as user`
  按 record_id 取一条或多条记录明细(具体 ID flag 见其 --help);user/bot 皆可
- [W] `base +record-upsert --base-token <base_token> --table-id <table_id> --json '{"Name":"Alice","Status":"Todo"}' --as user`
  不带 --record-id 是新建,带 --record-id 是更新该条(非业务键自动 upsert);--json 是顶层字段映射不包 fields;CellValue:文本"x"/数字 12.5/多选 ["A"]/日期 "2026-03-24 10:00:00"/人员 [{"id":"ou_xxx"}];先 +field-list 确认字段,勿写 formula/lookup/系统/附件字段
- [W] `base +record-batch-create --base-token <base_token> --table-id <table_id> --json '{"fields":["Name","Status"],"rows":[["Task A","Todo"],["Task B",null]]}' --as user`
  批量新建,rows 按 fields 列顺序,null 为空格;单批最多 200 行;并发写同表报 1254291 需串行+等待重试
- [W] `base +record-batch-update --base-token <base_token> --table-id <table_id> --json '{"record_id_list":["rec_xxx"],"patch":{"Status":"Done"}}' --as user`
  同一份 patch 应用到所有 record_id(同值批量),逐行不同值要改用逐条 +record-upsert;单批最多 200 条
- [R] `base +data-query --base-token <base_token> --table-id <table_id> --json '<DSL>' --as user`
  云端聚合/分组/TopN 统计(JSON DSL,先 lark-cli skills read lark-base references/lark-base-data-query-guide.md);全局计数/最值别用 record-list 本地算;维度行去重且无 record_id
- [W] `base +record-delete --base-token <base_token> --table-id <table_id> --as user --yes`
  按 ID 删记录(高危写,不带 --yes 会 exit 10,须用户确认后再加);删前先 get/list 确认目标
  ⚠ 身份:默认显式 --as user;user 报 scope 不足走 lark-shared 授权恢复,仅资源级无权限才试一次 bot;91403 别循环换身份。filter 三元组固定 {"logic":"and|or","conditions":[[字段,op,值]]},文本模糊用 intersects 而非 like;日期值用 "ExactDate(YYYY-MM-DD)"。写前必 +field-list;--filter-json/--sort-json 支持 @file;record 读命令默认输出 markdown,要信封加 --format json 再取 .data。
