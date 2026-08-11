<script setup>
import { computed, onMounted, ref } from 'vue'
import * as echarts from 'echarts'

const apiBase = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const token = ref(localStorage.getItem('home_flow_token') || '')
const user = ref(JSON.parse(localStorage.getItem('home_flow_user') || 'null'))
const activePage = ref('dashboard')
const message = ref('')
const loginForm = ref({ username: 'admin', password: '' })
const question = ref('本月哪个小区成交最多？')
const answer = ref('')
const orders = ref([])
const tasks = ref([])
const overview = ref({})
const users = ref([])
const roles = ref([])
const permissions = ref([])
const cities = ref([])
const stores = ref([])
const newUser = ref({ username: '', display_name: '', password: '', city_id: null, store_id: null, role_codes: ['clerk'] })
const chartRef = ref(null)
const excelInputRef = ref(null)
const importing = ref(false)

const isLoggedIn = computed(() => Boolean(token.value && user.value))
const isAdmin = computed(() => user.value?.roles?.includes('admin'))
const canHandleTasks = computed(() => user.value?.roles?.some((role) => ['admin', 'store_manager'].includes(role)))

const menus = computed(() => [
  { key: 'dashboard', label: '首页' },
  { key: 'orders', label: '成交数据' },
  { key: 'qa', label: '智能问答' },
  ...(canHandleTasks.value ? [{ key: 'tasks', label: '每日待办' }] : []),
  ...(isAdmin.value ? [{ key: 'admin', label: '权限管理' }] : []),
])

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

async function login() {
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
    localStorage.setItem('home_flow_token', data.token)
    localStorage.setItem('home_flow_user', JSON.stringify(data))
    await loadAll()
  } catch (error) {
    message.value = error.message
  }
}

async function logout(callApi = true) {
  if (callApi && token.value) {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch {
      // Local session still gets cleared.
    }
  }
  token.value = ''
  user.value = null
  localStorage.removeItem('home_flow_token')
  localStorage.removeItem('home_flow_user')
}

async function loadOrders() {
  orders.value = await api('/api/orders?limit=20')
}

async function loadTasks() {
  if (canHandleTasks.value) tasks.value = await api('/api/tasks')
}

async function loadAdminData() {
  if (!isAdmin.value) return
  const [overviewData, usersData, rolesData, permissionsData, citiesData, storesData] = await Promise.all([
    api('/api/admin/overview'),
    api('/api/admin/users'),
    api('/api/admin/roles'),
    api('/api/admin/permissions'),
    api('/api/admin/cities'),
    api('/api/admin/stores'),
  ])
  overview.value = overviewData
  users.value = usersData
  roles.value = rolesData
  permissions.value = permissionsData
  cities.value = citiesData
  stores.value = storesData
}

async function loadAll() {
  message.value = ''
  await Promise.all([loadOrders(), loadTasks(), loadAdminData()])
}

async function scanImages() {
  try {
    const data = await api('/api/images/scan', { method: 'POST' })
    message.value = `扫描完成：已扫描 ${data.scanned} 张，入库 ${data.confirmed} 条，待确认 ${data.pending} 条`
    await loadAll()
  } catch (error) {
    message.value = error.message
  }
}

function chooseExcel() {
  excelInputRef.value?.click()
}

