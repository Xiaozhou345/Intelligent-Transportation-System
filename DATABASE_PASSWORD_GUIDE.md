# 数据库密码配置指南

## 📋 概述

为了安全地存储数据库密码，项目支持从 `.env.db` 文件读取配置。此文件**不会上传到 GitHub**，确保密码安全。

---

## 🚀 快速开始

### 步骤 1: 创建配置文件

```bash
# 复制模板文件
cp .env.db.template .env.db
```

### 步骤 2: 编辑配置文件

编辑 `.env.db` 文件，填入你的 MySQL 密码：

```bash
# 使用你喜欢的编辑器
vim .env.db
# 或
nano .env.db
```

修改以下内容：

```ini
# MySQL 数据库配置
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_actual_mysql_password_here  # ← 改成你的实际密码
DB_NAME=intelligent_transportation_system
```

### 步骤 3: 保存并重启服务

```bash
# 重启后端服务
pkill -f main_server.py
python3 cloud/stream_receiver/main_server.py
```

---

## 🔍 配置优先级

系统按以下优先级读取配置：

1. **环境变量** (最高优先级)
   ```bash
   export ITS_DB_PASSWORD=your_password
   ```

2. **.env.db 文件** (推荐方式)
   ```ini
   DB_PASSWORD=your_password
   ```

3. **默认值** (空密码，仅用于本地无密码 MySQL)

---

## ✅ 验证配置

### 测试数据库连接

```bash
python3 -c "
import sys
sys.path.insert(0, 'cloud')
from database import mysql_client
print('测试数据库连接...')
result = mysql_client.check_connection()
print(f'✅ 数据库可用' if result else f'❌ 连接失败: {mysql_client._db_error_cache}')
"
```

**预期输出（成功）**:
```
✅ 从 .env.db 加载数据库配置: /root/S/Intelligent-Transportation-System/.env.db
测试数据库连接...
✅ 数据库可用
```

**预期输出（失败）**:
```
⚠️  未找到 .env.db 文件: /root/S/Intelligent-Transportation-System/.env.db
   将使用环境变量或默认配置
测试数据库连接...
❌ 连接失败: (1045, "Access denied for user 'root'@'localhost' (using password: NO)")
```

---

## 🔒 安全说明

### ✅ 安全措施

1. **`.env.db` 已添加到 `.gitignore`**
   - 不会被 Git 跟踪
   - 不会上传到 GitHub
   - 每个开发者独立配置

2. **`.env.db.template` 是模板**
   - 只包含示例，无实际密码
   - 可以安全地提交到 GitHub
   - 新团队成员可以快速配置

3. **配置文件位置**
   - 位于项目根目录
   - 不在代码目录内
   - 与代码分离

### ⚠️ 注意事项

1. **不要提交 `.env.db` 到 Git**
   ```bash
   # 检查是否被追踪
   git status | grep .env.db
   
   # 如果不小心添加了，移除追踪
   git rm --cached .env.db
   ```

2. **不要在代码中硬编码密码**
   ```python
   # ❌ 错误
   DB_PASSWORD = "my_secret_password"
   
   # ✅ 正确
   DB_PASSWORD = os.getenv('ITS_DB_PASSWORD') or _file_config.get('DB_PASSWORD', '')
   ```

3. **服务器部署时**
   - 在服务器上创建 `.env.db`
   - 或使用环境变量
   - 不要将本地 `.env.db` 上传到服务器

---

## 📝 配置文件格式

### 完整示例

```ini
# 智慧交通系统 - 数据库配置
# 本文件包含敏感信息，已在 .gitignore 中排除

# MySQL 数据库配置
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=intelligent_transportation_system

# 注释说明：
# - 以 # 开头的行是注释
# - 空行会被忽略
# - 格式: KEY=VALUE
# - 不需要引号
```

### 配置项说明

| 配置项 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| DB_HOST | 数据库主机地址 | 127.0.0.1 | localhost, 192.168.1.100 |
| DB_PORT | 数据库端口 | 3306 | 3306, 3307 |
| DB_USER | 数据库用户名 | root | root, its_user |
| DB_PASSWORD | 数据库密码 | (空) | your_password |
| DB_NAME | 数据库名称 | intelligent_transportation_system | its_db |

---

## 🔧 常见问题

### Q1: 配置文件不生效？

**检查文件位置**:
```bash
# 确保文件在项目根目录
ls -la /root/S/Intelligent-Transportation-System/.env.db
```

**检查文件格式**:
```bash
# 查看文件内容
cat .env.db | grep -v "^#" | grep -v "^$"
```

**检查是否被读取**:
```bash
# 启动后端服务，查看输出
# 应该看到: ✅ 从 .env.db 加载数据库配置
```

### Q2: 密码包含特殊字符？

**不需要引号**:
```ini
# ✅ 正确
DB_PASSWORD=P@ssw0rd!#$%

# ❌ 错误（会包含引号）
DB_PASSWORD="P@ssw0rd!#$%"
```

### Q3: 多环境配置？

**方案1: 使用不同的配置文件**:
```bash
# 开发环境
cp .env.db .env.db.dev

# 生产环境
cp .env.db .env.db.prod

# 切换环境
cp .env.db.dev .env.db
```

**方案2: 使用环境变量覆盖**:
```bash
# 临时使用不同密码
export ITS_DB_PASSWORD=production_password
python3 cloud/stream_receiver/main_server.py
```

### Q4: 忘记 MySQL 密码？

**重置 MySQL root 密码**:
```bash
# 1. 停止 MySQL
sudo service mysql stop

# 2. 安全模式启动
sudo mysqld_safe --skip-grant-tables &

# 3. 重置密码
mysql -u root
mysql> FLUSH PRIVILEGES;
mysql> ALTER USER 'root'@'localhost' IDENTIFIED BY 'new_password';
mysql> FLUSH PRIVILEGES;
mysql> exit;

# 4. 重启 MySQL
sudo service mysql restart

# 5. 更新 .env.db
vim .env.db  # 修改 DB_PASSWORD=new_password
```

---

## 📊 团队协作

### 新成员加入

1. **克隆项目**:
   ```bash
   git clone https://github.com/your/repo.git
   cd repo
   ```

2. **配置数据库**:
   ```bash
   # 复制模板
   cp .env.db.template .env.db
   
   # 编辑配置
   vim .env.db  # 填入自己的 MySQL 密码
   ```

3. **验证配置**:
   ```bash
   # 测试连接
   python3 -c "
   import sys
   sys.path.insert(0, 'cloud')
   from database import mysql_client
   print('可用' if mysql_client.check_connection() else '失败')
   "
   ```

### 文档传递

在团队文档中记录：

```markdown
## 数据库配置

1. 复制 `.env.db.template` 为 `.env.db`
2. 填入你的 MySQL 密码
3. 密码由团队管理员提供（通过安全渠道）
4. 不要提交 `.env.db` 到 Git
```

---

## 🎯 总结

### 使用流程

```
1. 复制模板
   cp .env.db.template .env.db

2. 填入密码
   编辑 DB_PASSWORD=your_password

3. 保存文件
   :wq (vim) 或 Ctrl+X (nano)

4. 重启服务
   pkill -f main_server.py
   python3 cloud/stream_receiver/main_server.py

5. 验证连接
   查看日志: ✅ 从 .env.db 加载数据库配置
```

### 优势

✅ **安全**: 密码不上传到 GitHub  
✅ **方便**: 无需设置环境变量  
✅ **灵活**: 支持多种配置方式  
✅ **清晰**: 配置文件独立于代码  

---

**配置完成后，系统会自动从 `.env.db` 读取密码，无需额外操作。**
