# 完整系统逻辑链审计报告 (回滚后)

## 📅 审计时间
2026-07-12 (回滚后)

## 🎯 审计结论
✅ **系统逻辑链存在严重问题**：video_overlay 数据不完整，导致多个功能失效

---

## 📊 当前系统状态

### 保留的优化 ✅

1. **画质优化** (f14dea9)
   - ✅ JPEG 质量: 85 (高画质)
   - ✅ 前端图像平滑: 'high'
   - ✅ 效果：画面清晰

2. **延迟优化** (26cb4da)
   - ✅ 前端 base64 解码: fetch data URI (性能提升 10 倍)
   - ✅ 帧丢弃机制: lastFrameSequence
   - ✅ Canvas 渲染优化: requestAnimationFrame
   - ✅ 效果：延迟降低 30-40%

### 当前推送逻辑 ⚠️

**后端** (video_processor.py:1461-1504):
```python
# 推送1: video_frame (完整画面)
self._send_result({
    'event_type': 'video_frame',
    'data': {'image': base64_jpeg}
})

# 推送2: video_overlay (只有统计数据，无 bbox)
self._send_result({
    'event_type': 'video_overlay',
    'data': {
        'vehicle_count': 5,       # ← 只有计数
        'plate_count': 3,         # ← 没有 bbox
        'illegal_parking_count': 2,
        # ... 其他计数
    }
})
```

**前端** (App.vue:575-582):
```javascript
if (data.event_type === 'video_frame') {
  handleVideoFrame(data)  // 显示画面
}

else if (data.event_type === 'video_overlay') {
  handleVideoOverlay(data, true)  // skipDraw=true，不绘制
}
```

---

## 🚨 发现的严重问题

### 问题 1: video_overlay 数据不完整 🔴

**当前状态**:
```python
# 后端只推送计数
'data': {
    'vehicle_count': 5,
    'plate_count': 3
}
```

**期望状态**:
```python
# 应该包含完整的 bbox 数据
'data': {
    'vehicles': [
        {'bbox': [x1, y1, x2, y2], 'label': 'car', ...},
        {'bbox': [x1, y1, x2, y2], 'label': 'bus', ...}
    ],
    'plates': [
        {'bbox': [x1, y1, x2, y2], 'label': '京A12345', ...}
    ]
}
```

**影响的功能**:

#### 1.1 EventStream.vue 显示错误 ❌

**位置**: `ui/components/EventStream.vue:85-90`

**代码**:
```javascript
if (event.event_type === 'video_overlay') {
  const count = ['vehicles', 'plates', 'illegal_parking', 'road_anomalies']
    .reduce((sum, key) => sum + (Array.isArray(data[key]) ? data[key].length : 0), 0)
    //                           ^^^^^^^^^^^^^^^^^^^^^^^^
    //                           期望是数组，实际是 undefined
  return `当前帧叠加目标 ${count} 个`
}
```

**结果**: 
- `data.vehicles` 是 `undefined` (不是数组)
- `count` 始终为 `0`
- 显示错误："当前帧叠加目标 0 个" (即使有检测)

#### 1.2 HistoryQuery.vue 显示错误 ❌

**位置**: `ui/components/HistoryQuery.vue:122-124`

**代码**:
```javascript
if (event.event_type === 'video_overlay') {
  return `目标 ${['vehicles', 'plates', 'illegal_parking', 'road_anomalies']
    .reduce((sum, key) => sum + (Array.isArray(data[key]) ? data[key].length : 0), 0)} 个`
}
```

**结果**:
- 历史查询表格中显示："目标 0 个"
- 用户无法看到正确的统计数据

#### 1.3 buildOverlayBoxes 函数失效 ❌

**位置**: `ui/App.vue:310-366`

