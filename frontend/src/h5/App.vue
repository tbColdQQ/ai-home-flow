<script setup>
import { computed, onMounted, ref } from 'vue'
import { ChatDotRound, Collection, User } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'

const apiBase = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const token = ref(localStorage.getItem('home_flow_h5_token') || '')
const user = ref(JSON.parse(localStorage.getItem('home_flow_h5_user') || 'null'))
const activeTab = ref('chat')
const message = ref('')
const loginForm = ref({ username: '', password: '' })
const isLoggingIn = ref(false)
const question = ref('')
const answer = ref('')
const isAsking = ref(false)
const knowledgeList = ref([])
const isLoadingKnowledge = ref(false)
const isUploadingKnowledge = ref(false)
const uploadFileList = ref([])
const knowledgeForm = ref({
  title: '',
  community_name: '',
  knowledge_type: '楼盘信息',
  content: '',
})
const passwordForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const isChangingPassword = ref(false)

const isLoggedIn = computed(() => Boolean(token.value && user.value))
const roleText = computed(() => (user.value?.roles || []).join(', '))

function authHeaders() {
  return { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' }
}

async function api(path, options = {}) {
  const res = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  })
  if (res.status === 401) {
    logout(false)
    throw new Error('登录已失效')
  }
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || data.error || '请求失败')
  return data
}

async function apiForm(path, formData) {
  const res = await fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token.value}` },
    body: formData,
  })
  if (res.status === 401) {
    logout(false)
    throw new Error('登录已失效')
  }
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || data.error || '请求失败')
  return data
}

async function login() {
  if (isLoggingIn.value) return
  isLoggingIn.value = true
  message.value = ''
  try {
    const res = await fetch(`${apiBase}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginForm.value),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '登录失败')
    token.value = data.token
    user.value = data
    localStorage.setItem('home_flow_h5_token', data.token)
    localStorage.setItem('home_flow_h5_user', JSON.stringify(data))
    await loadKnowledge()
  } catch (error) {
    message.value = error.message
  } finally {
    isLoggingIn.value = false
  }
}

async function logout(callApi = true) {
  if (callApi && token.value) {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch {
      // Local state is cleared even when the remote session already expired.
    }
  }
  token.value = ''
  user.value = null
  localStorage.removeItem('home_flow_h5_token')
  localStorage.removeItem('home_flow_h5_user')
}

function formatAnswer(value) {
  const text = String(value || '').trim()
  if (!text || text.includes('\n')) return text
  return text.replace(/([。！？；])\s*/g, '$1\n').trim()
}

async function ask() {
  const text = question.value.trim()
  if (!text || isAsking.value) return
  isAsking.value = true
  answer.value = ''
  message.value = ''
  try {
    const data = await api('/api/qa/ask', {
      method: 'POST',
      body: JSON.stringify({ question: text }),
    })
    answer.value = formatAnswer(data.answer)
  } catch (error) {
    message.value = error.message
  } finally {
    isAsking.value = false
  }
}

async function loadKnowledge() {
  if (!isLoggedIn.value || isLoadingKnowledge.value) return
  isLoadingKnowledge.value = true
  try {
    knowledgeList.value = await api('/api/qa/knowledge')
  } catch (error) {
    message.value = error.message
  } finally {
    isLoadingKnowledge.value = false
  }
}

function handleFileChange(file, files) {
  uploadFileList.value = files.slice(-1)
}

function handleFileRemove() {
  uploadFileList.value = []
}

async function uploadKnowledge() {
  if (isUploadingKnowledge.value) return
  isUploadingKnowledge.value = true
  message.value = ''
  try {
    const form = new FormData()
    form.append('title', knowledgeForm.value.title)
    form.append('community_name', knowledgeForm.value.community_name || '')
    form.append('knowledge_type', knowledgeForm.value.knowledge_type)
    form.append('content', knowledgeForm.value.content || '')
    const rawFile = uploadFileList.value[0]?.raw
    if (rawFile) form.append('file', rawFile)
    await apiForm('/api/qa/knowledge', form)
    knowledgeForm.value = { title: '', community_name: '', knowledge_type: '楼盘信息', content: '' }
    uploadFileList.value = []
    message.value = '知识已上传'
    await loadKnowledge()
  } catch (error) {
    message.value = error.message
  } finally {
    isUploadingKnowledge.value = false
  }
}

async function changePassword() {
  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
    message.value = '两次输入的新密码不一致'
    return
  }
  isChangingPassword.value = true
  try {
    await api('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        old_password: passwordForm.value.old_password,
        new_password: passwordForm.value.new_password,
      }),
    })
    await ElMessageBox.alert('密码已修改，请重新登录。', '修改成功', { confirmButtonText: '知道了' })
    logout(false)
  } catch (error) {
    message.value = error.message
  } finally {
    isChangingPassword.value = false
  }
}

function switchTab(name) {
  activeTab.value = name
  if (name === 'knowledge') loadKnowledge()
}

