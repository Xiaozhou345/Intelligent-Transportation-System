#!/bin/bash

echo "=========================================="
echo "🔍 数据库配置验证工具"
echo "=========================================="
echo ""

# 1. 检查 .env.db 文件是否存在
echo "1️⃣  检查配置文件..."
if [ -f ".env.db" ]; then
    echo "   ✅ .env.db 文件存在"
    echo "   位置: $(pwd)/.env.db"
else
    echo "   ❌ .env.db 文件不存在"
    echo "   请运行: cp .env.db.template .env.db"
    echo "   然后编辑 .env.db 填入密码"
    exit 1
fi
echo ""

# 2. 检查配置内容
echo "2️⃣  读取配置内容..."
DB_HOST=$(grep "^DB_HOST=" .env.db | cut -d'=' -f2)
DB_PORT=$(grep "^DB_PORT=" .env.db | cut -d'=' -f2)
DB_USER=$(grep "^DB_USER=" .env.db | cut -d'=' -f2)
DB_PASSWORD=$(grep "^DB_PASSWORD=" .env.db | cut -d'=' -f2)
DB_NAME=$(grep "^DB_NAME=" .env.db | cut -d'=' -f2)

echo "   Host: ${DB_HOST:-未设置}"
echo "   Port: ${DB_PORT:-未设置}"
echo "   User: ${DB_USER:-未设置}"
if [ -z "$DB_PASSWORD" ]; then
    echo "   Password: (空) ⚠️"
else
    echo "   Password: $(echo $DB_PASSWORD | sed 's/./*/g') (已设置) ✅"
fi
echo "   Database: ${DB_NAME:-未设置}"
echo ""

# 3. 检查 .gitignore
echo "3️⃣  检查 Git 忽略配置..."
if grep -q "^\.env\.db$" .gitignore; then
    echo "   ✅ .env.db 已添加到 .gitignore"
else
    echo "   ⚠️  .env.db 未在 .gitignore 中"
    echo "   建议添加以避免提交敏感信息"
fi
echo ""

# 4. 测试 Python 配置加载
echo "4️⃣  测试 Python 配置加载..."
python3 -c "
import sys
sys.path.insert(0, 'cloud')
from database import mysql_client
print('   配置加载完成')
print(f'   Host: {mysql_client.DB_SETTINGS[\"host\"]}')
print(f'   Port: {mysql_client.DB_SETTINGS[\"port\"]}')
print(f'   User: {mysql_client.DB_SETTINGS[\"user\"]}')
password_display = '*' * len(mysql_client.DB_SETTINGS['password']) if mysql_client.DB_SETTINGS['password'] else '(空)'
print(f'   Password: {password_display}')
print(f'   Database: {mysql_client.DB_SETTINGS[\"database\"]}')
" 2>&1
echo ""

# 5. 测试数据库连接
echo "5️⃣  测试数据库连接..."
python3 -c "
import sys
sys.path.insert(0, 'cloud')
from database import mysql_client
result = mysql_client.check_connection()
if result:
    print('   ✅ 数据库连接成功')
else:
    print('   ❌ 数据库连接失败')
    print(f'   错误: {mysql_client._db_error_cache}')
" 2>&1
echo ""

echo "=========================================="
echo "📖 详细文档: DATABASE_PASSWORD_GUIDE.md"
echo "=========================================="
echo ""