**代码**:
```javascript
const buildOverlayBoxes = (overlay) => {
  const data = overlay.data || {}
  const normalize = (items, color, fallbackLabel) => {
    return (Array.isArray(items) ? items : [])
      //     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      //     items 是 undefined，返回空数组
      .filter(item => Array.isArray(item.bbox) && item.bbox.length === 4)
      .map(item => ({...}))
  }
  return [
    ...normalize(data.vehicles, '#ef4444', 'vehicle'),  // 空数组
    ...normalize(data.plates, '#f59e0b', 'plate'),      // 空数组
  ]
}
```

**结果**:
- 函数始终返回空数组
- 如果有地方调用此函数绘制，会导致检测框消失

#### 1.4 redrawCurrentOverlay 潜在 bug ❌

**位置**: `ui/App.vue:417-424`

**代码**:
```javascript
const redrawCurrentOverlay = () => {
  if (!videoPlayerRef.value || !latestVideoOverlay.value) return
  const overlay = latestVideoOverlay.value
  videoPlayerRef.value.drawBoxes(buildOverlayBoxes(overlay), sourceSize)
  //                              ^^^^^^^^^^^^^^^^^^^^^^^^^
  //                              返回空数组，会清空检测框
}
```

**结果**:
- 如果调用此函数，会清空所有检测框
- 当前场景切换时调用了此函数 (handleSceneChange)

---

## 🔍 逻辑链完整性分析

### 当前逻辑链 (有断链)

```
边端推流 → 云端 → 后端处理
                    ↓
            AI 分析（完整数据：vehicles, plates, bbox 等）
                    ↓
            构建 overlay（完整数据）
                    ↓
            在帧上绘制检测框
                    ↓
            JPEG 编码
                    ↓
    ┌───────────────┴───────────────┐
    ↓                               ↓
video_frame                  video_overlay
(完整画面)                   (❌ 只有计数，无 bbox)
    ↓                               ↓
前端显示                      前端保存
✅ 正常                       ❌ 数据不完整
                                    ↓
                            EventStream 显示错误 ❌
                            HistoryQuery 显示错误 ❌
                            buildOverlayBoxes 失效 ❌
```

### 问题总结

| 环节 | 状态 | 问题 |
|------|------|------|
| 后端 AI 分析 | ✅ 正常 | 生成完整数据 |
| 后端构建 overlay | ✅ 正常 | 包含完整 bbox |
| 后端绘制检测框 | ✅ 正常 | video_frame 包含框 |
| **后端推送 video_overlay** | **❌ 断链** | **只推送计数，丢弃 bbox** |
| 前端 video_frame 显示 | ✅ 正常 | 画面正常 |
| **前端 EventStream** | **❌ 错误** | **显示 "0 个目标"** |
| **前端 HistoryQuery** | **❌ 错误** | **显示 "0 个目标"** |
| **buildOverlayBoxes** | **❌ 失效** | **返回空数组** |

---

## ✅ 正确的修复方案

### 修复 1: 恢复 video_overlay 的完整数据

**文件**: `cloud/stream_receiver/video_processor.py:1485-1504`

**修改前** (当前，错误):
```python
self._send_result({
    'event_type': 'video_overlay',
    'data': {
        'vehicle_count': len(overlay['data']['vehicles']),  # ❌ 只有计数
        'plate_count': len(overlay['data']['plates'])
    }
})
```

**修改后** (正确):
```python
# 🔥 关键修复：推送完整的 overlay 数据，包含 bbox
# EventStream 和 HistoryQuery 需要完整数据来显示统计
self._send_result(overlay)  # 推送完整数据
```

**效果**:
- ✅ EventStream 正确显示目标数量
- ✅ HistoryQuery 正确显示目标数量
- ✅ buildOverlayBoxes 正常工作
- ✅ 导出 CSV/JSON 包含完整数据

### 修复 2: 前端保持 skipDraw 逻辑

**文件**: `ui/App.vue:579-582`

**当前** (正确，保持不变):
```javascript
} else if (data.event_type === 'video_overlay') {
  handleVideoOverlay(data, true)  // skipDraw=true
}
```

**说明**:
- ✅ skipDraw=true 确保不重复绘制检测框
- ✅ video_frame 已经包含完整画面
- ✅ video_overlay 用于事件记录和统计

