<script setup>
import { reactive, ref, watch } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  user: {
    type: Object,
    default: null
  },
  serverUrl: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['updated', 'update:visible'])

const form = reactive({
  username: '',
  email: '',
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const passwordError = ref('')
const submitting = ref(false)
const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const resetForm = () => {
  form.username = props.user?.username || ''
  form.email = props.user?.email || ''
  form.currentPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
  passwordError.value = ''
}

watch(() => props.visible, (visible) => {
  if (visible) {
    resetForm()
  }
})

watch(() => props.user, () => {
  if (props.visible) {
    resetForm()
  }
}, { deep: true })

const validatePassword = () => {
  const wantsPasswordChange = Boolean(form.currentPassword || form.newPassword || form.confirmPassword)
  if (!wantsPasswordChange) {
    passwordError.value = ''
    return true
  }
  if (!form.currentPassword || !form.newPassword || !form.confirmPassword) {
    passwordError.value = '修改密码时请完整填写当前密码、新密码和确认密码'
    return false
  }
  if (form.newPassword !== form.confirmPassword) {
    passwordError.value = '两次输入的新密码不一致'
    return false
  }
  passwordError.value = ''
  return true
}

const submitUpdate = async () => {
  const username = form.username.trim()
  const email = form.email.trim().toLowerCase()
  if (!username) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (!emailPattern.test(email)) {
    ElMessage.warning('请输入正确的邮箱')
    return
  }
  if (!validatePassword()) {
    return
  }

  submitting.value = true
  try {
    const response = await fetch(`${props.serverUrl}/api/users/me`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username,
        email,
        currentPassword: form.currentPassword,
        newPassword: form.newPassword,
        confirmPassword: form.confirmPassword
      })
    })
    const payload = await response.json()
    if (!response.ok || payload.status !== 'success') {
      throw new Error(payload.message || '账号资料更新失败')
    }

    emit('updated', payload.data)
    emit('update:visible', false)
    ElMessage.success('账号资料更新成功')
  } catch (error) {
    ElMessage.error(error.message || '账号资料更新失败')
  } finally {
    submitting.value = false
  }
}

const closeDialog = () => {
  emit('update:visible', false)
}
</script>

<template>
  <ElDialog
    :model-value="visible"
    title="账号管理"
    width="420px"
    append-to-body
    modal-class="account-dialog-overlay"
    class="account-dialog"
    :z-index="4000"
    :close-on-click-modal="false"
    @close="closeDialog"
  >
    <ElForm label-position="top">
      <ElFormItem label="用户名">
        <ElInput v-model="form.username" maxlength="24" placeholder="请输入用户名" />
      </ElFormItem>
      <ElFormItem label="绑定邮箱">
        <ElInput v-model="form.email" maxlength="128" placeholder="请输入用于找回密码的邮箱" />
      </ElFormItem>
      <ElFormItem label="当前密码">
        <ElInput v-model="form.currentPassword" type="password" maxlength="32" placeholder="仅修改密码时填写" />
      </ElFormItem>
      <ElFormItem label="新密码">
        <ElInput v-model="form.newPassword" type="password" maxlength="32" placeholder="如不改密码可留空" />
      </ElFormItem>
      <ElFormItem label="确认新密码">
        <ElInput
          v-model="form.confirmPassword"
          type="password"
          maxlength="32"
          placeholder="请再次输入新密码"
          @blur="validatePassword"
        />
        <span v-if="passwordError" class="password-error">{{ passwordError }}</span>
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton @click="closeDialog">取消</ElButton>
      <ElButton type="primary" :loading="submitting" @click="submitUpdate">确认修改</ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.password-error {
  color: #f5222d;
  display: block;
  font-size: 12px;
  margin-top: 4px;
}

:global(.account-dialog-overlay) {
  z-index: 4000 !important;
}

:global(.account-dialog) {
  z-index: 4001 !important;
}

:global(.account-dialog.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  box-shadow: 0 26px 70px rgba(2, 8, 23, 0.72);
}

:global(.account-dialog .el-dialog__title),
:global(.account-dialog .el-form-item__label) {
  color: #e0f2fe;
}
</style>
