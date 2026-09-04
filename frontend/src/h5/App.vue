<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { Camera, ChatDotRound, Collection, User } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'

const apiBase = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const token = ref(localStorage.getItem('home_flow_h5_token') || '')
const user = ref(JSON.parse(localStorage.getItem('home_flow_h5_user') || 'null'))
const activeTab = ref('chat')
const message = ref('')
const loginForm = ref({ username: '', password: '' })
const isLoggingIn = ref(false)
const question = ref('')
const chatScrollRef = ref(null)
const imageInputRef = ref(null)
const chatChartEls = new Map()
const chatChartInstances = new Map()
const chatMessages = ref([
  { role: 'assistant', content: '你好，我可以帮你查询成交数据，也可以回答知识库里的楼盘、学区等信息。' },
])
const isAsking = ref(false)
const isUploadingQueryImage = ref(false)
const knowledgeList = ref([])
const isLoadingKnowledge = ref(false)
const isUploadingKnowledge = ref(false)
const uploadFileList = ref([])
const knowledgeForm = ref({
  title: '',
  community_name: '',
  knowledge_type: '楼盘信息',
  content: '',
  source_url: '',
})
const passwordForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const isChangingPassword = ref(false)
const pendingTasks = ref([])
const doneTasks = ref([])
const mineTaskTab = ref('pending')
const isLoadingTasks = ref(false)

const isLoggedIn = computed(() => Boolean(token.value && user.value))
const roleText = computed(() => (user.value?.roles || []).join(', '))

