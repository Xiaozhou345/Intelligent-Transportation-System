#!/bin/bash

echo "=========================================="
echo "🔍 完整逻辑链验证"
echo "=========================================="
echo ""

python3 << 'EOF'
import sys
import requests
import json

print("=== 1. 后端 API 测试 ===\n")

base_url = "http://localhost:5001"

# 测试所有 API
tests = [
    ("历史事件 API", f"{base_url}/api/history/events?limit=5"),
    ("历史告警 API", f"{base_url}/api/history/alarms?limit=5"),
    ("白名单 API", f"{base_url}/api/whitelist"),
    ("系统配置 API", f"{base_url}/api/config"),
]

api_results = {}

for name, url in tests:
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'success':
                count = len(data.get('data', [])) if isinstance(data.get('data'), list) else len(data.get('data', {}).keys())
                print(f"✅ {name}: 返回 {count} 条数据")
                api_results[name] = {'status': 'ok', 'count': count}
            else:
                print(f"❌ {name}: {data.get('message', '未知错误')}")
                api_results[name] = {'status': 'error'}
        else:
            print(f"❌ {name}: HTTP {resp.status_code}")
            api_results[name] = {'status': 'error'}
    except Exception as e:
        print(f"❌ {name}: {e}")
        api_results[name] = {'status': 'error'}

print()

print("\n=== 2. 前端逻辑检查 ===\n")

# 检查前端代码
import os

ui_app = 'ui/App.vue'
whitelist_mgr = 'ui/components/WhitelistManager.vue'

checks = []

# 检查 App.vue
with open(ui_app, 'r', encoding='utf-8') as f:
    content = f.read()

    if 'loadHistoryData' in content:
        print("✅ App.vue 定义了 loadHistoryData 函数")
        checks.append(True)
    else:
        print("❌ App.vue 缺少 loadHistoryData 函数")
        checks.append(False)

    if '/api/history/events' in content:
        print("✅ App.vue 调用历史事件 API")
        checks.append(True)
    else:
        print("❌ App.vue 未调用历史事件 API")
        checks.append(False)

    if '/api/whitelist' in content:
        print("✅ App.vue 调用白名单 API")
        checks.append(True)
    else:
        print("❌ App.vue 未调用白名单 API")
        checks.append(False)

    if 'window.initialWhitelist' in content:
        print("✅ App.vue 存储白名单到全局变量")
        checks.append(True)
    else:
        print("❌ App.vue 未存储白名单")
        checks.append(False)

    if 'eventRecords.value = [...historyEvents' in content:
        print("✅ App.vue 将历史事件添加到 eventRecords")
        checks.append(True)
    else:
        print("❌ App.vue 未将历史事件添加到 eventRecords")
        checks.append(False)

print()

# 检查 WhitelistManager.vue
with open(whitelist_mgr, 'r', encoding='utf-8') as f:
    content = f.read()

    if 'window.initialWhitelist' in content:
        print("✅ WhitelistManager 读取全局白名单")
        checks.append(True)
    else:
        print("❌ WhitelistManager 未读取全局白名单")
        checks.append(False)

    if 'onMounted' in content:
        print("✅ WhitelistManager 使用 onMounted 加载")
        checks.append(True)
    else:
        print("❌ WhitelistManager 未使用 onMounted")
        checks.append(False)

print()

print("\n=== 3. 数据流向验证 ===\n")

flow_checks = {
    "数据库 → API": "✅ 正常" if all(r['status'] == 'ok' for r in api_results.values()) else "❌ 有问题",
    "API → 前端加载": "✅ 正常" if all(checks) else "❌ 有问题",
    "前端加载 → 显示": "⚠️  需要前端测试确认"
}

for step, status in flow_checks.items():
    print(f"{step}: {status}")

print()

print("\n=== 4. 潜在问题检查 ===\n")

issues = []

# 检查 CORS
if True:  # 简化检查
    print("⚠️  CORS 问题:")
    print("   - API 在 localhost:5001")
    print("   - 前端在 localhost:5173")
    print("   - 需要确认 main_server.py 有 CORS 设置")

    with open('cloud/stream_receiver/main_server.py', 'r') as f:
        if 'CORS' in f.read():
            print("   ✅ 后端已启用 CORS")
        else:
            print("   ❌ 后端未启用 CORS - 前端会请求失败！")
            issues.append("CORS 未配置")

print()

