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
const orderTotal = ref(0)
const orderPage = ref(1)
const orderPageSize = ref(20)
const orderFilters = ref({
  start_date: '',
  end_date: '',
  residential: '',
  agent: '',
  area: '',
  acreage_min: '',
  acreage_max: '',
  price_min_wan: '',
  price_max_wan: '',
})
const selectedOrder = ref(null)
const orderDialogMode = ref('detail')
const orderForm = ref({})
const tasks = ref([])
const selectedTask = ref(null)
const taskForm = ref({})
const taskRemark = ref('')
const overview = ref({})
const users = ref([])
const roles = ref([])
const permissions = ref([])
const cities = ref([])
const stores = ref([])
const newUser = ref({ username: '', display_name: '', password: '', city_id: null, store_id: null, role_codes: ['clerk'] })
const storeForm = ref({ id: null, city_id: null, name: '', area: '', street: '', status: 'active' })
const roleForm = ref({ id: null, code: '', name: '', description: '', permission_codes_text: '' })
const permissionForm = ref({ id: null, code: '', name: '', permission_type: 'api', description: '' })
const chartRef = ref(null)
const excelInputRef = ref(null)
const importing = ref(false)

const isLoggedIn = computed(() => Boolean(token.value && user.value))
const isAdmin = computed(() => user.value?.roles?.includes('admin'))
const isStoreManager = computed(() => user.value?.roles?.includes('store_manager'))
const canHandleTasks = computed(() => user.value?.roles?.some((role) => ['admin', 'store_manager'].includes(role)))
const canManageUsers = computed(() => isAdmin.value || isStoreManager.value)
const canEditOrders = computed(() => isAdmin.value || isStoreManager.value)
const totalPages = computed(() => Math.max(1, Math.ceil(orderTotal.value / orderPageSize.value)))

const menus = computed(() => [
  { key: 'dashboard', label: '首页' },
  { key: 'orders', label: '成交数据' },
  { key: 'qa', label: '智能问答' },
  ...(canHandleTasks.value ? [{ key: 'tasks', label: '每日待办' }] : []),
  ...(canManageUsers.value ? [{ key: 'admin', label: isAdmin.value ? '权限管理' : '用户管理' }] : []),
])

const orderFields = [
  ['signing_date', '签约日期', 'date'],
  ['area', '区域', 'text'],
  ['street', '街道', 'text'],
  ['residential', '楼盘', 'text'],
  ['room_number', '房号', 'text'],
  ['acreage', '面积', 'number'],
  ['price', '成交价', 'number'],
  ['list_price', '挂牌价', 'number'],
  ['agent', '经纪人', 'text'],
  ['store', '门店', 'text'],
  ['brand', '品牌', 'text'],
  ['maintainor', '维护人', 'text'],
  ['CA', 'CA', 'text'],
  ['location', '位置', 'text'],
  ['remark', '备注', 'text'],
]

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
      // 本地会话仍然清理。
    }
  }
  token.value = ''
  user.value = null
  localStorage.removeItem('home_flow_token')
  localStorage.removeItem('home_flow_user')
}

function appendParam(params, key, value) {
  if (value !== null && value !== undefined && value !== '') params.set(key, value)
}

function rolePayloadText(text) {
  return String(text || '').split(',').map((item) => item.trim()).filter(Boolean)
}

function resetForms() {
  storeForm.value = { id: null, city_id: cities.value[0]?.id ?? null, name: '', area: '', street: '', status: 'active' }
  roleForm.value = { id: null, code: '', name: '', description: '', permission_codes_text: '' }
  permissionForm.value = { id: null, code: '', name: '', permission_type: 'api', description: '' }
}

