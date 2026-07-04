# 私有资产绑定示例

把你自己的飞书资源写进 `assets.local.md`(已 gitignore),小爪会在系统提示里
注入这段"已知资产",这样它知道该操作哪个 Base / 文档 / 群 / 用户,不用每次问你。
缺这个文件也能跑,只是小爪对你的具体资源一无所知、需要你在对话里给它 token。

格式(一行一条,自由文本,给够上下文即可):

```
- 我的 open_id: ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
- 某某台账 Base:base-token bascnXXXXXXXXXXXXXXXXXXXXXXXX,表名"…",字段:…
- 某某文档 token: docxXXXXXXXXXXXXXXXXXXXXXXXX
- 某某群 chat_id: oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx(读它要 --as user)
```