async function uploadExcel(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  importing.value = true
  message.value = ''
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${apiBase}/api/orders/import-excel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token.value}` },
      body: form,
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '导入失败')
    message.value = `导入完成：共 ${data.total} 行，成功 ${data.success} 行，跳过重复 ${data.skipped} 行，失败 ${data.failed} 行`
    await loadAll()
  } catch (error) {
    message.value = error.message
  } finally {
    importing.value = false
  }
}

async function ask() {
  try {
    const data = await api('/api/qa/ask', {
      method: 'POST',
      body: JSON.stringify({ question: question.value }),
    })
    answer.value = data.answer
    if (data.chart && chartRef.value) {
      const chart = echarts.getInstanceByDom(chartRef.value) || echarts.init(chartRef.value)
      chart.setOption({
        tooltip: {},
        grid: { left: 42, right: 18, top: 24, bottom: 54 },
        xAxis: { type: 'category', data: data.chart.x, axisLabel: { interval: 0, rotate: 28 } },
        yAxis: { type: 'value' },
        series: [{ type: data.chart.type, data: data.chart.y, itemStyle: { color: '#2563eb' } }],
      })
    }
  } catch (error) {
    answer.value = error.message
  }
}

async function createUser() {
  try {
    await api('/api/admin/users', { method: 'POST', body: JSON.stringify(newUser.value) })
    message.value = '用户已创建'
    newUser.value = { username: '', display_name: '', password: '', city_id: null, store_id: null, role_codes: ['clerk'] }
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

async function saveUserRoles(item) {
  try {
    const role_codes = String(item.role_codes || '').split(',').map((role) => role.trim()).filter(Boolean)
    await api(`/api/admin/users/${item.id}/roles`, { method: 'PUT', body: JSON.stringify({ role_codes }) })
    message.value = '角色已保存'
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

onMounted(async () => {
  if (isLoggedIn.value) {
    try {
      await loadAll()
    } catch (error) {
      message.value = error.message
    }
  }
})
</script>

<template>
  <main v-if="!isLoggedIn" class="login-page">
    <section class="login-panel">
      <h1>home-flow</h1>
      <p>二手房成交数据智能问答系统</p>
      <label>
        账号
        <input v-model="loginForm.username" autocomplete="username" />
      </label>
      <label>
        密码
        <input v-model="loginForm.password" type="password" autocomplete="current-password" @keyup.enter="login" />
      </label>
      <button @click="login">登录</button>
      <span class="error">{{ message }}</span>
    </section>
  </main>

  <main v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <strong>home-flow</strong>
        <span>{{ user.city }}</span>
      </div>
      <button
        v-for="menu in menus"
        :key="menu.key"
        class="nav-item"
        :class="{ active: activePage === menu.key }"
        @click="activePage = menu.key"
      >
        {{ menu.label }}
      </button>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <h1>{{ menus.find((item) => item.key === activePage)?.label }}</h1>
          <p>{{ user.display_name }} · {{ user.roles.join(', ') }}</p>
        </div>
        <div class="actions">
          <button v-if="canHandleTasks" @click="scanImages">扫描图片</button>
          <button class="secondary" @click="logout()">退出</button>
        </div>
      </header>

      <p v-if="message" class="notice">{{ message }}</p>

      <section v-if="activePage === 'dashboard'" class="cards">
        <article class="metric"><span>成交记录</span><strong>{{ overview.orders ?? orders.length }}</strong></article>
        <article class="metric"><span>待办</span><strong>{{ overview.pending_tasks ?? tasks.length }}</strong></article>
        <article class="metric"><span>用户</span><strong>{{ overview.users ?? '-' }}</strong></article>
        <article class="metric"><span>角色</span><strong>{{ overview.roles ?? '-' }}</strong></article>
      </section>

      <section v-if="activePage === 'orders'" class="panel">
        <div class="panel-header">
          <h2>最新成交</h2>
          <div>
            <input ref="excelInputRef" class="hidden-input" type="file" accept=".xlsx" @change="uploadExcel" />
            <button v-if="isAdmin" :disabled="importing" @click="chooseExcel">
              {{ importing ? '导入中...' : '导入成交数据' }}
            </button>
          </div>
        </div>
        <table>
          <thead>
            <tr><th>日期</th><th>楼盘</th><th>面积</th><th>成交价</th><th>经纪人</th><th>门店</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in orders" :key="item.ID">
              <td>{{ item.signing_date }}</td>
              <td>{{ item.residential }}</td>
              <td>{{ item.acreage }}</td>
              <td>{{ item.price }}</td>
              <td>{{ item.agent }}</td>
              <td>{{ item.store }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="activePage === 'qa'" class="panel">
        <div class="qa">
          <input v-model="question" @keyup.enter="ask" />
          <button @click="ask">提问</button>
        </div>
        <p class="answer">{{ answer }}</p>
        <div ref="chartRef" class="chart"></div>
      </section>

      <section v-if="activePage === 'tasks'" class="panel">
        <h2>每日待办</h2>
        <div v-for="task in tasks" :key="task.id" class="task">
          <strong>{{ task.title }}</strong>
          <span>{{ task.city }} · {{ task.reason }}</span>
        </div>
      </section>

      <section v-if="activePage === 'admin'" class="admin-grid">
        <div class="panel">
          <h2>创建用户</h2>
          <div class="form-grid">
            <input v-model="newUser.username" placeholder="登录账号" />
            <input v-model="newUser.display_name" placeholder="姓名" />
            <input v-model="newUser.password" type="password" placeholder="初始密码" />
            <select v-model="newUser.city_id">
              <option :value="null">默认城市</option>
              <option v-for="city in cities" :key="city.id" :value="city.id">{{ city.name }}</option>
            </select>
            <select v-model="newUser.store_id">
              <option :value="null">不指定门店</option>
              <option v-for="store in stores" :key="store.id" :value="store.id">{{ store.name }}</option>
            </select>
            <select v-model="newUser.role_codes[0]">
              <option v-for="role in roles" :key="role.code" :value="role.code">{{ role.name }}</option>
            </select>
          </div>
          <button @click="createUser">创建用户</button>
        </div>

        <div class="panel">
          <h2>用户与角色</h2>
          <table>
            <thead>
              <tr><th>账号</th><th>姓名</th><th>城市</th><th>门店</th><th>角色编码</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="item in users" :key="item.id">
                <td>{{ item.username }}</td>
                <td>{{ item.display_name }}</td>
                <td>{{ item.city }}</td>
                <td>{{ item.store }}</td>
                <td><input v-model="item.role_codes" /></td>
                <td><button class="small" @click="saveUserRoles(item)">保存</button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="panel">
          <h2>角色</h2>
          <table>
            <thead><tr><th>编码</th><th>名称</th><th>权限</th></tr></thead>
            <tbody>
              <tr v-for="role in roles" :key="role.id">
                <td>{{ role.code }}</td>
                <td>{{ role.name }}</td>
                <td>{{ role.permission_codes }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="panel">
          <h2>权限点</h2>
          <table>
            <thead><tr><th>编码</th><th>名称</th><th>类型</th></tr></thead>
            <tbody>
              <tr v-for="permission in permissions" :key="permission.id">
                <td>{{ permission.code }}</td>
                <td>{{ permission.name }}</td>
                <td>{{ permission.permission_type }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>
  </main>
</template>
