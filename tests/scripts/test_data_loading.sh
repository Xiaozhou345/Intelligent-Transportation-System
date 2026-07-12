#!/bin/bash

echo "=========================================="
echo "🧪 完整数据加载测试"
echo "=========================================="
echo ""

# 1. 测试后端 API
echo "=== 1. 后端 API 测试 ===\n"

echo "测试历史事件 API:"
EVENTS_RESPONSE=$(curl -s "http://localhost:5001/api/history/events?limit=5")
EVENTS_STATUS=$(echo $EVENTS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 'error'))")
EVENTS_COUNT=$(echo $EVENTS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('data', [])))")
EVENTS_TOTAL=$(echo $EVENTS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('total', 0))")

if [ "$EVENTS_STATUS" = "success" ]; then
    echo "  ✅ 状态: success"
    echo "  ✅ 返回: $EVENTS_COUNT 条"
    echo "  ✅ 总数: $EVENTS_TOTAL 条"
else
    echo "  ❌ 失败: $EVENTS_STATUS"
fi

echo ""

echo "测试白名单 API:"
WL_RESPONSE=$(curl -s "http://localhost:5001/api/whitelist")
WL_STATUS=$(echo $WL_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 'error'))")
WL_COUNT=$(echo $WL_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('data', [])))")

if [ "$WL_STATUS" = "success" ]; then
    echo "  ✅ 状态: success"
    echo "  ✅ 返回: $WL_COUNT 条"

    # 显示白名单车牌
    echo $WL_RESPONSE | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data.get('data', []):
    print(f\"     - {item['plate_number']} (permission_status={item['permission_status']})\")
"
else
    echo "  ❌ 失败: $WL_STATUS"
fi

echo ""

echo "测试告警记录 API:"
ALARM_RESPONSE=$(curl -s "http://localhost:5001/api/history/alarms?limit=5")
ALARM_STATUS=$(echo $ALARM_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 'error'))")
ALARM_COUNT=$(echo $ALARM_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('data', [])))")
ALARM_TOTAL=$(echo $ALARM_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('total', 0))")

if [ "$ALARM_STATUS" = "success" ]; then
    echo "  ✅ 状态: success"
    echo "  ✅ 返回: $ALARM_COUNT 条"
    echo "  ✅ 总数: $ALARM_TOTAL 条"
else
    echo "  ❌ 失败: $ALARM_STATUS"
fi

echo ""

echo "测试系统配置 API:"
CONFIG_RESPONSE=$(curl -s "http://localhost:5001/api/config")
CONFIG_STATUS=$(echo $CONFIG_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 'error'))")
CONFIG_KEYS=$(echo $CONFIG_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('data', {}).keys()))")

if [ "$CONFIG_STATUS" = "success" ]; then
    echo "  ✅ 状态: success"
    echo "  ✅ 配置项: $CONFIG_KEYS 个"
else
    echo "  ❌ 失败: $CONFIG_STATUS"
fi

echo ""

# 2. 测试数据库
echo "=== 2. 数据库状态 ===\n"

python3 << 'EOF'
import sys
sys.path.insert(0, 'cloud')
from database import mysql_client

with mysql_client.get_connection() as conn:
    with conn.cursor() as cursor:
        # 统计各表数据量
        tables = {
            'recognition_event': '识别事件',
            'alarm_record': '告警记录',
            'vehicle_whitelist': '白名单',
            'edge_device': '设备',
            'system_config': '系统配置'
        }

        for table, name in tables.items():
            cursor.execute(f'SELECT COUNT(*) as count FROM {table}')
            count = cursor.fetchone()['count']
            print(f"  {name:12} {count:6} 条")

EOF

echo ""

# 3. 前端代码验证
echo "=== 3. 前端代码验证 ===\n"

echo "检查 loadHistoryData 函数:"
if grep -q "const loadHistoryData = async" ui/App.vue; then
    echo "  ✅ loadHistoryData 定义为 async"

    # 检查 API 调用
    if grep -q "fetch.*api/history/events" ui/App.vue; then
        echo "  ✅ 调用历史事件 API"
    fi

    if grep -q "fetch.*api/whitelist" ui/App.vue; then
        echo "  ✅ 调用白名单 API"
    fi

    if grep -q "fetch.*api/config" ui/App.vue; then
        echo "  ✅ 调用系统配置 API"
    fi
else
    echo "  ❌ loadHistoryData 未定义"
fi

echo ""

echo "检查 onMounted 调用:"
if grep -q "await loadHistoryData()" ui/App.vue; then
    echo "  ✅ onMounted 中使用 await loadHistoryData()"
else
    echo "  ❌ 未使用 await"
fi

echo ""

echo "检查数据转换:"
if grep -q "timestamp: event.created_at" ui/App.vue; then
    echo "  ✅ 转换 created_at → timestamp"
fi

if grep -q "data: event.result_json" ui/App.vue; then
    echo "  ✅ 转换 result_json → data"
fi

echo ""

echo "检查白名单加载:"
if grep -q "window.initialWhitelist" ui/App.vue; then
    echo "  ✅ 设置 window.initialWhitelist"
fi

if grep -q "dispatchEvent.*whitelist-loaded" ui/App.vue; then
    echo "  ✅ 触发 whitelist-loaded 事件"
fi

if grep -q "addEventListener.*whitelist-loaded" ui/components/WhitelistManager.vue; then
    echo "  ✅ WhitelistManager 监听事件"
fi

echo ""

# 4. 总结
echo "=========================================="
echo "测试总结"
echo "=========================================="
echo ""

PASS=0
FAIL=0

# 检查所有 API
if [ "$EVENTS_STATUS" = "success" ] && [ "$WL_STATUS" = "success" ] && [ "$ALARM_STATUS" = "success" ] && [ "$CONFIG_STATUS" = "success" ]; then
    echo "✅ 所有 API 正常工作"
    PASS=$((PASS+1))
else
    echo "❌ 有 API 失败"
    FAIL=$((FAIL+1))
fi

# 检查数据库
if python3 -c "import sys; sys.path.insert(0, 'cloud'); from database import mysql_client; exit(0 if mysql_client.check_connection() else 1)" 2>/dev/null; then
    echo "✅ 数据库连接正常"
    PASS=$((PASS+1))
else
    echo "❌ 数据库连接失败"
    FAIL=$((FAIL+1))
fi

# 检查前端代码
if grep -q "await loadHistoryData()" ui/App.vue && grep -q "dispatchEvent.*whitelist-loaded" ui/App.vue; then
    echo "✅ 前端加载逻辑完整"
    PASS=$((PASS+1))
else
    echo "❌ 前端加载逻辑不完整"
    FAIL=$((FAIL+1))
fi

echo ""
echo "通过: $PASS / 失败: $FAIL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "🎉 所有测试通过！"
    echo ""
    echo "📊 数据统计:"
    echo "   - 历史事件: $EVENTS_TOTAL 条"
    echo "   - 告警记录: $ALARM_TOTAL 条"
    echo "   - 白名单: $WL_COUNT 条"
    echo ""
    echo "✅ 系统已就绪，可以在浏览器中测试前端"
else
    echo "⚠️  有 $FAIL 项测试失败"
fi

echo ""
