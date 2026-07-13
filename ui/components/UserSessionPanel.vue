<script setup>
import { reactive } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElTag } from 'element-plus'

const props = defineProps({
  user: {
    type: Object,
    default: null
  },
  visible: {
    type: Boolean,
    default: false
  },
  embedded: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['login', 'logout', 'register', 'update:visible'])

const roleMap = {
  admin: { label: '管理员', type: 'danger' },
  user: { label: '普通用户', type: 'info' }
}

const form = reactive({
  username: 'admin',
  password: ''
})

const submitLogin = () => {
  if (!form.username.trim() || !form.password) {
    return
  }
  emit('login', {
    username: form.username.trim(),
    password: form.password
  })
}

const closeDialog = () => {
  emit('update:visible', false)
}
</script>

<template>
  <div :class="['user-session', { 'user-session-embedded': embedded }]">
    <template v-if="embedded">
      <ElForm label-position="top" class="embedded-login-form">
        <ElFormItem label="用户名">
          <ElInput v-model="form.username" maxlength="24" />
        </ElFormItem>
        <ElFormItem label="密码">
          <ElInput v-model="form.password" type="password" maxlength="32" placeholder="请输入密码" />
        </ElFormItem>
        <ElButton type="primary" class="login-submit" @click="submitLogin">进入视频监控台</ElButton>
      </ElForm>
    </template>

    <template v-else>
    <template v-if="user">
      <ElTag :type="roleMap[user.role]?.type || 'info'" size="small" style="height: 32px; line-height: 30px; padding: 0 12px;">
        {{ roleMap[user.role]?.label || user.role }}
      </ElTag>
      <ElButton size="small" plain style="height: 32px; padding: 0 15px; border-radius: 8px; line-height: 30px;" @click="emit('logout')">退出</ElButton>
    </template>
    <ElButton v-else size="small" type="primary" @click="emit('update:visible', true)">登录</ElButton>

    <ElDialog
      :model-value="visible"
      title="用户登录"
      width="420px"
      append-to-body
      modal-class="login-dialog-overlay"
      class="login-dialog"
      :z-index="4000"
      :close-on-click-modal="false"
      @close="closeDialog"
    >
      <ElForm label-position="top">
        <ElFormItem label="用户名">
          <ElInput v-model="form.username" maxlength="24" />
        </ElFormItem>
        <ElFormItem label="密码">
          <ElInput v-model="form.password" type="password" maxlength="32" placeholder="请输入密码" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <div class="login-dialog-footer">
          <ElButton text @click="emit('register')">注册账号</ElButton>
          <div class="login-dialog-actions">
            <ElButton @click="closeDialog">取消</ElButton>
            <ElButton type="primary" @click="submitLogin">进入系统</ElButton>
          </div>
        </div>
      </template>
    </ElDialog>
    </template>
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

:global(.login-role-popper) {
  z-index: 5000 !important;
}

:global(.login-role-popper.el-popper) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.34);
  box-shadow: 0 18px 44px rgba(2, 8, 23, 0.62);
}

:global(.login-role-popper .el-select-dropdown__item) {
  color: #dbeafe;
}

:global(.login-role-popper .el-select-dropdown__item.is-hovering),
:global(.login-role-popper .el-select-dropdown__item:hover) {
  background: rgba(14, 165, 233, 0.18);
}

:global(.login-role-popper .el-select-dropdown__item.is-selected) {
  background: rgba(34, 211, 238, 0.18);
  color: #67e8f9;
}

:global(.login-role-popper .el-popper__arrow::before) {
  background: #0f172a;
  border-color: rgba(56, 189, 248, 0.34);
}

.user-session-embedded {
  display: block;
  width: 100%;
}

.embedded-login-form {
  display: grid;
  gap: 2px;
  width: 100%;
}

.login-submit {
  height: 42px;
  margin-top: 4px;
  width: 100%;
}

:global(.login-dialog-overlay) {
  z-index: 4000 !important;
}

:global(.login-dialog) {
  z-index: 4001 !important;
}

:global(.login-dialog.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  box-shadow: 0 26px 70px rgba(2, 8, 23, 0.72);
}

:global(.login-dialog .el-dialog__title),
:global(.login-dialog .el-form-item__label) {
  color: #e0f2fe;
}

/* 加深值班员标签颜色 */
:global(.user-session .el-tag.el-tag--warning) {
  --el-tag-bg-color: rgba(234, 179, 8, 0.15);
  --el-tag-border-color: rgba(234, 179, 8, 0.3);
  --el-tag-text-color: #ca8a04;
  background-color: var(--el-tag-bg-color);
  border-color: var(--el-tag-border-color);
  color: var(--el-tag-text-color);
  font-weight: 600;
}

.login-dialog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.login-dialog-actions {
  display: flex;
  gap: 8px;
}

.login-dialog-footer .el-button--text {
  color: #67e8f9;
  font-size: 13px;
}

.login-dialog-footer .el-button--text:hover {
  color: #a5f3fc;
}
</style>
