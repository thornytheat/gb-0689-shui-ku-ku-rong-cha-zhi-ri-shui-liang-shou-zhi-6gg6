# 运行维护

主服务端口与Compose保持一致。数据保存在records命名卷，应用代码不需要写入权限。

```sh
docker compose logs --tail=80 app
docker compose restart app
docker compose exec -T app pytest -q
docker compose down --remove-orphans
```

健康检查GET /health。失败输入返回原因码，结构性错误422，过大文件413，陈旧复核409。
文件内容最大4MB。批次先计算再原子保存，失败不留半条记录。证据CSV按原始行号定位。

## 曲线改版运行要点

- 在 M2 页面或 `POST /api/m2/revisions` 登记 `curve_switch`（生效时刻含时区、新曲线点）。登记前自动试算整条管线：生效时刻落在缺口/范围外返回 `CURVE_SWITCH`，所在日已复核确认返回 `SWITCH_CONFLICT`，两类失败均不落库。
- 同一生效时刻重复登记返回“已存在”，不会产生第二次曲线调整；改版登记与确认日分别存于 `curve_revisions`、`confirmed_days` 表。
- 复核“通过”会固化当日曲线快照；续跑新改版前，对需要重算的日期先在 M6 作“退回”解除确认，已确认日始终保持原曲线。