async function loadOrders() {
  const params = new URLSearchParams()
  params.set('page', orderPage.value)
  params.set('page_size', orderPageSize.value)
  appendParam(params, 'start_date', orderFilters.value.start_date)
  appendParam(params, 'end_date', orderFilters.value.end_date)
  appendParam(params, 'residential', orderFilters.value.residential)
  appendParam(params, 'agent', orderFilters.value.agent)
  appendParam(params, 'area', orderFilters.value.area)
  appendParam(params, 'acreage_min', orderFilters.value.acreage_min)
  appendParam(params, 'acreage_max', orderFilters.value.acreage_max)
  appendParam(params, 'price_min', orderFilters.value.price_min_wan ? Number(orderFilters.value.price_min_wan) * 10000 : '')
  appendParam(params, 'price_max', orderFilters.value.price_max_wan ? Number(orderFilters.value.price_max_wan) * 10000 : '')
  const data = await api(`/api/orders?${params.toString()}`)
  orders.value = data.items
  orderTotal.value = data.total
  orderPage.value = data.page
  orderPageSize.value = data.page_size
}

async function loadTasks() {
  if (canHandleTasks.value) tasks.value = await api('/api/tasks')
}

async function loadAdminData() {
  if (!canManageUsers.value) return
  const usersData = await api('/api/admin/users')
  users.value = usersData
  if (!isAdmin.value) return
  const [overviewData, rolesData, permissionsData, citiesData, storesData] = await Promise.all([
    api('/api/admin/overview'),
    api('/api/admin/roles'),
    api('/api/admin/permissions'),
    api('/api/admin/cities'),
    api('/api/admin/stores'),
  ])
  overview.value = overviewData
  roles.value = rolesData
  permissions.value = permissionsData
  cities.value = citiesData
  stores.value = storesData
  if (!storeForm.value.city_id) resetForms()
}

async function loadAll() {
  message.value = ''
  await Promise.all([loadOrders(), loadTasks(), loadAdminData()])
}

async function applyOrderFilters() {
  orderPage.value = 1
  await loadOrders()
}

async function resetOrderFilters() {
  orderFilters.value = {
    start_date: '',
    end_date: '',
    residential: '',
    agent: '',
    area: '',
    acreage_min: '',
    acreage_max: '',
    price_min_wan: '',
    price_max_wan: '',
  }
  orderPage.value = 1
  await loadOrders()
}

async function changeOrderPage(nextPage) {
  orderPage.value = Math.min(Math.max(nextPage, 1), totalPages.value)
  await loadOrders()
}

async function changeOrderPageSize() {
  orderPage.value = 1
  await loadOrders()
}

async function openOrder(item, mode = 'detail') {
  const detail = await api(`/api/orders/${item.ID}`)
  selectedOrder.value = detail
  orderDialogMode.value = mode
  orderForm.value = { ...detail }
}

function closeOrderDialog() {
  selectedOrder.value = null
  orderForm.value = {}
}

function taskPayload(item) {
  if (item.payload_json) {
    try {
      return JSON.parse(item.payload_json)
    } catch {
      // 使用默认表单兜底。
    }
  }
  return {
    city: item.city || user.value?.city,
    signing_date: item.business_date || '',
    residential: '',
    price: null,
    acreage: null,
    agent: '',
    store: item.store || '',
    CA: '',
    status: 'normal',
    source_type: item.source_type,
    source_id: item.source_id,
  }
}

function openTask(item) {
  selectedTask.value = item
  taskForm.value = taskPayload(item)
  taskRemark.value = item.reason || ''
}

function closeTaskDialog() {
  selectedTask.value = null
  taskForm.value = {}
  taskRemark.value = ''
}

async function saveTaskDraft() {
  try {
    await api(`/api/tasks/${selectedTask.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({ order: taskForm.value, remark: taskRemark.value }),
    })
    message.value = '待办已保存'
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

async function completeTask() {
  try {
    const data = await api(`/api/tasks/${selectedTask.value.id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ order: taskForm.value, remark: taskRemark.value }),
    })
    message.value = `待办已确认入库，订单 ID：${data.order_id}`
    closeTaskDialog()
    await loadAll()
  } catch (error) {
    message.value = error.message
  }
}