function authHeaders() {
  return { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' }
}

function apiUrl(path) {
  const base = String(apiBase || '').replace(/\/$/, '')
  if (base.endsWith('/api') && path.startsWith('/api/')) {
    return `${base}${path.slice(4)}`
  }
  return `${base}${path}`
}

async function api(path, options = {}) {
  const res = await fetch(apiUrl(path), {
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
  const res = await fetch(apiUrl(path), {
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

async function readNdjsonStream(res, onEvent) {
  const reader = res.body?.getReader()
  if (!reader) return
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      const text = line.trim()
      if (!text) continue
      onEvent(JSON.parse(text))
    }
  }
  buffer += decoder.decode()
  const text = buffer.trim()
  if (text) onEvent(JSON.parse(text))
}

async function login() {
  if (isLoggingIn.value) return
  isLoggingIn.value = true
  message.value = ''
  try {
    const res = await fetch(apiUrl('/api/auth/login'), {
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
  chatMessages.value.push({ role: 'user', content: text })
  const assistantMessage = { role: 'assistant', content: '正在连接智能问答...' }
  chatMessages.value.push(assistantMessage)
  question.value = ''
  message.value = ''
  await scrollChatToBottom()
  try {
    const res = await fetch(apiUrl('/api/qa/ask-stream'), {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ question: text }),
    })
    if (res.status === 401) {
      logout(false)
      throw new Error('登录已失效')
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || data.error || '请求失败')
    }
    let hasDelta = false
    await readNdjsonStream(res, (event) => {
      if (event.type === 'status' && !hasDelta) {
        assistantMessage.content = event.content
      } else if (event.type === 'timing') {
        assistantMessage.timing = [...(assistantMessage.timing || []), event]
      } else if (event.type === 'delta') {
        if (!hasDelta) {
          assistantMessage.content = ''
          hasDelta = true
        }
        assistantMessage.content += event.content || ''
      } else if (event.type === 'final') {
        const data = event.result || {}
        assistantMessage.content = formatAnswer(data.answer || assistantMessage.content)
        assistantMessage.sources = data.rag_context || []
        assistantMessage.dealResult = data.deal_result || null
        assistantMessage.chart = data.chart || null
        renderChatChart(assistantMessage)
      } else if (event.type === 'error') {
        throw new Error(event.content || '请求失败')
      }
      scrollChatToBottom()
    })
  } catch (error) {
    chatMessages.value[chatMessages.value.length - 1].content = error.message
  } finally {
    isAsking.value = false
    await scrollChatToBottom()
  }
}

function chooseQueryImage() {
  if (isAsking.value || isUploadingQueryImage.value) return
  imageInputRef.value?.click()
}

async function askWithImage(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || isUploadingQueryImage.value) return
  isUploadingQueryImage.value = true
  isAsking.value = true
  message.value = ''
  chatMessages.value.push({ role: 'user', content: `上传图片：${file.name}` })
  const assistantMessage = { role: 'assistant', content: '正在上传图片...', imageQuery: null, dealResult: null, sources: [] }
  chatMessages.value.push(assistantMessage)
  await scrollChatToBottom()
  try {
    const form = new FormData()
    form.append('file', file)
    if (question.value.trim()) form.append('question', question.value.trim())
    question.value = ''
    const res = await fetch(apiUrl('/api/qa/ask-image-stream'), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token.value}` },
      body: form,
    })
    if (res.status === 401) {
      logout(false)
      throw new Error('登录已失效')
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || data.error || '请求失败')
    }
    let hasDelta = false
    await readNdjsonStream(res, (streamEvent) => {
      if (streamEvent.type === 'status' && !hasDelta) {
        assistantMessage.content = streamEvent.content
      } else if (streamEvent.type === 'image_ocr') {
        assistantMessage.imageQuery = streamEvent.content
        assistantMessage.content = '图片已识别，正在查询相关信息...'
      } else if (streamEvent.type === 'deal_result') {
        assistantMessage.dealResult = streamEvent.content
      } else if (streamEvent.type === 'sources') {
        assistantMessage.sources = streamEvent.content || []
      } else if (streamEvent.type === 'delta') {
        if (!hasDelta) {
          assistantMessage.content = ''
          hasDelta = true
        }
        assistantMessage.content += streamEvent.content || ''
      } else if (streamEvent.type === 'final') {
        const data = streamEvent.result || {}
        assistantMessage.content = formatAnswer(data.answer || assistantMessage.content)
        assistantMessage.imageQuery = data.image_query || assistantMessage.imageQuery
        assistantMessage.dealResult = data.deal_result || assistantMessage.dealResult
        assistantMessage.sources = data.rag_context || assistantMessage.sources
        assistantMessage.chart = data.chart || assistantMessage.chart
        renderChatChart(assistantMessage)
      } else if (streamEvent.type === 'error') {
        throw new Error(streamEvent.content || '请求失败')
      }
      scrollChatToBottom()
    })
  } catch (error) {
    assistantMessage.content = error.message
  } finally {
    isUploadingQueryImage.value = false
    isAsking.value = false
    await scrollChatToBottom()
  }
}

async function scrollChatToBottom() {
  await nextTick()
  const el = chatScrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function setChatChartRef(el, index) {
  if (el) {
    chatChartEls.set(index, el)
    renderChatChart(chatMessages.value[index])
    return
  }
  const chart = chatChartInstances.get(index)
  if (chart) chart.dispose()
  chatChartInstances.delete(index)
  chatChartEls.delete(index)
}

async function renderChatChart(messageItem) {
  if (!messageItem?.chart) return
  await nextTick()
  const index = chatMessages.value.indexOf(messageItem)
  const el = chatChartEls.get(index)
  if (!el) return
  const chartData = messageItem.chart
  const chart = chatChartInstances.get(index) || echarts.init(el)
  chatChartInstances.set(index, chart)
  const series = Array.isArray(chartData.series) && chartData.series.length
    ? chartData.series
    : [{ name: '数量', type: chartData.type || 'bar', data: chartData.y || [] }]
  chart.setOption({
    color: ['#2563eb', '#16a34a', '#f97316'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { fontSize: 10 } },
    grid: { left: 40, right: 12, top: 38, bottom: 58 },
    xAxis: { type: 'category', data: chartData.x || [], axisLabel: { interval: 0, rotate: 35, fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
    series: series.map((item) => ({
      name: item.name,
      type: item.type || chartData.type || 'bar',
      data: item.data || [],
      smooth: item.type === 'line',
      barMaxWidth: 24,
    })),
  })
}

function resizeChatCharts() {
  chatChartInstances.forEach((chart) => chart.resize())
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
    form.append('source_url', knowledgeForm.value.source_url || '')
    const rawFile = uploadFileList.value[0]?.raw
    if (rawFile) form.append('file', rawFile)
    await apiForm('/api/qa/knowledge', form)
    knowledgeForm.value = { title: '', community_name: '', knowledge_type: '楼盘信息', content: '', source_url: '' }
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

function taskDescription(task) {
  const parts = [
    task.reason,
    task.community_name,
    task.address,
    task.file_name,
  ].filter(Boolean)
  return parts.join(' · ') || task.title
}

async function loadTasks() {
  if (!isLoggedIn.value || isLoadingTasks.value) return
  isLoadingTasks.value = true
  try {
    const [pending, done] = await Promise.all([
      api('/api/tasks?status=pending'),
      api('/api/tasks?status=done'),
    ])
    pendingTasks.value = pending
    doneTasks.value = done
  } catch (error) {
    message.value = error.message
  } finally {
    isLoadingTasks.value = false
  }
}

async function acknowledgeTask(task) {
  try {
    await api(`/api/tasks/${task.id}/acknowledge`, { method: 'POST' })
    message.value = '待办已转为已办'
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

async function deleteTask(task) {
  if (!task) return
  if (!window.confirm(`确认删除待办 ${task.title || task.id}？`)) return
  try {
    await api(`/api/tasks/${task.id}`, { method: 'DELETE' })
    message.value = '待办已删除'
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

function switchTab(name) {
  activeTab.value = name
  if (name === 'knowledge') loadKnowledge()
  if (name === 'mine') loadTasks()
}

onMounted(async () => {
  window.addEventListener('resize', resizeChatCharts)
  if (isLoggedIn.value) {
    await scrollChatToBottom()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChatCharts)
  chatChartInstances.forEach((chart) => chart.dispose())
  chatChartInstances.clear()
  chatChartEls.clear()
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

    <section v-show="activeTab === 'chat'" class="chat-page">
      <div ref="chatScrollRef" class="chat-thread">
        <article
          v-for="(item, index) in chatMessages"
          :key="index"
          class="chat-message"
          :class="item.role"
        >
          <div class="avatar">{{ item.role === 'user' ? '我' : 'AI' }}</div>
          <div class="message-body">
            <p>{{ item.content }}</p>
            <div
              v-if="item.role === 'assistant' && item.chart"
              :ref="(el) => setChatChartRef(el, index)"
              class="message-chart"
            />
            <div v-if="item.imageQuery" class="message-detail">
              <strong>图片识别</strong>
              <span>小区：{{ item.imageQuery.parsed?.residential || '-' }}</span>
              <span>面积：{{ item.imageQuery.parsed?.acreage || '-' }}</span>
              <span>维护人：{{ item.imageQuery.parsed?.maintainor || item.imageQuery.parsed?.CA || '-' }}</span>
              <span>价格：{{ item.imageQuery.parsed?.price || '-' }}</span>
            </div>
            <div v-if="item.dealResult?.rows?.length" class="message-detail">
              <strong>成交结果 {{ item.dealResult.total }}</strong>
              <span v-for="row in item.dealResult.rows.slice(0, 3)" :key="row.ID || row.residential">
                {{ row.signing_date || '-' }} · {{ row.residential || row.name || '-' }} · {{ row.price || row.count || '-' }}
              </span>
            </div>
            <div v-if="item.sources?.length" class="message-detail">
              <strong>知识来源 {{ item.sources.length }}</strong>
              <span v-for="source in item.sources.slice(0, 3)" :key="`${source.chunk_id}-${source.title}`">
                {{ source.title }} · v{{ source.version }}
              </span>
            </div>
            <div v-if="item.timing?.length" class="message-detail timing-detail">
              <strong>耗时</strong>
              <span v-for="step in item.timing" :key="`${step.step}-${step.total_ms}`">
                {{ step.step }}：{{ step.elapsed_ms }}ms
              </span>
            </div>
          </div>
        </article>
      </div>
      <div class="chat-composer">
        <input ref="imageInputRef" class="hidden-file-input" type="file" accept="image/*" capture="environment" @change="askWithImage" />
        <el-button :icon="Camera" :loading="isUploadingQueryImage" circle @click="chooseQueryImage" />
        <el-input
          v-model="question"
          type="textarea"
          autosize
          resize="none"
          placeholder="发送消息"
          @keyup.enter.exact.prevent="ask"
        />
        <el-button type="primary" :loading="isAsking" @click="ask">发送</el-button>
      </div>
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
          <el-form-item label="网页链接">
            <el-input v-model="knowledgeForm.source_url" placeholder="https://..." clearable />
          </el-form-item>
          <el-form-item label="文件">
            <el-upload
              v-model:file-list="uploadFileList"
              :auto-upload="false"
              :limit="1"
              accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.bmp,.webp"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
            >
              <el-button>选择 PDF / DOCX / 图片 / 文本</el-button>
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
      <section class="task-card">
        <div class="section-title">
          <h2>待办已办</h2>
          <el-button size="small" :loading="isLoadingTasks" @click="loadTasks">刷新</el-button>
        </div>
        <el-tabs v-model="mineTaskTab">
          <el-tab-pane :label="`待办 ${pendingTasks.length}`" name="pending">
            <article v-for="task in pendingTasks" :key="task.id" class="task-item">
              <div>
                <strong>{{ task.title }}</strong>
                <el-tag size="small" type="warning" effect="plain">待办</el-tag>
              </div>
              <p>{{ taskDescription(task) }}</p>
              <span>创建时间：{{ task.create_time || '-' }}</span>
              <el-button size="small" type="primary" @click="acknowledgeTask(task)">已知悉</el-button>
              <el-button size="small" type="danger" @click="deleteTask(task)">删除</el-button>
            </article>
            <el-empty v-if="!isLoadingTasks && !pendingTasks.length" description="暂无待办" />
          </el-tab-pane>
          <el-tab-pane :label="`已办 ${doneTasks.length}`" name="done">
            <article v-for="task in doneTasks" :key="task.id" class="task-item done">
              <div>
                <strong>{{ task.title }}</strong>
                <el-tag size="small" type="success" effect="plain">已办</el-tag>
              </div>
              <p>{{ taskDescription(task) }}</p>
              <span>处理人：{{ task.handler_name || '-' }}</span>
              <span>创建时间：{{ task.create_time || '-' }}</span>
              <span>完成时间：{{ task.finish_time || '-' }}</span>
              <el-button size="small" type="danger" @click="deleteTask(task)">删除</el-button>
            </article>
            <el-empty v-if="!isLoadingTasks && !doneTasks.length" description="暂无已办" />
          </el-tab-pane>
        </el-tabs>
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
