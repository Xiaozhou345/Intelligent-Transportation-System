<script setup>
import { reactive } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElOption, ElSelect, ElTag } from 'element-plus'

const props = defineProps({
  user: {
    type: Object,
    default: null
  },
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['login', 'logout', 'update:visible'])

const roleMap = {
  admin: { label: '管理员', type: 'danger' },
  operator: { label: '值班员', type: 'warning' },
  viewer: { label: '访客', type: 'info' }
}

const form = reactive({
  username: 'operator',
  role: 'operator'
})

const submitLogin = () => {
  emit('login', {
    username: form.username.trim() || 'operator',
    role: form.role,
    loginAt: new Date().toISOString()
  })
}

const closeDialog = () => {
  emit('update:visible', false)
}
</script>

<template>
  <div class="user-session">
    <template v-if="user">
      <div class="user-meta">
        <span>{{ user.username }}</span>
        <ElTag :type="roleMap[user.role]?.type || 'info'" size="small">
          {{ roleMap[user.role]?.label || user.role }}
        </ElTag>
      </div>
      <ElButton size="small" plain @click="emit('logout')">退出</ElButton>
    </template>
    <ElButton v-else size="small" type="primary" @click="emit('update:visible', true)">登录</ElButton>

    <ElDialog
      :model-value="visible"
      title="用户登录"
      width="420px"
      :close-on-click-modal="false"
      @close="closeDialog"
    >
      <ElForm label-position="top">
        <ElFormItem label="用户名">
          <ElInput v-model="form.username" maxlength="24" />
        </ElFormItem>
        <ElFormItem label="角色">
          <ElSelect v-model="form.role" class="role-select">
            <ElOption label="管理员" value="admin" />
            <ElOption label="值班员" value="operator" />
            <ElOption label="访客" value="viewer" />
          </ElSelect>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="closeDialog">取消</ElButton>
        <ElButton type="primary" @click="submitLogin">进入系统</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.user-session {
  align-items: center;
  display: flex;
  gap: 10px;
}

.user-meta {
  align-items: flex-end;
  display: grid;
  gap: 4px;
  justify-items: end;
}

.user-meta span {
  color: #e0f2fe;
  font-size: 13px;
  font-weight: 700;
}

.role-select {
  width: 100%;
}
</style>
