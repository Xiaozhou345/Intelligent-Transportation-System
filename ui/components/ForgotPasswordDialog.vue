<script setup>
import { reactive, ref, watch } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  serverUrl: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update:visible'])

const form = reactive({
  username: '',
  email: '',
  code: '',
  newPassword: '',
  confirmPassword: ''
})

const step = ref('identity')
const sending = ref(false)
const verifying = ref(false)
const resetting = ref(false)
const passwordError = ref('')

const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const resetForm = () => {
  form.username = ''
  form.email = ''
  form.code = ''
  form.newPassword = ''
  form.confirmPassword = ''
  step.value = 'identity'
  passwordError.value = ''
}

watch(() => props.visible, (visible) => {
  if (visible) {
    resetForm()
  }
})

const closeDialog = () => {
  emit('update:visible', false)
}

const normalizedIdentity = () => ({
  username: form.username.trim(),
  email: form.email.trim().toLowerCase()
})

const validateIdentity = () => {
  const { username, email } = normalizedIdentity()
  if (!username) {
    ElMessage.warning('请输入用户名')
    return false
  }
  if (!emailPattern.test(email)) {
    ElMessage.warning('请输入正确的绑定邮箱')
    return false
  }
  return true
}

const validateCode = () => {
  if (!/^\d{6}$/.test(form.code.trim())) {
    ElMessage.warning('请输入6位数字验证码')
    return false
  }
  return true
}

const validatePassword = () => {
  if (!form.newPassword) {
    passwordError.value = '请输入新密码'
    return false
  }
  if (form.newPassword !== form.confirmPassword) {
    passwordError.value = '两次输入的新密码不一致'
    return false
  }
  passwordError.value = ''
  return true
}

const parsePayload = async (response) => {
  try {
    return await response.json()
  } catch (error) {
    return { status: 'error', message: '服务器响应格式错误' }
  }
}

const sendCode = async () => {
  if (!validateIdentity()) return

  sending.value = true
  try {
    const { username, email } = normalizedIdentity()
    const response = await fetch(`${props.serverUrl}/api/users/forgot-password/send-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, email })
    })
    const payload = await parsePayload(response)
    if (!response.ok || payload.status !== 'success') {
      throw new Error(payload.message || '验证码发送失败')
    }
    step.value = 'reset'
    ElMessage.success(payload.message || '验证码已发送')
  } catch (error) {
    ElMessage.error(error.message || '验证码发送失败')
  } finally {
    sending.value = false
  }
}

const verifyCode = async () => {
  if (!validateIdentity() || !validateCode()) return

  verifying.value = true
  try {
    const { username, email } = normalizedIdentity()
    const response = await fetch(`${props.serverUrl}/api/users/forgot-password/verify-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, email, code: form.code.trim() })
    })
    const payload = await parsePayload(response)
    if (!response.ok || payload.status !== 'success') {
      throw new Error(payload.message || '验证码校验失败')
    }
    ElMessage.success('验证码校验通过')
  } catch (error) {
    ElMessage.error(error.message || '验证码校验失败')
  } finally {
    verifying.value = false
  }
}

const resetPassword = async () => {
  if (!validateIdentity() || !validateCode() || !validatePassword()) return

  resetting.value = true
  try {
    const { username, email } = normalizedIdentity()
    const response = await fetch(`${props.serverUrl}/api/users/forgot-password/reset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username,
        email,
        code: form.code.trim(),
        newPassword: form.newPassword,
        confirmPassword: form.confirmPassword
      })
    })
    const payload = await parsePayload(response)
    if (!response.ok || payload.status !== 'success') {
      throw new Error(payload.message || '密码重置失败')
    }
    ElMessage.success(payload.message || '密码已重置，请使用新密码登录')
    closeDialog()
  } catch (error) {
    ElMessage.error(error.message || '密码重置失败')
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <ElDialog
    :model-value="visible"
    title="忘记密码"
    width="420px"
    append-to-body
    modal-class="forgot-password-dialog-overlay"
    class="forgot-password-dialog"
    :z-index="4000"
    :close-on-click-modal="false"
    @close="closeDialog"
  >
    <ElForm label-position="top">
      <ElFormItem label="用户名">
        <ElInput v-model="form.username" maxlength="24" placeholder="请输入用户名" :disabled="step === 'reset'" />
      </ElFormItem>
      <ElFormItem label="绑定邮箱">
        <ElInput v-model="form.email" maxlength="128" placeholder="请输入账号绑定邮箱" :disabled="step === 'reset'" />
      </ElFormItem>

      <template v-if="step === 'reset'">
        <ElFormItem label="邮箱验证码">
          <div class="code-row">
            <ElInput v-model="form.code" maxlength="6" placeholder="请输入6位验证码" />
            <ElButton :loading="verifying" @click="verifyCode">验证</ElButton>
          </div>
        </ElFormItem>
        <ElFormItem label="新密码">
          <ElInput v-model="form.newPassword" type="password" maxlength="32" placeholder="请输入新密码" />
        </ElFormItem>
        <ElFormItem label="确认新密码">
          <ElInput
            v-model="form.confirmPassword"
            type="password"
            maxlength="32"
            placeholder="请再次输入新密码"
            @blur="validatePassword"
            @keyup.enter="resetPassword"
          />
          <span v-if="passwordError" class="password-error">{{ passwordError }}</span>
        </ElFormItem>
      </template>
    </ElForm>

    <template #footer>
      <div class="forgot-dialog-footer">
        <ElButton v-if="step === 'reset'" text :loading="sending" @click="sendCode">重新发送验证码</ElButton>
        <span v-else />
        <div class="forgot-dialog-actions">
          <ElButton @click="closeDialog">取消</ElButton>
          <ElButton v-if="step === 'identity'" type="primary" :loading="sending" @click="sendCode">发送验证码</ElButton>
          <ElButton v-else type="primary" :loading="resetting" @click="resetPassword">重置密码</ElButton>
        </div>
      </div>
    </template>
  </ElDialog>
</template>

<style scoped>
.code-row {
  display: grid;
  gap: 8px;
  grid-template-columns: 1fr auto;
  width: 100%;
}

.password-error {
  color: #f5222d;
  display: block;
  font-size: 12px;
  margin-top: 4px;
}

.forgot-dialog-footer {
  align-items: center;
  display: flex;
  justify-content: space-between;
  width: 100%;
}

.forgot-dialog-actions {
  display: flex;
  gap: 8px;
}

.forgot-dialog-footer .el-button--text {
  color: #67e8f9;
  font-size: 13px;
}

.forgot-dialog-footer .el-button--text:hover {
  color: #a5f3fc;
}

:global(.forgot-password-dialog-overlay) {
  z-index: 4000 !important;
}

:global(.forgot-password-dialog) {
  z-index: 4001 !important;
}

:global(.forgot-password-dialog.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  box-shadow: 0 26px 70px rgba(2, 8, 23, 0.72);
}

:global(.forgot-password-dialog .el-dialog__title),
:global(.forgot-password-dialog .el-form-item__label) {
  color: #e0f2fe;
}
</style>
