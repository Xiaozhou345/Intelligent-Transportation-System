# 数据库设计说明

本文档对应：

- `cloud/database/mysql_schema.sql`

用于给智慧交通系统建立 **MySQL** 版本的基础表结构。

---

## 1. 为什么没有完全照搬最初设计图

最初设计图中的 5 张表方向是对的：

- `edge_device`
- `vehicle_whitelist`
- `recognition_event`
- `alarm_record`
- `system_config`

但如果直接照截图里的字段原样建表，会有几个问题：

1. **字段不够覆盖当前代码真实输出**
   - 当前后端已经会输出：
     - `vehicle_detection`
     - `plate_recognition`
     - `traffic_density`
     - `illegal_parking`
     - `road_anomaly`
   - 这些事件字段差异很大，单靠少量固定列不够。

2. **中文车牌与完整 JSON 结果需要扩展能力**
   - 车牌号必须支持中文，因此数据库必须用 `utf8mb4`。
   - 各场景的完整结果最适合放在 `JSON` 字段里，不然每加一个业务都要改表。

3. **当前系统已经依赖 `scene_id`、`status`、`bbox`、完整结果 JSON**
   - 如果不设计这些字段，后续很难和现有后端代码对齐。

因此我保留了你们最初设计的 5 张主表，但做了**更适合当前项目代码**的扩展版设计。

---

## 2. 当前推荐的 5 张主表

### 2.1 `edge_device`
存设备注册、流地址、场景、状态、心跳等。

相比原图，补充了：

- `resolution`
- `fps`
- `codec`
- `bitrate`
- `register_time`
- `updated_at`

并把：

- `device_id`

作为业务唯一键（`UNIQUE`），同时保留自增主键 `id`。

---

### 2.2 `vehicle_whitelist`
存白名单车辆。

相比原图，补充了：

- `id` 自增主键
- `remark`
- `updated_at`
- `permission_status` 用 `TINYINT(1)`，表示是否允许通行

并把：

- `plate_number`

设为唯一键。

---

### 2.3 `recognition_event`
存“识别/分析事件”。

这张表不是只给车牌识别用，而是可以统一存：

- `plate_recognition`
- `vehicle_detection`
- `traffic_density`
- `road_anomaly`
- `illegal_parking`

相比原图，新增或强化了：

- `event_type`
- `scene_id`
- `result_json`
- `bbox`（JSON）
- `plate_number`（可空）

其中最重要的是：

- `result_json JSON`

因为当前系统不同事件差异太大，必须保留完整事件结构。

---

### 2.4 `alarm_record`
存告警记录。

相比原图，补充了：

- `scene_id`
- `target_type`
- `plate_number`
- `detail_json`
- `resolved_at`

并把：

- `status`

设计为：

- `warning`
- `acknowledged`
- `resolved`

这样更适合当前违停/道路异常的真实流程。

---

### 2.5 `system_config`
存系统配置。

相比原图，改进点是：

- `config_value` 用 `JSON`
- 保留 `config_key` 作为主键
- 增加 `updated_at`

这样后续像：

- `traffic_thresholds`
- `no_parking_zone`
- 前端可调阈值

都能直接存进去。

---

## 3. 设计上最关键的原则

### 3.1 保留你们原本设计的主表分工
没有推翻你们的思路，只是增强：

- 设备 → `edge_device`
- 白名单 → `vehicle_whitelist`
- 识别事件 → `recognition_event`
- 告警 → `alarm_record`
- 配置 → `system_config`

### 3.2 统一使用 `utf8mb4`
因为车牌有中文，比如：

- `京A12345`
- `粤B6789T`

### 3.3 使用 `JSON` 保存多场景完整结果
原因是当前系统的事件类型太多，不适合每种事件都拆成大量固定列。

### 3.4 设备关联使用 `device_id`
因为当前后端代码里设备主标识就是：

- `device_id`

例如：

- `mobile_001`

所以外键直接连到 `edge_device.device_id` 更符合当前代码逻辑。

---

## 4. 这个建表脚本适合什么阶段

当前这个 `mysql_schema.sql` 适合：

- 你们先把 MySQL 表建起来
- 后续再逐步把 Python 后端代码接入数据库

也就是说：

> **这次我先把“合理的数据库结构”建好，不强行把现有运行时逻辑立刻全部改成数据库版。**

这样做更稳妥，也更符合你现在项目推进节奏。

---

## 5. 你接下来怎么建表

如果你本地或服务器上已经装了 MySQL，执行：

```bash
mysql -u root -p < cloud/database/mysql_schema.sql
```

或者进入 MySQL 后：

```sql
SOURCE cloud/database/mysql_schema.sql;
```

---

## 6. 一句话总结

这份建表方案：

- 保留了你们最初 5 张表的总体思路；
- 但根据当前项目代码和事件结构，把字段设计改得更适合现在的后端实际输出；
- 重点增强了：`scene_id`、`status`、`bbox JSON`、`result_json JSON`、配置 JSON 化、中文车牌兼容。