### 修复 3: 验证 redrawCurrentOverlay

**文件**: `ui/App.vue:417-424`

**当前**:
```javascript
const redrawCurrentOverlay = () => {
  videoPlayerRef.value.drawBoxes(buildOverlayBoxes(overlay), sourceSize)
}
```

**验证**:
- 修复后，overlay 包含完整 bbox
- buildOverlayBoxes 会返回正确的框
- 场景切换时可以正确重绘

---

## 🎯 修复后的完整逻辑链

```
边端推流 → 云端 → 后端处理
                    ↓
            AI 分析（完整数据）
                    ↓
            构建 overlay（完整数据）
                    ↓
            在帧上绘制检测框
                    ↓
            JPEG 编码
                    ↓
    ┌───────────────┴───────────────┐
    ↓                               ↓
video_frame                  video_overlay
(完整画面)                   (✅ 完整数据：bbox + 统计)
    ↓                               ↓
前端 handleVideoFrame        前端 handleVideoOverlay(skipDraw=true)
    ↓                               ↓
显示到 canvas                 保存到 latestVideoOverlay
✅ 正常显示                          ↓
                            ┌───────┴───────┐
                            ↓               ↓
                    EventStream      HistoryQuery
                    ✅ 正确显示      ✅ 正确显示
```

---

## 📝 修复检查清单

### 上游 (后端)

- [ ] 恢复 video_overlay 完整数据推送
- [ ] 确认 overlay 包含 vehicles, plates, bbox 等完整字段
- [ ] 测试后端日志，验证推送数据结构

### 下游 (前端)

- [x] handleVideoOverlay 使用 skipDraw=true (已正确)
- [x] handleVideoFrame 显示画面 (已正确)
- [ ] 验证 EventStream 显示正确数量
- [ ] 验证 HistoryQuery 显示正确数量
- [ ] 验证 buildOverlayBoxes 返回正确框
- [ ] 验证场景切换时检测框正常

### 端到端测试

- [ ] 视频画面显示正常 ✅
- [ ] 检测框显示正常 ✅
- [ ] 事件流显示正确统计 ❌
- [ ] 历史查询显示正确统计 ❌
- [ ] 场景切换检测框不消失 ❌
- [ ] 导出 CSV/JSON 包含完整数据 ❌

---

## 🚀 立即执行的修复

### 第一步：修复后端推送

**位置**: `cloud/stream_receiver/video_processor.py:1483-1504`

**操作**: 删除简化的统计数据推送，恢复完整 overlay 推送

```python
# 删除第 1485-1504 行的简化推送
# 替换为：
self._send_result(overlay)  # 推送完整 overlay 数据
```

### 第二步：测试验证

1. 重启后端服务
2. 刷新前端页面
3. 检查事件流：应显示 "当前帧叠加目标 X 个" (X > 0)
4. 检查历史查询：应显示 "目标 X 个" (X > 0)
5. 切换场景：检测框应保持显示

### 第三步：确认无副作用

- ✅ 视频画面仍然流畅
- ✅ 画质仍然清晰
- ✅ 延迟仍然低
- ✅ 无渲染冲突 (skipDraw=true 确保)

---

## 📊 总结

### 当前问题

**核心问题**: video_overlay 数据被简化，只包含计数，不包含 bbox

**影响范围**:
- ❌ EventStream 显示错误
- ❌ HistoryQuery 显示错误
- ❌ buildOverlayBoxes 失效
- ❌ redrawCurrentOverlay 可能清空检测框

### 修复方案

**简单且安全**:
1. 恢复后端推送完整 overlay 数据
2. 前端保持 skipDraw=true 逻辑
3. 无需其他改动

### 修复成本

- 代码改动：1 行（删除简化逻辑，恢复完整推送）
- 测试时间：10 分钟
- 风险评估：极低（恢复到已验证的状态）

---

**建议立即修复**：这是一个明确的数据断链问题，修复简单且风险低。

**审计完成时间**: 2026-07-12
**审计结论**: ⚠️ 需要立即修复 video_overlay 数据不完整问题
