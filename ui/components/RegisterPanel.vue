<script setup>
import { reactive, ref } from 'vue'
import { ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['register', 'update:visible'])

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  role: 'user'
})

const passwordError = ref('')
const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const validatePassword = () => {
  if (form.password !== form.confirmPassword) {
    passwordError.value = '两次输入的密码不一致'
    return false
  }
  passwordError.value = ''
  return true
}

const submitRegister = () => {
  if (!form.username.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (!emailPattern.test(form.email.trim().toLowerCase())) {
    ElMessage.warning('请输入正确的邮箱')
    return
  }
  if (!form.password) {
    ElMessage.warning('请输入密码')
    return
  }
  if (!validatePassword()) {
    return
  }
  
  emit('register', {
    username: form.username.trim(),
    email: form.email.trim().toLowerCase(),
    password: form.password,
    role: 'user'
  })

  form.username = ''
  form.email = ''
  form.password = ''
  form.confirmPassword = ''
  form.role = 'user'
  passwordError.value = ''
  
  ElMessage.success('注册成功，正在登录...')
}

const closeDialog = () => {
  form.username = ''
  form.email = ''
  form.password = ''
  form.confirmPassword = ''
  form.role = 'user'
  passwordError.value = ''
  emit('update:visible', false)
}
</script>

<template>
  <ElDialog
    :model-value="visible"
    title="用户注册"
    width="420px"
    append-to-body
    modal-class="register-dialog-overlay"
    class="register-dialog"
    :z-index="4000"
    :close-on-click-modal="false"
    @close="closeDialog"
  >
    <ElForm label-position="top">
      <ElFormItem label="用户名">
        <ElInput v-model="form.username" maxlength="24" placeholder="请输入用户名" />
      </ElFormItem>
      <ElFormItem label="邮箱">
        <ElInput v-model="form.email" maxlength="128" placeholder="请输入用于找回密码的邮箱" />
      </ElFormItem>
      <ElFormItem label="密码">
        <ElInput v-model="form.password" type="password" maxlength="32" placeholder="请输入密码" />
      </ElFormItem>
      <ElFormItem label="确认密码">
        <ElInput
          v-model="form.confirmPassword"
          type="password"
          maxlength="32"
          placeholder="请再次输入密码"
          @blur="validatePassword"
        />
        <span v-if="passwordError" style="color: #f5222d; font-size: 12px; margin-top: 4px; display: block;">{{ passwordError }}</span>
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton @click="closeDialog">取消</ElButton>
      <ElButton type="primary" @click="submitRegister">注册</ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.role-select {
  width: 100%;
}

:global(.register-role-popper) {
  z-index: 5000 !important;
}

:global(.register-role-popper.el-popper) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.34);
  box-shadow: 0 18px 44px rgba(2, 8, 23, 0.62);
}

:global(.register-role-popper .el-select-dropdown__item) {
  color: #dbeafe;
}

:global(.register-role-popper .el-select-dropdown__item.is-hovering),
:global(.register-role-popper .el-select-dropdown__item:hover) {
  background: rgba(14, 165, 233, 0.18);
}

:global(.register-role-popper .el-select-dropdown__item.is-selected) {
  background: rgba(34, 211, 238, 0.18);
  color: #67e8f9;
}

:global(.register-role-popper .el-popper__arrow::before) {
  background: #0f172a;
  border-color: rgba(56, 189, 248, 0.34);
}

:global(.register-dialog-overlay) {
  z-index: 4000 !important;
}

:global(.register-dialog) {
  z-index: 4001 !important;
}

:global(.register-dialog.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  box-shadow: 0 26px 70px rgba(2, 8, 23, 0.72);
}

:global(.register-dialog .el-dialog__title),
:global(.register-dialog .el-form-item__label) {
  color: #e0f2fe;
}
</style>
