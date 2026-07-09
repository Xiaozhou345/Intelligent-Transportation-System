<script setup>
import { reactive, ref } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage, ElTable, ElTableColumn, ElTag } from 'element-plus'

const emit = defineEmits(['send-command'])

const whitelist = ref([
  { plate: '京A12345', owner: '校内车辆', role: 'faculty', status: 'enabled' },
  { plate: '京B67890', owner: '后勤车辆', role: 'service', status: 'enabled' },
  { plate: '沪C11223', owner: '临时访客', role: 'visitor', status: 'disabled' }
])

const showDialog = ref(false)
const form = reactive({
  plate: '',
  owner: '',
  role: ''
})

const resetForm = () => {
  form.plate = ''
  form.owner = ''
  form.role = ''
}

const handleAdd = () => {
  if (!form.plate || !form.owner) {
    ElMessage.warning('请填写车牌号和所属人')
    return
  }

  const record = {
    plate: form.plate,
    owner: form.owner,
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
      <ElTableColumn prop="plate" label="车牌号" width="110" />
      <ElTableColumn prop="owner" label="所属人" />
      <ElTableColumn prop="role" label="类型" width="90" />
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

    <ElDialog title="新增白名单车辆" v-model="showDialog" width="420px">
      <ElForm :model="form" label-width="80px">
        <ElFormItem label="车牌号">
          <ElInput v-model="form.plate" placeholder="例如：京A12345" />
        </ElFormItem>
        <ElFormItem label="所属人">
          <ElInput v-model="form.owner" placeholder="请输入所属人或部门" />
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
</style>