async function deleteTask(item = selectedTask.value) {
  if (!item) return
  if (!window.confirm(`确认删除待办 ${item.title || item.id}？`)) return
  try {
    await api(`/api/tasks/${item.id}`, { method: 'DELETE' })
    message.value = '待办已删除'
    closeTaskDialog()
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

async function saveOrder() {
  try {
    const payload = { ...orderForm.value }
    delete payload.ID
    const updated = await api(`/api/orders/${selectedOrder.value.ID}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    message.value = '成交记录已保存'
    selectedOrder.value = updated
    orderForm.value = { ...updated }
    orderDialogMode.value = 'detail'
    await loadOrders()
  } catch (error) {
    message.value = error.message
  }
}

async function deleteOrder(item) {
  if (!window.confirm(`确认删除 ${item.residential || ''} 的成交记录？`)) return
  try {
    await api(`/api/orders/${item.ID}`, { method: 'DELETE' })
    message.value = '成交记录已删除'
    closeOrderDialog()
    await loadOrders()
  } catch (error) {
    message.value = error.message
  }
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
    orderPage.value = 1
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
    const role_codes = rolePayloadText(item.role_codes)
    await api(`/api/admin/users/${item.id}/roles`, { method: 'PUT', body: JSON.stringify({ role_codes }) })
    message.value = '角色已保存'
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

async function deleteUser(item) {
  if (!window.confirm(`确认删除用户 ${item.username}？`)) return
  try {
    await api(`/api/admin/users/${item.id}`, { method: 'DELETE' })
    message.value = '用户已删除'
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

async function resetUserPassword(item) {
  try {
    const data = await api(`/api/admin/users/${item.id}/reset-password`, { method: 'POST' })
    message.value = `${item.username} 的新密码：${data.password}`
  } catch (error) {
    message.value = error.message
  }
}

async function saveStore() {
  try {
    const method = storeForm.value.id ? 'PUT' : 'POST'
    const path = storeForm.value.id ? `/api/admin/stores/${storeForm.value.id}` : '/api/admin/stores'
    await api(path, { method, body: JSON.stringify(storeForm.value) })
    message.value = '门店已保存'
    resetForms()
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

function editStore(item) {
  storeForm.value = { id: item.id, city_id: item.city_id, name: item.name, area: item.area || '', street: item.street || '', status: item.status || 'active' }
}

async function deleteStore(item) {
  if (!window.confirm(`确认删除门店 ${item.name}？`)) return
  try {
    await api(`/api/admin/stores/${item.id}`, { method: 'DELETE' })
    message.value = '门店已删除'
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

async function saveRole() {
  try {
    const payload = {
      code: roleForm.value.code,
      name: roleForm.value.name,
      description: roleForm.value.description,
      permission_codes: rolePayloadText(roleForm.value.permission_codes_text),
    }
    const method = roleForm.value.id ? 'PUT' : 'POST'
    const path = roleForm.value.id ? `/api/admin/roles/${roleForm.value.id}` : '/api/admin/roles'
    await api(path, { method, body: JSON.stringify(payload) })
    message.value = '角色已保存'
    resetForms()
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

function editRole(item) {
  roleForm.value = {
    id: item.id,
    code: item.code,
    name: item.name,
    description: item.description || '',
    permission_codes_text: item.permission_codes || '',
  }
}

async function deleteRole(item) {
  if (!window.confirm(`确认删除角色 ${item.name}？`)) return
  try {
    await api(`/api/admin/roles/${item.id}`, { method: 'DELETE' })
    message.value = '角色已删除'
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

async function savePermission() {
  try {
    const method = permissionForm.value.id ? 'PUT' : 'POST'
    const path = permissionForm.value.id ? `/api/admin/permissions/${permissionForm.value.id}` : '/api/admin/permissions'
    await api(path, { method, body: JSON.stringify(permissionForm.value) })
    message.value = '权限已保存'
    resetForms()
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

function editPermission(item) {
  permissionForm.value = {
    id: item.id,
    code: item.code,
    name: item.name,
    permission_type: item.permission_type,
    description: item.description || '',
  }
}

async function deletePermission(item) {
  if (!window.confirm(`确认删除权限 ${item.name}？`)) return
  try {
    await api(`/api/admin/permissions/${item.id}`, { method: 'DELETE' })
    message.value = '权限已删除'
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
        <article class="metric"><span>成交记录</span><strong>{{ overview.orders ?? orderTotal }}</strong></article>
        <article class="metric"><span>待办</span><strong>{{ overview.pending_tasks ?? tasks.length }}</strong></article>
        <article class="metric"><span>用户</span><strong>{{ overview.users ?? '-' }}</strong></article>
        <article class="metric"><span>角色</span><strong>{{ overview.roles ?? '-' }}</strong></article>
      </section>

      <section v-if="activePage === 'orders'" class="panel">
        <div class="panel-header">
          <h2>成交数据</h2>
          <div>
            <input ref="excelInputRef" class="hidden-input" type="file" accept=".xlsx" @change="uploadExcel" />
            <button v-if="isAdmin" :disabled="importing" @click="chooseExcel">
              {{ importing ? '导入中...' : '导入成交数据' }}
            </button>
          </div>
        </div>

        <section class="filters">
          <label>开始日期<input v-model="orderFilters.start_date" type="date" /></label>
          <label>结束日期<input v-model="orderFilters.end_date" type="date" /></label>
          <label>楼盘<input v-model="orderFilters.residential" placeholder="小区/楼盘" @keyup.enter="applyOrderFilters" /></label>
          <label>经纪人<input v-model="orderFilters.agent" placeholder="成交人" @keyup.enter="applyOrderFilters" /></label>
          <label>区域<input v-model="orderFilters.area" placeholder="区域" @keyup.enter="applyOrderFilters" /></label>
          <label>面积下限<input v-model="orderFilters.acreage_min" type="number" min="0" placeholder="平方米" /></label>
          <label>面积上限<input v-model="orderFilters.acreage_max" type="number" min="0" placeholder="平方米" /></label>
          <label>成交价下限<input v-model="orderFilters.price_min_wan" type="number" min="0" placeholder="万元" /></label>
          <label>成交价上限<input v-model="orderFilters.price_max_wan" type="number" min="0" placeholder="万元" /></label>
          <div class="filter-actions">
            <button @click="applyOrderFilters">筛选</button>
            <button class="secondary" @click="resetOrderFilters">重置</button>
          </div>
        </section>

        <div class="table-meta">
          <span>共 {{ orderTotal }} 条</span>
          <select v-model.number="orderPageSize" @change="changeOrderPageSize">
            <option :value="20">20 条/页</option>
            <option :value="50">50 条/页</option>
            <option :value="100">100 条/页</option>
          </select>
        </div>

        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>区域</th>
              <th>街道</th>
              <th>楼盘</th>
              <th>面积</th>
              <th>成交价</th>
              <th>经纪人</th>
              <th>门店</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in orders" :key="item.ID">
              <td>{{ item.signing_date }}</td>
              <td>{{ item.area }}</td>
              <td>{{ item.street }}</td>
              <td>{{ item.residential }}</td>
              <td>{{ item.acreage }}</td>
              <td>{{ item.price }}</td>
              <td>{{ item.agent }}</td>
              <td>{{ item.store }}</td>
              <td class="row-actions">
                <button class="small secondary" @click="openOrder(item)">详情</button>
                <button v-if="canEditOrders" class="small secondary" @click="openOrder(item, 'edit')">修改</button>
                <button v-if="canEditOrders" class="small danger" @click="deleteOrder(item)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="pagination">
          <button class="secondary" :disabled="orderPage <= 1" @click="changeOrderPage(orderPage - 1)">上一页</button>
          <span>第 {{ orderPage }} / {{ totalPages }} 页</span>
          <button class="secondary" :disabled="orderPage >= totalPages" @click="changeOrderPage(orderPage + 1)">下一页</button>
        </div>
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
        <div class="panel-header">
          <h2>每日待办</h2>
          <button class="secondary" @click="loadTasks">刷新</button>
        </div>
        <div v-if="!tasks.length" class="empty">暂无待办</div>
        <div v-for="task in tasks" :key="task.id" class="task">
          <div>
            <strong>{{ task.title }}</strong>
            <span>{{ task.city }} · {{ task.file_name || task.source_type }} · {{ task.reason }}</span>
          </div>
          <div class="row-actions">
            <button class="small secondary" @click="openTask(task)">修改/确认</button>
            <button class="small danger" @click="deleteTask(task)">删除</button>
          </div>
        </div>
      </section>

      <section v-if="activePage === 'admin'" class="admin-grid">
        <div v-if="isAdmin" class="panel">
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
              <tr><th>账号</th><th>姓名</th><th>城市</th><th>门店</th><th>角色编码</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in users" :key="item.id">
                <td>{{ item.username }}</td>
                <td>{{ item.display_name }}</td>
                <td>{{ item.city }}</td>
                <td>{{ item.store }}</td>
                <td><input v-if="isAdmin" v-model="item.role_codes" /><span v-else>{{ item.role_codes }}</span></td>
                <td class="row-actions">
                  <button v-if="isAdmin" class="small secondary" @click="saveUserRoles(item)">保存</button>
                  <button class="small secondary" @click="resetUserPassword(item)">重置密码</button>
                  <button v-if="isAdmin" class="small danger" @click="deleteUser(item)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="isAdmin" class="panel">
          <h2>门店管理</h2>
          <div class="form-grid">
            <select v-model="storeForm.city_id">
              <option v-for="city in cities" :key="city.id" :value="city.id">{{ city.name }}</option>
            </select>
            <input v-model="storeForm.name" placeholder="门店名称" />
            <input v-model="storeForm.area" placeholder="区域" />
            <input v-model="storeForm.street" placeholder="街道" />
            <select v-model="storeForm.status">
              <option value="active">active</option>
              <option value="disabled">disabled</option>
            </select>
          </div>
          <div class="actions">
            <button @click="saveStore">{{ storeForm.id ? '保存门店' : '新增门店' }}</button>
            <button class="secondary" @click="resetForms">清空</button>
          </div>
          <table>
            <thead><tr><th>城市</th><th>门店</th><th>区域</th><th>街道</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="store in stores" :key="store.id">
                <td>{{ store.city }}</td>
                <td>{{ store.name }}</td>
                <td>{{ store.area }}</td>
                <td>{{ store.street }}</td>
                <td>{{ store.status }}</td>
                <td class="row-actions">
                  <button class="small secondary" @click="editStore(store)">修改</button>
                  <button class="small danger" @click="deleteStore(store)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="isAdmin" class="panel">
          <h2>角色管理</h2>
          <div class="form-grid">
            <input v-model="roleForm.code" placeholder="角色编码" />
            <input v-model="roleForm.name" placeholder="角色名称" />
            <input v-model="roleForm.description" placeholder="说明" />
            <input v-model="roleForm.permission_codes_text" placeholder="权限编码，逗号分隔" />
          </div>
          <div class="actions">
            <button @click="saveRole">{{ roleForm.id ? '保存角色' : '新增角色' }}</button>
            <button class="secondary" @click="resetForms">清空</button>
          </div>
          <table>
            <thead><tr><th>编码</th><th>名称</th><th>权限</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="role in roles" :key="role.id">
                <td>{{ role.code }}</td>
                <td>{{ role.name }}</td>
                <td>{{ role.permission_codes }}</td>
                <td class="row-actions">
                  <button class="small secondary" @click="editRole(role)">修改</button>
                  <button class="small danger" @click="deleteRole(role)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="isAdmin" class="panel">
          <h2>权限点管理</h2>
          <div class="form-grid">
            <input v-model="permissionForm.code" placeholder="权限编码" />
            <input v-model="permissionForm.name" placeholder="权限名称" />
            <input v-model="permissionForm.permission_type" placeholder="类型" />
            <input v-model="permissionForm.description" placeholder="说明" />
          </div>
          <div class="actions">
            <button @click="savePermission">{{ permissionForm.id ? '保存权限' : '新增权限' }}</button>
            <button class="secondary" @click="resetForms">清空</button>
          </div>
          <table>
            <thead><tr><th>编码</th><th>名称</th><th>类型</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="permission in permissions" :key="permission.id">
                <td>{{ permission.code }}</td>
                <td>{{ permission.name }}</td>
                <td>{{ permission.permission_type }}</td>
                <td class="row-actions">
                  <button class="small secondary" @click="editPermission(permission)">修改</button>
                  <button class="small danger" @click="deletePermission(permission)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>

    <div v-if="selectedOrder" class="dialog-backdrop" @click.self="closeOrderDialog">
      <section class="dialog">
        <div class="panel-header">
          <h2>{{ orderDialogMode === 'edit' ? '修改成交记录' : '成交详情' }}</h2>
          <button class="secondary" @click="closeOrderDialog">关闭</button>
        </div>
        <div class="form-grid">
          <label v-for="[key, label, type] in orderFields" :key="key">
            {{ label }}
            <input v-if="orderDialogMode === 'edit'" v-model="orderForm[key]" :type="type" />
            <span v-else class="readonly">{{ selectedOrder[key] || '-' }}</span>
          </label>
          <label>
            车位
            <select v-if="orderDialogMode === 'edit'" v-model.number="orderForm.parking">
              <option :value="0">无</option>
              <option :value="1">有</option>
            </select>
            <span v-else class="readonly">{{ selectedOrder.parking ? '有' : '无' }}</span>
          </label>
        </div>
        <div class="actions">
          <button v-if="orderDialogMode === 'detail' && canEditOrders" @click="orderDialogMode = 'edit'">修改</button>
          <button v-if="orderDialogMode === 'edit'" @click="saveOrder">保存</button>
          <button v-if="canEditOrders" class="danger" @click="deleteOrder(selectedOrder)">删除</button>
        </div>
      </section>
    </div>

    <div v-if="selectedTask" class="dialog-backdrop" @click.self="closeTaskDialog">
      <section class="dialog">
        <div class="panel-header">
          <h2>处理待办</h2>
          <button class="secondary" @click="closeTaskDialog">关闭</button>
        </div>
        <div class="task-source">
          <strong>{{ selectedTask.file_name || selectedTask.title }}</strong>
          <span>{{ selectedTask.city }} · {{ selectedTask.business_date || '-' }}</span>
          <p>{{ selectedTask.reason }}</p>
          <pre v-if="selectedTask.ocr_text">{{ selectedTask.ocr_text }}</pre>
        </div>
        <div class="form-grid">
          <label v-for="[key, label, type] in orderFields" :key="key">
            {{ label }}
            <input v-model="taskForm[key]" :type="type" />
          </label>
          <label>
            车位
            <select v-model.number="taskForm.parking">
              <option :value="0">无</option>
              <option :value="1">有</option>
            </select>
          </label>
          <label>
            处理备注
            <input v-model="taskRemark" />
          </label>
        </div>
        <div class="actions">
          <button class="secondary" @click="saveTaskDraft">保存修改</button>
          <button @click="completeTask">确认入库</button>
          <button class="danger" @click="deleteTask()">删除待办</button>
        </div>
      </section>
    </div>
  </main>
</template>