onMounted(async () => {
  if (isLoggedIn.value) {
    try {
      await loadKnowledge()
    } catch {
      logout(false)
    }
  }
})
</script>

<template>
  <main v-if="!isLoggedIn" class="login-page">
    <section class="login-card">
      <div>
        <h1>home-flow</h1>
        <p>店长 / 店员移动端</p>
      </div>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="账号">
          <el-input v-model="loginForm.username" placeholder="请输入账号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="loginForm.password" type="password" show-password placeholder="请输入密码" @keyup.enter="login" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="isLoggingIn" @click="login">登录</el-button>
      </el-form>
      <p v-if="message" class="notice">{{ message }}</p>
    </section>
  </main>

  <main v-else class="h5-shell">
    <header class="h5-header">
      <div>
        <strong>home-flow</strong>
        <span>{{ user.city }}</span>
      </div>
      <p>{{ user.display_name }}</p>
    </header>

    <p v-if="message" class="notice">{{ message }}</p>

    <section v-show="activeTab === 'chat'" class="page">
      <div class="chat-card">
        <el-input
          v-model="question"
          type="textarea"
          :rows="4"
          placeholder="问成交数据、楼盘资料、学区信息..."
        />
        <el-button type="primary" :loading="isAsking" @click="ask">发送</el-button>
      </div>
      <el-skeleton v-if="isAsking" :rows="5" animated />
      <article v-else-if="answer" class="answer-card">{{ answer }}</article>
    </section>

    <section v-show="activeTab === 'knowledge'" class="page">
      <section class="upload-card">
        <h2>上传知识</h2>
        <el-form label-position="top">
          <el-form-item label="标题">
            <el-input v-model="knowledgeForm.title" placeholder="例如：某小区学区信息" />
          </el-form-item>
          <el-form-item label="楼盘">
            <el-input v-model="knowledgeForm.community_name" placeholder="可选" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="knowledgeForm.knowledge_type">
              <el-option label="楼盘信息" value="楼盘信息" />
              <el-option label="学区信息" value="学区信息" />
              <el-option label="交易规则" value="交易规则" />
              <el-option label="其他" value="其他" />
            </el-select>
          </el-form-item>
          <el-form-item label="文字">
            <el-input v-model="knowledgeForm.content" type="textarea" :rows="4" placeholder="可直接粘贴文字" />
          </el-form-item>
          <el-form-item label="文件">
            <el-upload
              v-model:file-list="uploadFileList"
              :auto-upload="false"
              :limit="1"
              accept=".pdf,.txt,.md,.jpg,.jpeg,.png,.bmp,.webp"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
            >
              <el-button>选择 PDF / 图片 / 文本</el-button>
            </el-upload>
          </el-form-item>
          <el-button type="primary" :loading="isUploadingKnowledge" @click="uploadKnowledge">上传</el-button>
        </el-form>
      </section>

      <section class="knowledge-list">
        <div class="section-title">
          <h2>知识库</h2>
          <el-button size="small" :loading="isLoadingKnowledge" @click="loadKnowledge">刷新</el-button>
        </div>
        <article v-for="item in knowledgeList" :key="item.id" class="knowledge-item">
          <div>
            <strong>{{ item.title }}</strong>
            <el-tag size="small" effect="plain">{{ item.knowledge_type || '知识' }}</el-tag>
          </div>
          <p>{{ item.community_name || item.city }} · v{{ item.version }} · {{ item.create_time }}</p>
          <span>{{ item.summary }}</span>
        </article>
        <el-empty v-if="!isLoadingKnowledge && !knowledgeList.length" description="暂无知识" />
      </section>
    </section>

    <section v-show="activeTab === 'mine'" class="page">
      <section class="profile-card">
        <h2>{{ user.display_name }}</h2>
        <p>{{ user.username }}</p>
        <p>{{ user.city }} · {{ roleText }}</p>
      </section>
      <section class="password-card">
        <h2>修改密码</h2>
        <el-form label-position="top">
          <el-form-item label="原密码">
            <el-input v-model="passwordForm.old_password" type="password" show-password />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="passwordForm.new_password" type="password" show-password />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="passwordForm.confirm_password" type="password" show-password />
          </el-form-item>
          <el-button type="primary" :loading="isChangingPassword" @click="changePassword">保存新密码</el-button>
        </el-form>
      </section>
      <el-button class="logout-button" @click="logout()">退出登录</el-button>
    </section>

    <nav class="bottom-nav">
      <button :class="{ active: activeTab === 'chat' }" @click="switchTab('chat')">
        <el-icon><ChatDotRound /></el-icon>
        <span>聊天</span>
      </button>
      <button :class="{ active: activeTab === 'knowledge' }" @click="switchTab('knowledge')">
        <el-icon><Collection /></el-icon>
        <span>知识库</span>
      </button>
      <button :class="{ active: activeTab === 'mine' }" @click="switchTab('mine')">
        <el-icon><User /></el-icon>
        <span>我的</span>
      </button>
    </nav>
  </main>
</template>
