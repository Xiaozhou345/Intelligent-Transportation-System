<script setup>
import { reactive, ref, onMounted, onUnmounted } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage, ElTable, ElTableColumn, ElTag } from 'element-plus'

const emit = defineEmits(['send-command'])

const whitelist = ref([])

const showDialog = ref(false)
const form = reactive({
  plate: '',
  role: ''
})

// 从数据库加载白名单
const loadWhitelist = (data) => {
  if (data && data.length > 0) {
    whitelist.value = data.map(item => ({
      id: item.id,
      plate: item.plate_number,
      role: item.vehicle_type || 'visitor',
      status: item.permission_status === 1 ? 'enabled' : 'disabled',
      remark: item.remark
    }))
    console.log(`✅ WhitelistManager 加载了 ${whitelist.value.length} 条白名单`)
  }
}

onMounted(() => {
  // 方式1: 如果数据已经加载完成
  if (window.initialWhitelist && window.initialWhitelist.length > 0) {
    loadWhitelist(window.initialWhitelist)
  }

  // 方式2: 监听加载完成事件（处理异步加载）
  const handleWhitelistLoaded = (event) => {
    loadWhitelist(event.detail)
  }
  window.addEventListener('whitelist-loaded', handleWhitelistLoaded)

  // 清理事件监听
  onUnmounted(() => {
    window.removeEventListener('whitelist-loaded', handleWhitelistLoaded)
  })
})

const resetForm = () => {
  form.plate = ''
  form.role = ''
}

const handleAdd = () => {
  if (!form.plate) {
    ElMessage.warning('请填写车牌号')
    return
  }

  const record = {
    plate: form.plate,
    role: form.role || 'visitor',
    status: 'enabled'
  }
  whitelist.value.unshift(record)
  emit('send-command', {
    command: 'update_whitelist',
    data: record
  })
  resetForm()
  showDialog.value = false
  ElMessage.success('白名单已更新')
}

const toggleStatus = (row) => {
  row.status = row.status === 'enabled' ? 'disabled' : 'enabled'
  emit('send-command', {
    command: 'update_whitelist_status',
    data: row
  })
}
</script>

<template>
  <section class="whitelist-manager">
    <div class="section-header">
      <h2>白名单管理</h2>
      <ElButton type="primary" size="small" @click="showDialog = true">新增</ElButton>
    </div>

    <ElTable :data="whitelist" stripe size="small" max-height="260">
      <ElTableColumn prop="plate" label="车牌号" width="120" />
      <ElTableColumn prop="role" label="类型" width="100" />
      <ElTableColumn label="状态" width="80" align="center">
        <template #default="{ row }">
          <ElTag :type="row.status === 'enabled' ? 'success' : 'info'" size="small">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="80" align="center">
        <template #default="{ row }">
          <ElButton type="primary" link size="small" @click="toggleStatus(row)">
            {{ row.status === 'enabled' ? '停用' : '启用' }}
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
    <div v-if="whitelist.length === 0" class="empty-tip">
      暂无白名单记录
    </div>

    <ElDialog title="新增白名单车辆" v-model="showDialog" width="420px">
      <ElForm :model="form" label-width="80px">
        <ElFormItem label="车牌号">
          <ElInput v-model="form.plate" placeholder="例如：京A12345" />
        </ElFormItem>
        <ElFormItem label="类型">
          <ElInput v-model="form.role" placeholder="faculty / service / visitor" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="showDialog = false">取消</ElButton>
        <ElButton type="primary" @click="handleAdd">确定</ElButton>
      </template>
    </ElDialog>
  </section>
</template>

<style scoped>
.whitelist-manager {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.section-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-header h2 {
  color: #e0f2fe;
  font-size: 17px;
}

.empty-tip {
  color: #93c5fd;
  font-size: 14px;
  padding: 18px;
  text-align: center;
}
</style>