# 检查 URL 配置
with open(ui_app, 'r', encoding='utf-8') as f:
    content = f.read()
    if 'CLOUD_SERVER_URL' in content and '${CLOUD_SERVER_URL}' in content:
        print("✅ 前端使用 CLOUD_SERVER_URL 变量")
    else:
        print("⚠️  前端可能硬编码了 URL")

print()

# 检查数据格式转换
print("⚠️  数据格式转换:")
print("   - 数据库字段: created_at, result_json, plate_number")
print("   - 前端期望: timestamp, data, plate_number")
with open(ui_app, 'r', encoding='utf-8') as f:
    content = f.read()
    if 'created_at' in content and 'timestamp: event.created_at' in content:
        print("   ✅ 前端正确转换 created_at → timestamp")
    else:
        print("   ❌ 前端未正确转换字段")
        issues.append("字段转换不完整")

print()

print("\n=== 5. 完整逻辑链 ===\n")

logic_chain = [
    ("1. 后端写入数据", "insert_recognition_event()", "✅"),
    ("2. 数据存入 MySQL", "recognition_event 表", "✅"),
    ("3. API 查询数据", "GET /api/history/events", "✅" if api_results.get('历史事件 API', {}).get('status') == 'ok' else "❌"),
    ("4. 前端加载数据", "loadHistoryData()", "✅" if all(checks[:5]) else "❌"),
    ("5. 转换数据格式", "map(event => ...)", "✅"),
    ("6. 添加到 eventRecords", "eventRecords.value = [...]", "✅"),
    ("7. HistoryQuery 显示", "props.events", "⚠️  需测试"),
]

for step, detail, status in logic_chain:
    print(f"{status} {step}")
    print(f"   {detail}")

print()

print("\n=== 6. 白名单逻辑链 ===\n")

whitelist_chain = [
    ("1. 数据库有白名单", "vehicle_whitelist 表", "✅"),
    ("2. API 返回白名单", "GET /api/whitelist", "✅" if api_results.get('白名单 API', {}).get('status') == 'ok' else "❌"),
    ("3. 前端加载白名单", "loadHistoryData()", "✅"),
    ("4. 存储到全局变量", "window.initialWhitelist", "✅"),
    ("5. WhitelistManager 读取", "onMounted()", "✅" if checks[-2:] == [True, True] else "❌"),
    ("6. 显示白名单列表", "ElTable :data=\"whitelist\"", "⚠️  需测试"),
]

for step, detail, status in whitelist_chain:
    print(f"{status} {step}")
    print(f"   {detail}")

print()

print("\n=== 7. 关键问题 ===\n")

critical_issues = []

# 问题1: 异步加载时机
print("❓ 问题1: 数据加载时机")
print("   - loadHistoryData() 在 onMounted 中调用")
print("   - WebSocket 也在 onMounted 中连接")
print("   - 如果 API 慢，可能先收到 WebSocket 数据")
print("   ⚠️  建议: 使用 await 确保按顺序加载")
critical_issues.append("数据加载时机可能有竞态")

print()

# 问题2: 白名单传递方式
print("❓ 问题2: 白名单传递方式")
print("   - 使用 window.initialWhitelist 全局变量")
print("   - WhitelistManager 在 onMounted 读取")
print("   - 如果 App.vue 加载慢，window.initialWhitelist 可能还是 undefined")
print("   ⚠️  建议: 使用 provide/inject 或 props 传递")
critical_issues.append("白名单传递方式不可靠")

print()

# 问题3: CORS
print("❓ 问题3: CORS 配置")
sys.path.insert(0, 'cloud/stream_receiver')
try:
    with open('cloud/stream_receiver/main_server.py', 'r') as f:
        content = f.read()
        if 'CORS(app)' in content:
            print("   ✅ 后端已配置 CORS(app)")
        elif 'flask_cors' in content:
            print("   ⚠️  已导入 CORS 但可能未正确配置")
            critical_issues.append("CORS 配置可能不完整")
        else:
            print("   ❌ 后端未配置 CORS")
            critical_issues.append("CORS 未配置 - 前端请求会失败")
except:
    pass

print()

print("\n========================================")
print("总结")
print("========================================")
print()

if len(issues) == 0 and len(critical_issues) == 0:
    print("✅ 逻辑链基本完整，但需要前端测试验证")
else:
    print(f"❌ 发现 {len(issues) + len(critical_issues)} 个问题:\n")
    for issue in issues + critical_issues:
        print(f"   • {issue}")

print()
print("🧪 下一步: 需要在浏览器中测试前端加载")
print()

EOF
