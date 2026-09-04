<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessageBox } from 'element-plus'

const apiBase = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const token = ref(localStorage.getItem('home_flow_token') || '')
const user = ref(JSON.parse(localStorage.getItem('home_flow_user') || 'null'))
const activePage = ref('dashboard')
const message = ref('')
const loginForm = ref({ username: 'admin', password: '' })
const showPasswordDialog = ref(false)
const passwordForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const isChangingPassword = ref(false)
const question = ref('本月哪个小区成交最多？')
const answer = ref('')
const qaStatus = ref('')
const qaMode = ref('auto')
const qaMessages = ref([])
const qaConversationId = ref(null)
const qaDealQuery = ref(null)
const qaDealResult = ref(null)
const qaRouter = ref(null)
const qaScrollRef = ref(null)
const qaChartEls = new Map()
const qaChartInstances = new Map()
const isAsking = ref(false)
const orders = ref([])
const orderTotal = ref(0)
const orderPage = ref(1)
const orderPageSize = ref(20)
const leases = ref([])
const leaseTotal = ref(0)
const leasePage = ref(1)
const leasePageSize = ref(20)
const leaseFilters = ref({ community_name: '', price_min: '', price_max: '', sort_by: 'lease_expire_date', sort_order: 'asc' })
const selectedLease = ref(null)
const leaseDialogMode = ref('detail')
const leaseForm = ref({})
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
  sort_by: '',
  sort_order: '',
})
const selectedOrder = ref(null)
const orderDialogMode = ref('detail')
const orderForm = ref({})
const tasks = ref([])
const selectedTask = ref(null)
const taskForm = ref({})
const taskRemark = ref('')
const taskStatus = ref('pending')
const dutyMonth = ref(new Date().toISOString().slice(0, 7))
const dutyCalendarDate = ref(new Date())
const dutyDays = ref([])
const dutyRoster = ref([])
const selectedDutyDay = ref(null)
const selectedDutyUserId = ref(null)
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
const leaseExcelInputRef = ref(null)
const knowledgeFileList = ref([])
const knowledgeSources = ref([])
const knowledgeDocuments = ref([])
const knowledgeForm = ref({
  title: '',
  community_name: '',
  knowledge_type: '楼盘信息',
  content: '',
  source_url: '',
})
const isUploadingKnowledge = ref(false)
const importing = ref(false)
const importingLeases = ref(false)
const showScanDialog = ref(false)
const scanDate = ref(new Date().toISOString().slice(0, 10))
const isScanning = ref(false)
const isUploadingImages = ref(false)
const imageUploadRef = ref(null)
const imageUploadFileList = ref([])
const scanDetails = ref([])
const scanResultDetails = ref([])
const showScanResultDialog = ref(false)
const MAX_SCAN_IMAGE_FILES = 10

const isLoggedIn = computed(() => Boolean(token.value && user.value))
const isAdmin = computed(() => user.value?.roles?.includes('admin'))
const isStoreManager = computed(() => user.value?.roles?.includes('store_manager'))
const isClerkAdmin = computed(() => user.value?.roles?.includes('clerk_admin'))
const canHandleTasks = computed(() => user.value?.roles?.some((role) => ['admin', 'store_manager', 'clerk_admin', 'rental_agent', 'rental_clerk'].includes(role)))
const canScanImages = computed(() => user.value?.roles?.some((role) => ['admin', 'store_manager', 'clerk_admin'].includes(role)))
const canManageUsers = computed(() => isAdmin.value || isStoreManager.value)
const canEditOrders = computed(() => isAdmin.value || isStoreManager.value)
const canDeleteOrders = computed(() => isStoreManager.value || isClerkAdmin.value)
const canEditDuty = computed(() => isAdmin.value || isStoreManager.value)
const canManageLeases = computed(() => user.value?.roles?.some((role) => ['admin', 'store_manager', 'rental_agent', 'rental_clerk'].includes(role)))
const canManageKnowledge = computed(() => isLoggedIn.value)
const showDutyCalendar = false
const hasSelectedImageFiles = computed(() => imageUploadFileList.value.some((item) => item.raw instanceof File))
const newScanOrderResults = computed(() => scanResultDetails.value.filter((item) => item.status === 'confirmed'))
const reviewScanResults = computed(() => scanResultDetails.value.filter((item) => ['pending', 'failed'].includes(item.status)))
const totalPages = computed(() => Math.max(1, Math.ceil(orderTotal.value / orderPageSize.value)))
const leaseTotalPages = computed(() => Math.max(1, Math.ceil(leaseTotal.value / leasePageSize.value)))
const todayText = computed(() => formatDate(new Date()))
const dutyDayMap = computed(() => {
  const map = {}
  dutyDays.value.forEach((day) => {
    map[day.date] = day
  })
  return map
})
const todayDuty = computed(() => dutyDayMap.value[todayText.value])

const menus = computed(() => [
  { key: 'dashboard', label: '首页' },
  { key: 'orders', label: '成交数据' },
  ...(canManageLeases.value ? [{ key: 'leases', label: '租赁房源' }] : []),
  { key: 'qa', label: '智能问答' },
  ...(canManageKnowledge.value ? [{ key: 'knowledge', label: '知识库管理' }] : []),
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
  ['agent', '成交人', 'text'],
  ['store', '成交人门店', 'text'],
  ['brand', '品牌', 'text'],
  ['maintainor', '维护人', 'text'],
  ['maintainor_store', '维护人门店', 'text'],
  ['CA', 'CA', 'text'],
  ['location', '位置', 'text'],
  ['remark', '备注', 'text'],
]

const imageTaskFields = [
  ['signing_date', '成交日期'],
  ['agent', '成交人'],
  ['maintainor', '维护人'],
  ['residential', '成交小区'],
  ['acreage', '面积'],
  ['price', '成交价'],
]
const imageTaskMissingReasonMap = {
  signing_date: ['成交日期缺失', '签约日期缺失'],
  agent: ['成交人缺失'],
  maintainor: ['维护人缺失'],
  residential: ['楼盘缺失', '成交小区缺失'],
  acreage: ['房源面积缺失', '面积缺失'],
  price: ['成交价格缺失', '成交价缺失'],
}

const leaseFields = [
  ['community_name', '小区名称', 'text'],
  ['address', '房源地址', 'text'],
  ['acreage', '面积', 'number'],
  ['price', '价格', 'number'],
  ['listing_date', '挂牌时间', 'text'],
  ['rental_type', '出租方式', 'text'],
  ['recorder', '录入人', 'text'],
  ['maintainor', '维护人', 'text'],
  ['agent', '成交人', 'text'],
  ['deal_date', '成交日期', 'date'],
  ['lease_expire_date', '租期到期时间', 'date'],
  ['cancel_time', '核销时间', 'date'],
  ['cancel_reason', '核销原因', 'text'],
  ['owner_phone', '业主电话', 'text'],
  ['customer_phone', '客户电话', 'text'],
]

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

function normalizeRoleCodes(value) {
  if (Array.isArray(value)) return value
  return rolePayloadText(value)
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
  appendParam(params, 'sort_by', orderFilters.value.sort_by)
  appendParam(params, 'sort_order', orderFilters.value.sort_order)
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

async function loadLeases() {
  if (!canManageLeases.value) return
  const params = new URLSearchParams()
  params.set('page', leasePage.value)
  params.set('page_size', leasePageSize.value)
  appendParam(params, 'community_name', leaseFilters.value.community_name)
  appendParam(params, 'price_min', leaseFilters.value.price_min)
  appendParam(params, 'price_max', leaseFilters.value.price_max)
  appendParam(params, 'sort_by', leaseFilters.value.sort_by)
  appendParam(params, 'sort_order', leaseFilters.value.sort_order)
  const data = await api(`/api/leases?${params.toString()}`)
  leases.value = data.items
  leaseTotal.value = data.total
  leasePage.value = data.page
  leasePageSize.value = data.page_size
}

async function loadTasks() {
  tasks.value = await api(`/api/tasks?status=${taskStatus.value}`)
}

async function changeTaskStatus(status) {
  taskStatus.value = status
  await loadTasks()
}

async function loadDuty() {
  if (!showDutyCalendar) return
  const data = await api(`/api/duty/schedule?month=${dutyMonth.value}`)
  dutyDays.value = data.days || []
  dutyRoster.value = data.roster || []
  dutyCalendarDate.value = new Date(`${dutyMonth.value}-01T00:00:00`)
}

async function loadAdminData() {
  if (!canManageUsers.value) return
  const usersData = await api('/api/admin/users')
  users.value = usersData.map((item) => ({ ...item, role_codes: normalizeRoleCodes(item.role_codes) }))
  if (!isAdmin.value) {
    const [rolesData, storesData] = await Promise.all([
      api('/api/admin/roles'),
      api('/api/admin/stores'),
    ])
    roles.value = rolesData
    stores.value = storesData
    newUser.value.city_id = storesData[0]?.city_id ?? null
    newUser.value.store_id = user.value?.store_id ?? storesData[0]?.id ?? null
    if (!rolesData.some((role) => role.code === newUser.value.role_codes[0])) {
      newUser.value.role_codes = [rolesData[0]?.code || 'clerk']
    }
    return
  }
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
  await Promise.all([loadOrders(), loadLeases(), loadTasks(), loadDuty(), loadAdminData(), loadKnowledgeDocuments()])
}

async function loadKnowledgeDocuments() {
  if (!canManageKnowledge.value) return
  knowledgeDocuments.value = await api('/api/qa/knowledge')
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
    sort_by: '',
    sort_order: '',
  }
  orderPage.value = 1
  await loadOrders()
}

async function applyLeaseFilters() {
  leasePage.value = 1
  await loadLeases()
}

async function resetLeaseFilters() {
  leaseFilters.value = { community_name: '', price_min: '', price_max: '', sort_by: 'lease_expire_date', sort_order: 'asc' }
  leasePage.value = 1
  await loadLeases()
}

function dutyWeekdayLabel(value) {
  return ['一', '二', '三', '四', '五', '六', '日'][value] || ''
}

function formatDate(value) {
  const date = value instanceof Date ? value : new Date(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dutyCellDay(data) {
  return dutyDayMap.value[data.day]
}

function isDutyToday(dateText) {
  return dateText === todayText.value
}

async function changeDutyMonth() {
  dutyCalendarDate.value = new Date(`${dutyMonth.value}-01T00:00:00`)
  await loadDuty()
}

async function syncDutyMonthFromCalendar(value) {
  const nextMonth = formatDate(value).slice(0, 7)
  if (nextMonth === dutyMonth.value) return
  dutyMonth.value = nextMonth
  await loadDuty()
}

async function saveDutyRoster() {
  try {
    const user_ids = dutyRoster.value.map((item) => Number(item.id)).filter(Boolean)
    const data = await api('/api/duty/roster', { method: 'PUT', body: JSON.stringify({ user_ids }) })
    dutyRoster.value = data.roster || []
    message.value = '值班排序已保存'
    await loadDuty()
  } catch (error) {
    message.value = error.message
  }
}

function openDutyDay(day) {
  if (!canEditDuty.value || !day.user_id) return
  selectedDutyDay.value = day
  selectedDutyUserId.value = day.user_id
}

function moveDutyRoster(index, delta) {
  const targetIndex = index + delta
  if (targetIndex < 0 || targetIndex >= dutyRoster.value.length) return
  const next = [...dutyRoster.value]
  const [item] = next.splice(index, 1)
  next.splice(targetIndex, 0, item)
  dutyRoster.value = next.map((row, rowIndex) => ({ ...row, sort_order: rowIndex + 1 }))
}

function openDutyDate(dateText) {
  const day = dutyDayMap.value[dateText]
  if (!canEditDuty.value) return
  selectedDutyDay.value = day || { date: dateText, display_name: '', user_id: null }
  selectedDutyUserId.value = day?.user_id || dutyRoster.value[0]?.id || null
}

function closeDutyDialog() {
  selectedDutyDay.value = null
  selectedDutyUserId.value = null
}

async function saveDutyAssignment() {
  try {
    await api('/api/duty/assignment', {
      method: 'PUT',
      body: JSON.stringify({ duty_date: selectedDutyDay.value.date, user_id: Number(selectedDutyUserId.value) }),
    })
    message.value = '当天值班人员已修改'
    closeDutyDialog()
    await loadDuty()
  } catch (error) {
    message.value = error.message
  }
}

async function changeOrderCurrentPage(page) {
  orderPage.value = page
  await loadOrders()
}

async function changeOrderPageSizeElement(pageSize) {
  orderPageSize.value = pageSize
  orderPage.value = 1
  await loadOrders()
}

async function handleOrderSort({ prop, order }) {
  orderFilters.value.sort_by = order ? prop : ''
  orderFilters.value.sort_order = order === 'descending' ? 'desc' : order === 'ascending' ? 'asc' : ''
  orderPage.value = 1
  await loadOrders()
}

async function changeLeaseCurrentPage(page) {
  leasePage.value = page
  await loadLeases()
}

async function changeLeasePageSizeElement(pageSize) {
  leasePageSize.value = pageSize
  leasePage.value = 1
  await loadLeases()
}

async function handleLeaseSort({ prop, order }) {
  leaseFilters.value.sort_by = order ? prop : 'lease_expire_date'
  leaseFilters.value.sort_order = order === 'descending' ? 'desc' : 'asc'
  leasePage.value = 1
  await loadLeases()
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

function newLease() {
  selectedLease.value = { id: null }
  leaseDialogMode.value = 'edit'
  leaseForm.value = { has_key: 0, for_sale: 0 }
}

async function openLease(item, mode = 'detail') {
  const detail = await api(`/api/leases/${item.id}`)
  selectedLease.value = detail
  leaseDialogMode.value = mode
  leaseForm.value = { ...detail }
}

function closeLeaseDialog() {
  selectedLease.value = null
  leaseForm.value = {}
}

async function saveLease() {
  try {
    const payload = { ...leaseForm.value }
    delete payload.id
    const path = selectedLease.value?.id ? `/api/leases/${selectedLease.value.id}` : '/api/leases'
    const method = selectedLease.value?.id ? 'PUT' : 'POST'
    const saved = await api(path, { method, body: JSON.stringify(payload) })
    message.value = selectedLease.value?.id ? '租赁房源已保存' : '租赁房源已添加'
    if (saved.id) {
      closeLeaseDialog()
    } else {
      selectedLease.value = saved
      leaseForm.value = { ...saved }
      leaseDialogMode.value = 'detail'
    }
    await loadLeases()
  } catch (error) {
    message.value = error.message
  }
}

async function deleteLease(item = selectedLease.value) {
  if (!item) return
  if (!window.confirm(`确认删除租赁房源 ${item.community_name || ''} ${item.address || ''}？`)) return
  if (!window.confirm('删除后列表中将不再显示，是否继续？')) return
  try {
    await api(`/api/leases/${item.id}`, { method: 'DELETE' })
    message.value = '租赁房源已删除'
    closeLeaseDialog()
    await loadLeases()
  } catch (error) {
    message.value = error.message
  }
}

function chooseLeaseExcel() {
  leaseExcelInputRef.value?.click()
}

async function uploadLeaseExcel(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  importingLeases.value = true
  message.value = ''
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl('/api/leases/import-excel'), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token.value}` },
      body: form,
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '导入失败')
    message.value = `租赁房源导入完成：共 ${data.total} 行，成功 ${data.success} 行，跳过 ${data.skipped} 行，失败 ${data.failed} 行`
    leasePage.value = 1
    await loadLeases()
  } catch (error) {
    message.value = error.message
  } finally {
    importingLeases.value = false
  }
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

function isLeaseTask(task) {
  return task?.task_type === 'lease_expiry'
}

function isOrderConfirmTask(task) {
  return task?.task_type === 'ocr_order_confirm'
}

function canEditTask(task) {
  return task?.status === 'pending'
}

function leaseTaskPayload(task) {
  if (!task?.payload_json) return {}
  try {
    return JSON.parse(task.payload_json)
  } catch {
    return {}
  }
}

function leaseTaskSummary(task) {
  const payload = leaseTaskPayload(task)
  return [
    payload.community_name || task.community_name,
    payload.address || task.address,
    payload.lease_expire_date || task.lease_expire_date,
    task.assignee_name ? `负责人：${task.assignee_name}` : '',
  ].filter(Boolean).join(' · ')
}

function imageTaskPayload(task) {
  return taskPayload(task)
}

function imageTaskValue(payload, key) {
  const value = payload?.[key]
  return value === null || value === undefined || value === '' ? '未识别' : value
}

function scanResultValue(row, key) {
  const value = row?.parsed?.[key]
  return value === null || value === undefined || value === '' ? '-' : value
}

function imageTaskMissingLabels(task) {
  const reason = String(task?.reason || '')
  const payload = imageTaskPayload(task)
  return imageTaskFields
    .filter(([key, label]) => {
      const missingValue = payload?.[key] === null || payload?.[key] === undefined || payload?.[key] === ''
      const missingReason = (imageTaskMissingReasonMap[key] || [`${label}缺失`]).some((text) => reason.includes(text))
      return missingValue || missingReason
    })
    .map(([, label]) => label)
}

function imageTaskSummary(task) {
  const payload = imageTaskPayload(task)
  if (task?.reason) return task.reason
  return `${imageTaskValue(payload, 'signing_date')}成交的${imageTaskValue(payload, 'residential')}小区，面积${imageTaskValue(payload, 'acreage')}，成交价${imageTaskValue(payload, 'price')}，信息待确认`
}

async function openTaskOrder(task) {
  const orderId = task?.result_ref_id
  closeTaskDialog()
  activePage.value = 'orders'
  await loadOrders()
  if (orderId) await openOrder({ ID: orderId }, 'edit')
}

function taskTypeLabel(task) {
  return isLeaseTask(task) ? '租赁到期' : '成交确认'
}

function taskSourceText(task) {
  if (isLeaseTask(task)) return leaseTaskSummary(task)
  return imageTaskSummary(task)
}

function canDeleteTask(task) {
  if (!task || task.status === 'deleted') return false
  if (isStoreManager.value && task.assignee_store_id === user.value?.store_id) return true
  if (isStoreManager.value && task.task_store_id === user.value?.store_id) return true
  return task.assignee_user_id === user.value?.id
}

async function addLeaseFollowup(task) {
  const content = window.prompt('请输入回访内容')
  if (!content) return
  try {
    await api(`/api/tasks/${task.id}/lease-followups`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    })
    message.value = '回访已添加'
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

async function acknowledgeLeaseTask(task) {
  try {
    await api(`/api/tasks/${task.id}/acknowledge`, { method: 'POST' })
    message.value = '待办已知悉'
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

async function acknowledgeTask(task) {
  try {
    await api(`/api/tasks/${task.id}/acknowledge`, { method: 'POST' })
    message.value = '待办已知悉'
    await loadTasks()
  } catch (error) {
    message.value = error.message
  }
}

async function suppressLeaseTask(task) {
  if (!window.confirm('确认不再提示这套租赁房源的到期提醒？')) return
  try {
    await api(`/api/tasks/${task.id}/suppress`, { method: 'POST' })
    message.value = '已设置不再提示'
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

function openScanDialog() {
  scanDetails.value = []
  clearImageUploadFiles()
  showScanDialog.value = true
}

function closeScanDialog() {
  showScanDialog.value = false
  scanDetails.value = []
  clearImageUploadFiles()
}

function closeScanResultDialog() {
  showScanResultDialog.value = false
  scanResultDetails.value = []
}

function handleImageFileChange(_file, files) {
  imageUploadFileList.value = files.slice(0, MAX_SCAN_IMAGE_FILES)
  if (files.length > MAX_SCAN_IMAGE_FILES) {
    message.value = `最多只能上传 ${MAX_SCAN_IMAGE_FILES} 张图片`
  }
}

function handleImageFileRemove(_file, files) {
  imageUploadFileList.value = files
}

function handleImageFileExceed() {
  message.value = `最多只能上传 ${MAX_SCAN_IMAGE_FILES} 张图片`
}

function clearImageUploadFiles() {
  imageUploadFileList.value = []
  imageUploadRef.value?.clearFiles?.()
}

async function scanImages() {
  if (!scanDate.value || isScanning.value) return
  isScanning.value = true
  scanDetails.value = []
  try {
    const data = await api('/api/images/scan', {
      method: 'POST',
      body: JSON.stringify({ business_date: scanDate.value }),
    })
    scanDetails.value = data.details || []
    message.value = `扫描完成：日期 ${scanDate.value}，已扫描 ${data.scanned} 张，入库 ${data.confirmed} 条，合并 ${data.merged ?? 0} 条，待确认 ${data.pending} 条，跳过 ${data.skipped} 张，失败 ${data.failed} 张`
    await loadAll()
  } catch (error) {
    message.value = error.message
  } finally {
    isScanning.value = false
  }
}

async function uploadImages(scanAfterUpload = false) {
  if (!scanDate.value || isUploadingImages.value) return
  const files = imageUploadFileList.value.map((item) => item.raw).filter(Boolean)
  if (!files.length) {
    message.value = '请选择要上传的成交图片'
    clearImageUploadFiles()
    return
  }
  isUploadingImages.value = true
  scanDetails.value = []
  try {
    const form = new FormData()
    form.append('business_date', scanDate.value)
    form.append('scan_after_upload', scanAfterUpload ? 'true' : 'false')
    files.forEach((file) => form.append('files', file))
    const data = await apiForm('/api/images/upload', form)
    clearImageUploadFiles()
    if (data.scan) {
      const scan = data.scan
      scanDetails.value = scan.details || []
      scanResultDetails.value = scanDetails.value
      message.value = `上传 ${data.uploaded} 张并扫描完成：入库 ${scan.confirmed} 条，合并 ${scan.merged ?? 0} 条，待确认 ${scan.pending} 条，跳过 ${scan.skipped} 张，失败 ${scan.failed} 张`
      showScanDialog.value = false
      showScanResultDialog.value = true
      await loadAll()
    } else {
      scanDetails.value = []
      message.value = `上传完成：${data.uploaded} 张图片已保存到 ${data.business_date} 目录`
    }
  } catch (error) {
    message.value = error.message
  } finally {
    isUploadingImages.value = false
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
    const res = await fetch(apiUrl('/api/orders/import-excel'), {
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
  const text = question.value.trim()
  if (!text || isAsking.value) return
  isAsking.value = true
  answer.value = ''
  qaStatus.value = '正在连接智能问答...'
  knowledgeSources.value = []
  qaDealQuery.value = null
  qaDealResult.value = null
  qaRouter.value = null
  qaMessages.value.push({ role: 'user', content: text })
  const assistantMessage = { role: 'assistant', content: '', status: '正在连接智能问答...', intent: '', sources: [], dealQuery: null, dealResult: null, chart: null, timing: [] }
  qaMessages.value.push(assistantMessage)
  question.value = ''
  await scrollQaToBottom()
  try {
    const res = await fetch(apiUrl('/api/qa/ask-stream'), {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ question: text, session_id: qaConversationId.value, mode: qaMode.value }),
    })
    if (res.status === 401) {
      logout(false)
      throw new Error('登录已失效')
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || data.error || '请求失败')
    }
    await readNdjsonStream(res, (event) => {
      if (event.type === 'status') {
        qaStatus.value = event.content
        assistantMessage.status = event.content
      } else if (event.type === 'timing') {
        assistantMessage.timing = [...(assistantMessage.timing || []), event]
      } else if (event.type === 'router') {
        qaRouter.value = event.content || null
        assistantMessage.intent = event.content?.intent || ''
      } else if (event.type === 'sources') {
        knowledgeSources.value = event.content || []
        assistantMessage.sources = event.content || []
      } else if (event.type === 'deal_query') {
        qaDealQuery.value = event.content || null
        assistantMessage.dealQuery = event.content || null
      } else if (event.type === 'deal_result') {
        qaDealResult.value = event.content || null
        assistantMessage.dealResult = event.content || null
      } else if (event.type === 'delta') {
        qaStatus.value = ''
        assistantMessage.status = ''
        answer.value += event.content || ''
        assistantMessage.content += event.content || ''
      } else if (event.type === 'final') {
        const data = event.result || {}
        qaStatus.value = ''
        assistantMessage.status = ''
        answer.value = formatAnswer(data.answer || answer.value)
        assistantMessage.content = formatAnswer(data.answer || assistantMessage.content)
        assistantMessage.intent = data.intent || assistantMessage.intent
        assistantMessage.sources = data.rag_context || assistantMessage.sources
        assistantMessage.dealQuery = data.deal_query || assistantMessage.dealQuery
        assistantMessage.dealResult = data.deal_result || assistantMessage.dealResult
        assistantMessage.chart = data.chart || assistantMessage.chart
        qaConversationId.value = data.session_id || qaConversationId.value
        knowledgeSources.value = data.rag_context || knowledgeSources.value
        qaDealQuery.value = data.deal_query || qaDealQuery.value
        qaDealResult.value = data.deal_result || qaDealResult.value
        renderQaChart(assistantMessage)
      } else if (event.type === 'error') {
        throw new Error(event.content || '请求失败')
      }
      scrollQaToBottom()
    })
  } catch (error) {
    qaStatus.value = ''
    answer.value = error.message
    assistantMessage.status = ''
    assistantMessage.content = error.message
  } finally {
    isAsking.value = false
  }
}

async function scrollQaToBottom() {
  await nextTick()
  const el = qaScrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function setQaChartRef(el, index) {
  if (el) {
    qaChartEls.set(index, el)
    renderQaChart(qaMessages.value[index])
    return
  }
  const chart = qaChartInstances.get(index)
  if (chart) chart.dispose()
  qaChartInstances.delete(index)
  qaChartEls.delete(index)
}

async function renderQaChart(messageItem) {
  if (!messageItem?.chart) return
  await nextTick()
  const index = qaMessages.value.indexOf(messageItem)
  const el = qaChartEls.get(index)
  if (!el) return
  const chartData = messageItem.chart
  const chart = qaChartInstances.get(index) || echarts.init(el)
  qaChartInstances.set(index, chart)
  const series = Array.isArray(chartData.series) && chartData.series.length
    ? chartData.series
    : [{ name: '数量', type: chartData.type || 'bar', data: chartData.y || [] }]
  chart.setOption({
    color: ['#2563eb', '#16a34a', '#f97316'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 48, right: 22, top: 44, bottom: 58 },
    xAxis: { type: 'category', data: chartData.x || [], axisLabel: { interval: 0, rotate: 24 } },
    yAxis: { type: 'value' },
    series: series.map((item) => ({
      name: item.name,
      type: item.type || chartData.type || 'bar',
      data: item.data || [],
      smooth: item.type === 'line',
      barMaxWidth: 34,
    })),
  })
}

function resizeQaCharts() {
  qaChartInstances.forEach((chart) => chart.resize())
}

function resetQaConversation() {
  qaMessages.value = []
  qaConversationId.value = null
  qaStatus.value = ''
  answer.value = ''
  knowledgeSources.value = []
  qaDealQuery.value = null
  qaDealResult.value = null
  qaRouter.value = null
}

function askQuick(text) {
  question.value = text
  ask()
}

function intentLabel(intent) {
  const labels = {
    deal_query: '成交数据',
    knowledge_query: '知识库',
    mixed_query: '综合查询',
    clarification: '需要补充',
    unsupported: '暂不支持',
  }
  return labels[intent] || '自动判断'
}

function handleKnowledgeFileChange(file, files) {
  knowledgeFileList.value = files.slice(-1)
}

function handleKnowledgeFileRemove() {
  knowledgeFileList.value = []
}

async function uploadKnowledge() {
  if (isUploadingKnowledge.value) return
  isUploadingKnowledge.value = true
  message.value = ''
  try {
    const form = new FormData()
    form.append('title', knowledgeForm.value.title)
    form.append('knowledge_type', knowledgeForm.value.knowledge_type)
    form.append('community_name', knowledgeForm.value.community_name || '')
    form.append('content', knowledgeForm.value.content || '')
    form.append('source_url', knowledgeForm.value.source_url || '')
    const rawFile = knowledgeFileList.value[0]?.raw
    if (rawFile) form.append('file', rawFile)
    const result = await apiForm('/api/qa/knowledge', form)
    message.value = `知识已上传：版本 ${result.version}，分块 ${result.chunks}`
    knowledgeForm.value = { title: '', community_name: '', knowledge_type: '楼盘信息', content: '', source_url: '' }
    knowledgeFileList.value = []
    await loadKnowledgeDocuments()
  } catch (error) {
    message.value = error.message
  } finally {
    isUploadingKnowledge.value = false
  }
}

async function deleteKnowledgeDocument(item) {
  if (!window.confirm(`确认归档知识 ${item.title}？`)) return
  try {
    await api(`/api/qa/knowledge/${item.id}`, { method: 'DELETE' })
    message.value = '知识已归档'
    await loadKnowledgeDocuments()
  } catch (error) {
    message.value = error.message
  }
}

function formatAnswer(value) {
  const text = String(value || '').trim()
  if (!text || text.includes('\n')) return text
  return text.replace(/([。！？；])\s*/g, '$1\n').trim()
}

async function createUser() {
  try {
    await api('/api/admin/users', { method: 'POST', body: JSON.stringify(newUser.value) })
    message.value = '用户已创建'
    newUser.value = {
      username: '',
      display_name: '',
      password: '',
      city_id: isAdmin.value ? null : stores.value[0]?.city_id ?? null,
      store_id: isAdmin.value ? null : user.value?.store_id ?? stores.value[0]?.id ?? null,
      role_codes: [roles.value[0]?.code || 'clerk'],
    }
    await loadAdminData()
  } catch (error) {
    message.value = error.message
  }
}

async function saveUserRoles(item) {
  try {
    const role_codes = normalizeRoleCodes(item.role_codes)
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
    await ElMessageBox.confirm(`确认重置用户 ${item.username} 的密码？`, '重置密码', {
      confirmButtonText: '确认重置',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const data = await api(`/api/admin/users/${item.id}/reset-password`, { method: 'POST' })
    await ElMessageBox.alert(`${item.username} 的新密码：${data.password}`, '重置成功', {
      confirmButtonText: '知道了',
    })
    message.value = '密码已重置'
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    message.value = error.message
  }
}

function openPasswordDialog() {
  passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
  showPasswordDialog.value = true
}

async function changeMyPassword() {
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
    showPasswordDialog.value = false
    await ElMessageBox.alert('密码已修改，请使用新密码重新登录。', '修改成功', {
      confirmButtonText: '重新登录',
    })
    logout(false)
  } catch (error) {
    message.value = error.message
  } finally {
    isChangingPassword.value = false
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
  window.addEventListener('resize', resizeQaCharts)
  if (isLoggedIn.value) {
    try {
      await loadAll()
    } catch (error) {
      message.value = error.message
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeQaCharts)
  qaChartInstances.forEach((chart) => chart.dispose())
  qaChartInstances.clear()
  qaChartEls.clear()
})

watch(dutyCalendarDate, (value) => {
  if (isLoggedIn.value && showDutyCalendar) syncDutyMonthFromCalendar(value)
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
      <el-menu
        class="sidebar-menu"
        :default-active="activePage"
        background-color="#101827"
        text-color="#d6deeb"
        active-text-color="#ffffff"
        @select="activePage = $event"
      >
        <el-menu-item v-for="menu in menus" :key="menu.key" :index="menu.key">
          <span>{{ menu.label }}</span>
        </el-menu-item>
      </el-menu>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <h1>{{ menus.find((item) => item.key === activePage)?.label }}</h1>
          <p>{{ user.display_name }} · {{ user.roles.join(', ') }}</p>
        </div>
        <div class="actions">
          <button v-if="activePage === 'dashboard' && canScanImages" @click="openScanDialog">上传/扫描图片</button>
          <el-button @click="openPasswordDialog">修改密码</el-button>
          <button class="secondary" @click="logout()">退出</button>
        </div>
      </header>

      <p v-if="message" class="notice">{{ message }}</p>

      <section v-if="activePage === 'dashboard'" class="dashboard-stack">
        <div class="cards">
          <article class="metric"><span>成交记录</span><strong>{{ overview.orders ?? orderTotal }}</strong></article>
          <article class="metric"><span>待办</span><strong>{{ overview.pending_tasks ?? tasks.length }}</strong></article>
          <article v-if="isAdmin" class="metric"><span>用户</span><strong>{{ overview.users ?? '-' }}</strong></article>
          <article v-if="isAdmin" class="metric"><span>角色</span><strong>{{ overview.roles ?? '-' }}</strong></article>
        </div>

        <section class="panel">
          <div class="panel-header">
            <h2>每日待办</h2>
            <div class="actions">
              <el-radio-group v-model="taskStatus" size="small" @change="changeTaskStatus">
                <el-radio-button label="pending">待办</el-radio-button>
                <el-radio-button label="done">已办</el-radio-button>
              </el-radio-group>
              <button class="secondary" @click="loadTasks">刷新</button>
            </div>
          </div>
          <el-table :data="tasks" border stripe class="data-table">
            <el-table-column label="类型" width="100">
              <template #default="{ row }">{{ taskTypeLabel(row) }}</template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="180" />
            <el-table-column label="内容" min-width="260">
              <template #default="{ row }">{{ taskSourceText(row) }}</template>
            </el-table-column>
            <el-table-column prop="assignee_name" label="负责人" width="120" />
            <el-table-column prop="handler_name" label="处理人" width="120" />
            <el-table-column prop="create_time" label="创建时间" width="170" />
            <el-table-column prop="finish_time" label="处理时间" width="170" />
            <el-table-column label="操作" width="320" fixed="right">
              <template #default="{ row }">
                <div v-if="row.status === 'pending'" class="row-actions">
                  <el-button v-if="isLeaseTask(row)" size="small" @click="addLeaseFollowup(row)">添加回访</el-button>
                  <el-button v-if="!isLeaseTask(row) && canScanImages" size="small" @click="openTask(row)">修改/确认</el-button>
                  <el-button v-if="!isOrderConfirmTask(row)" size="small" @click="acknowledgeTask(row)">已知悉</el-button>
                  <el-button v-if="isLeaseTask(row) && row.followup_count > 0" size="small" type="danger" @click="suppressLeaseTask(row)">不再提示</el-button>
                  <el-button v-if="canDeleteTask(row)" size="small" type="danger" @click="deleteTask(row)">删除</el-button>
                </div>
                <div v-else class="row-actions">
                  <el-button size="small" @click="openTask(row)">查看</el-button>
                  <el-button v-if="canDeleteTask(row)" size="small" type="danger" @click="deleteTask(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="showDutyCalendar" class="panel">
          <div class="panel-header">
            <h2>值班日历</h2>
          </div>
          <div v-if="canEditDuty" class="duty-roster-editor">
            <div>
              <strong>值班排序</strong>
              <span>按上移/下移调整顺序，系统按顺序每日轮换。</span>
            </div>
            <el-table :data="dutyRoster" size="small" border>
              <el-table-column prop="sort_order" label="顺序" width="72" />
              <el-table-column prop="display_name" label="店员" width="160" />
              <el-table-column label="操作" min-width="170">
                <template #default="{ $index }">
                  <div class="roster-actions">
                    <el-button size="small" :disabled="$index === 0" @click="moveDutyRoster($index, -1)">上移</el-button>
                    <el-button size="small" :disabled="$index === dutyRoster.length - 1" @click="moveDutyRoster($index, 1)">下移</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <button @click="saveDutyRoster">保存排序</button>
          </div>
          <div class="today-duty" v-if="todayDuty">
            今日值班：<strong>{{ todayDuty.display_name || '未排班' }}</strong>
          </div>
          <el-calendar v-model="dutyCalendarDate" class="duty-calendar">
            <template #date-cell="{ data }">
              <div
                class="duty-date-cell"
                :class="{ today: isDutyToday(data.day), override: dutyCellDay(data)?.is_override }"
                @click.stop="openDutyDate(data.day)"
                @keyup.enter="openDutyDate(data.day)"
                tabindex="0"
              >
                <span>{{ Number(data.day.slice(-2)) }}</span>
                <strong>{{ dutyCellDay(data)?.display_name || '未排班' }}</strong>
                <em v-if="dutyCellDay(data)?.is_override">已调整</em>
              </div>
            </template>
          </el-calendar>
        </section>

      </section>

      <section v-if="activePage === 'orders'" class="panel">
        <div class="panel-header">
          <h2>成交数据</h2>
          <div>
            <input ref="excelInputRef" class="hidden-input" type="file" accept=".xlsx" @change="uploadExcel" />
          </div>
        </div>

        <section class="filters">
          <label>开始日期<input v-model="orderFilters.start_date" type="date" /></label>
          <label>结束日期<input v-model="orderFilters.end_date" type="date" /></label>
          <label>楼盘<input v-model="orderFilters.residential" placeholder="小区/楼盘" @keyup.enter="applyOrderFilters" /></label>
          <label>成交人<input v-model="orderFilters.agent" placeholder="成交人" @keyup.enter="applyOrderFilters" /></label>
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

        <el-table :data="orders" border stripe class="data-table" @sort-change="handleOrderSort">
          <el-table-column prop="signing_date" label="日期" width="120" sortable="custom" />
          <el-table-column prop="residential" label="楼盘" min-width="160" />
          <el-table-column prop="acreage" label="面积" width="100" sortable="custom" />
          <el-table-column prop="price" label="成交价" width="120" sortable="custom" />
          <el-table-column prop="agent" label="成交人" width="120" />
          <el-table-column prop="store" label="成交人门店" min-width="150" />
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button size="small" @click="openOrder(row)">详情</el-button>
                <el-button v-if="canEditOrders" size="small" @click="openOrder(row, 'edit')">修改</el-button>
                <el-button v-if="canDeleteOrders" size="small" type="danger" @click="deleteOrder(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="element-pagination"
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="orderTotal"
          :current-page="orderPage"
          :page-size="orderPageSize"
          :page-sizes="[20, 50, 100]"
          @current-change="changeOrderCurrentPage"
          @size-change="changeOrderPageSizeElement"
        />
      </section>

      <section v-if="activePage === 'leases'" class="panel">
        <div class="panel-header">
          <h2>租赁房源</h2>
          <div class="actions">
            <input ref="leaseExcelInputRef" class="hidden-input" type="file" accept=".xlsx" @change="uploadLeaseExcel" />
            <button @click="newLease">添加房源</button>
            <button class="secondary" :disabled="importingLeases" @click="chooseLeaseExcel">
              {{ importingLeases ? '导入中...' : '导入房源数据' }}
            </button>
          </div>
        </div>

        <section class="filters">
          <label>小区<input v-model="leaseFilters.community_name" placeholder="小区名称" @keyup.enter="applyLeaseFilters" /></label>
          <label>价格下限<input v-model="leaseFilters.price_min" type="number" min="0" placeholder="元/月" /></label>
          <label>价格上限<input v-model="leaseFilters.price_max" type="number" min="0" placeholder="元/月" /></label>
          <div class="filter-actions">
            <button @click="applyLeaseFilters">筛选</button>
            <button class="secondary" @click="resetLeaseFilters">重置</button>
          </div>
        </section>

        <el-table :data="leases" border stripe class="data-table" @sort-change="handleLeaseSort">
          <el-table-column prop="community_name" label="小区" min-width="150" />
          <el-table-column prop="address" label="地址" min-width="180" />
          <el-table-column prop="acreage" label="面积" width="100" />
          <el-table-column prop="price" label="价格" width="110" sortable="custom" />
          <el-table-column prop="rental_type" label="出租方式" width="120" />
          <el-table-column prop="agent" label="成交人" width="120" />
          <el-table-column prop="lease_expire_date" label="租期到期" width="130" sortable="custom" />
          <el-table-column label="钥匙" width="80">
            <template #default="{ row }">{{ row.has_key ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button size="small" @click="openLease(row)">详情</el-button>
                <el-button size="small" @click="openLease(row, 'edit')">修改</el-button>
                <el-button size="small" type="danger" @click="deleteLease(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="element-pagination"
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="leaseTotal"
          :current-page="leasePage"
          :page-size="leasePageSize"
          :page-sizes="[20, 50, 100]"
          @current-change="changeLeaseCurrentPage"
          @size-change="changeLeasePageSizeElement"
        />
      </section>

      <section v-if="activePage === 'qa'" class="qa-workspace">
        <div class="qa-topbar">
          <div>
            <h2>智能问答</h2>
            <span>{{ user?.city || '当前城市' }} · {{ qaConversationId ? `会话 ${qaConversationId}` : '新会话' }}</span>
          </div>
          <el-button size="small" @click="resetQaConversation">新建对话</el-button>
        </div>

        <div ref="qaScrollRef" class="qa-messages">
          <div v-if="!qaMessages.length" class="qa-empty">
            <el-button size="small" @click="askQuick('本月哪个小区成交最多？')">本月成交排行</el-button>
            <el-button size="small" @click="askQuick('公元世家三期最近成交情况')">小区成交情况</el-button>
            <el-button size="small" @click="askQuick('宁波购房政策有哪些？')">政策资料查询</el-button>
          </div>
          <div
            v-for="(item, index) in qaMessages"
            :key="index"
            class="qa-message"
            :class="item.role === 'user' ? 'qa-message-user' : 'qa-message-assistant'"
          >
            <div class="qa-bubble">
              <div v-if="item.role === 'assistant'" class="qa-bubble-meta">
                <el-tag size="small" effect="plain">{{ intentLabel(item.intent) }}</el-tag>
                <span v-if="item.status">{{ item.status }}</span>
              </div>
              <p class="qa-content">{{ item.content || (item.status ? '' : '正在生成回答...') }}</p>
              <div
                v-if="item.role === 'assistant' && item.chart"
                :ref="(el) => setQaChartRef(el, index)"
                class="qa-chart"
              />

              <el-collapse v-if="item.dealQuery || item.dealResult?.rows?.length || item.sources?.length || item.timing?.length" class="qa-evidence">
                <el-collapse-item v-if="item.dealQuery" title="成交查询条件" name="deal-query">
                  <pre>{{ JSON.stringify(item.dealQuery, null, 2) }}</pre>
                </el-collapse-item>
                <el-collapse-item v-if="item.dealResult?.rows?.length" title="成交查询结果" name="deal-result">
                  <el-table :data="item.dealResult.rows" size="small" max-height="260" border>
                    <el-table-column prop="signing_date" label="日期" width="110" />
                    <el-table-column prop="residential" label="楼盘" min-width="140" show-overflow-tooltip />
                    <el-table-column prop="name" label="分组" min-width="120" show-overflow-tooltip />
                    <el-table-column prop="count" label="套数" width="80" />
                    <el-table-column prop="price" label="成交价" width="110" />
                    <el-table-column prop="total_price" label="总额" width="120" />
                    <el-table-column prop="avg_unit_price" label="均价" width="110" />
                    <el-table-column prop="agent" label="经纪人" width="100" />
                    <el-table-column prop="store" label="门店" min-width="120" show-overflow-tooltip />
                  </el-table>
                </el-collapse-item>
                <el-collapse-item v-if="item.sources?.length" title="知识库来源" name="sources">
                  <div class="source-list">
                    <div v-for="source in item.sources" :key="`${source.chunk_id}-${source.title}`" class="source-item">
                      <strong>{{ source.title }}</strong>
                      <span>{{ source.knowledge_type }} · v{{ source.version }} · 相关度 {{ Number(source.score || 0).toFixed(2) }}</span>
                      <p>{{ source.summary || source.content }}</p>
                    </div>
                  </div>
                </el-collapse-item>
                <el-collapse-item v-if="item.timing?.length" title="执行耗时" name="timing">
                  <el-table :data="item.timing" size="small" border>
                    <el-table-column prop="step" label="步骤" />
                    <el-table-column prop="elapsed_ms" label="本步耗时(ms)" width="130" />
                    <el-table-column prop="total_ms" label="累计耗时(ms)" width="130" />
                  </el-table>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </div>

        <div class="qa-composer">
          <el-segmented
            v-model="qaMode"
            :options="[
              { label: '自动', value: 'auto' },
              { label: '成交数据', value: 'deal' },
              { label: '知识库', value: 'knowledge' },
            ]"
            size="small"
          />
          <div class="qa-input-row">
            <el-input
              v-model="question"
              type="textarea"
              :rows="3"
              resize="none"
              :disabled="isAsking"
              placeholder="请输入成交数据、小区情况或政策相关问题"
              @keydown.enter.exact.prevent="ask"
            />
            <el-button type="primary" :loading="isAsking" @click="ask">发送</el-button>
          </div>
        </div>
      </section>

      <section v-if="activePage === 'knowledge'" class="panel knowledge-page">
        <div class="panel-header">
          <h2>知识库管理</h2>
          <el-button size="small" @click="loadKnowledgeDocuments">刷新</el-button>
        </div>
        <el-form class="knowledge-upload" label-position="top">
          <el-form-item label="标题">
            <el-input v-model="knowledgeForm.title" placeholder="例如：公元世家三期楼盘资料" />
          </el-form-item>
          <el-form-item label="楼盘/小区">
            <el-input v-model="knowledgeForm.community_name" placeholder="可选，用于同楼盘新版覆盖旧版" />
          </el-form-item>
          <el-form-item label="知识类型">
            <el-select v-model="knowledgeForm.knowledge_type">
              <el-option label="楼盘信息" value="楼盘信息" />
              <el-option label="政策制度" value="政策制度" />
              <el-option label="交易规则" value="交易规则" />
              <el-option label="学区信息" value="学区信息" />
              <el-option label="其他" value="其他" />
            </el-select>
          </el-form-item>
          <el-form-item label="文字内容">
            <el-input v-model="knowledgeForm.content" type="textarea" :rows="5" placeholder="可直接粘贴文字，也可以配合上传文件" />
          </el-form-item>
          <el-form-item label="网页链接">
            <el-input v-model="knowledgeForm.source_url" placeholder="https://..." clearable />
          </el-form-item>
          <el-form-item label="文件">
            <el-upload
              v-model:file-list="knowledgeFileList"
              :auto-upload="false"
              :limit="1"
              accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.bmp,.webp"
              :on-change="handleKnowledgeFileChange"
              :on-remove="handleKnowledgeFileRemove"
            >
              <el-button>选择文件</el-button>
            </el-upload>
          </el-form-item>
          <el-button type="primary" :loading="isUploadingKnowledge" @click="uploadKnowledge">上传并索引</el-button>
        </el-form>
        <el-table :data="knowledgeDocuments" size="small" border stripe class="knowledge-table">
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column prop="knowledge_type" label="类型" width="100" />
          <el-table-column prop="community_name" label="小区" min-width="120" show-overflow-tooltip />
          <el-table-column prop="source_type" label="来源类型" width="90" />
          <el-table-column prop="creator" label="创建人" width="110" show-overflow-tooltip />
          <el-table-column prop="create_time" label="上传时间" width="170" />
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button v-if="isAdmin && row.status === 'active'" size="small" type="danger" @click="deleteKnowledgeDocument(row)">归档</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="activePage === 'tasks'" class="panel">
        <div class="panel-header">
          <h2>每日待办</h2>
          <div class="actions">
            <el-radio-group v-model="taskStatus" size="small" @change="changeTaskStatus">
              <el-radio-button label="pending">待办</el-radio-button>
              <el-radio-button label="done">已办</el-radio-button>
            </el-radio-group>
            <button class="secondary" @click="loadTasks">刷新</button>
          </div>
        </div>
        <el-table :data="tasks" border stripe class="data-table">
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ taskTypeLabel(row) }}</template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="180" />
          <el-table-column label="内容" min-width="260">
            <template #default="{ row }">{{ taskSourceText(row) }}</template>
          </el-table-column>
          <el-table-column prop="assignee_name" label="负责人" width="120" />
          <el-table-column prop="handler_name" label="处理人" width="120" />
          <el-table-column prop="create_time" label="创建时间" width="170" />
          <el-table-column prop="finish_time" label="处理时间" width="170" />
          <el-table-column label="操作" width="320" fixed="right">
            <template #default="{ row }">
              <div v-if="row.status === 'pending'" class="row-actions">
                <el-button v-if="isLeaseTask(row)" size="small" @click="addLeaseFollowup(row)">添加回访</el-button>
                <el-button v-if="!isLeaseTask(row) && canScanImages" size="small" @click="openTask(row)">修改/确认</el-button>
                <el-button v-if="!isOrderConfirmTask(row)" size="small" @click="acknowledgeTask(row)">已知悉</el-button>
                <el-button v-if="isLeaseTask(row) && row.followup_count > 0" size="small" type="danger" @click="suppressLeaseTask(row)">不再提示</el-button>
                <el-button v-if="canDeleteTask(row)" size="small" type="danger" @click="deleteTask(row)">删除</el-button>
              </div>
              <div v-else class="row-actions">
                <el-button size="small" @click="openTask(row)">查看</el-button>
                <el-button v-if="canDeleteTask(row)" size="small" type="danger" @click="deleteTask(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="activePage === 'admin'" class="admin-grid">
        <div v-if="canManageUsers" class="panel">
          <h2>创建用户</h2>
          <div class="form-grid">
            <input v-model="newUser.username" placeholder="登录账号" />
            <input v-model="newUser.display_name" placeholder="姓名" />
            <input v-model="newUser.password" type="password" placeholder="初始密码" />
            <select v-if="isAdmin" v-model="newUser.city_id">
              <option :value="null">默认城市</option>
              <option v-for="city in cities" :key="city.id" :value="city.id">{{ city.name }}</option>
            </select>
            <select v-if="isAdmin" v-model="newUser.store_id">
              <option :value="null">不指定门店</option>
              <option v-for="store in stores" :key="store.id" :value="store.id">{{ store.name }}</option>
            </select>
            <select v-else v-model="newUser.store_id" disabled>
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
                <td>
                  <el-select
                    v-if="canManageUsers"
                    v-model="item.role_codes"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="选择角色"
                  >
                    <el-option v-for="role in roles" :key="role.code" :label="role.name" :value="role.code" />
                  </el-select>
                  <span v-else>{{ normalizeRoleCodes(item.role_codes).join(', ') }}</span>
                </td>
                <td class="row-actions">
                  <button v-if="canManageUsers" class="small secondary" @click="saveUserRoles(item)">保存</button>
                  <button class="small secondary" @click="resetUserPassword(item)">重置密码</button>
                  <button v-if="canManageUsers" class="small danger" @click="deleteUser(item)">删除</button>
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

    <el-dialog v-model="showScanDialog" title="上传/扫描成交图片" width="560px" @closed="closeScanDialog">
      <el-form label-position="top">
        <el-form-item label="图片日期">
          <el-input
            :model-value="scanDate"
            readonly
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="成交图片">
          <el-upload
            ref="imageUploadRef"
            drag
            multiple
            accept=".jpg,.jpeg,.png,.bmp,.webp"
            :auto-upload="false"
            :limit="MAX_SCAN_IMAGE_FILES"
            v-model:file-list="imageUploadFileList"
            :on-change="handleImageFileChange"
            :on-exceed="handleImageFileExceed"
            :on-remove="handleImageFileRemove"
          >
            <div class="upload-drop-text">拖拽图片到这里，或点击选择图片</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <el-table v-if="scanDetails.length" :data="scanDetails" border stripe size="small" class="scan-detail-table">
        <el-table-column prop="file_name" label="图片" min-width="160" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'confirmed' ? 'success' : row.status === 'pending' ? 'warning' : row.status === 'failed' ? 'danger' : 'info'"
              effect="plain"
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="处理结果" min-width="180" />
        <el-table-column label="成交ID" width="90">
          <template #default="{ row }">{{ row.order_id || '-' }}</template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button :disabled="isScanning || isUploadingImages" @click="closeScanDialog">取消</el-button>
        <el-button :loading="isUploadingImages" :disabled="!scanDate || !hasSelectedImageFiles" @click="uploadImages(false)">仅上传</el-button>
        <el-button :loading="isScanning" :disabled="!scanDate || isUploadingImages" @click="scanImages">扫描已有图片</el-button>
        <el-button
          type="primary"
          :loading="isUploadingImages"
          :disabled="!scanDate || !hasSelectedImageFiles || isScanning"
          @click="uploadImages(true)"
        >
          上传并扫描
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showScanResultDialog" title="扫描结果" width="1100px" @closed="closeScanResultDialog">
      <section class="scan-result-section">
        <h3>新增成交记录</h3>
        <el-table v-if="newScanOrderResults.length" :data="newScanOrderResults" border stripe size="small">
          <el-table-column prop="file_name" label="图片名称" min-width="180" />
          <el-table-column label="小区名" min-width="150">
            <template #default="{ row }">{{ scanResultValue(row, 'residential') }}</template>
          </el-table-column>
          <el-table-column label="成交日期" width="120">
            <template #default="{ row }">{{ scanResultValue(row, 'signing_date') }}</template>
          </el-table-column>
          <el-table-column label="成交人" width="110">
            <template #default="{ row }">{{ scanResultValue(row, 'agent') }}</template>
          </el-table-column>
          <el-table-column label="维护人" width="110">
            <template #default="{ row }">{{ scanResultValue(row, 'maintainor') }}</template>
          </el-table-column>
          <el-table-column label="成交面积" width="110">
            <template #default="{ row }">{{ scanResultValue(row, 'acreage') }}</template>
          </el-table-column>
          <el-table-column label="成交价" width="120">
            <template #default="{ row }">{{ scanResultValue(row, 'price') }}</template>
          </el-table-column>
          <el-table-column label="成交ID" width="100">
            <template #default="{ row }">{{ row.order_id || '-' }}</template>
          </el-table-column>
          <el-table-column prop="message" label="处理结果" min-width="220" />
        </el-table>
        <el-empty v-else description="暂无新增成交记录" />
      </section>

      <section class="scan-result-section">
        <h3>需人工审核</h3>
        <el-table v-if="reviewScanResults.length" :data="reviewScanResults" border stripe size="small">
          <el-table-column prop="file_name" label="图片名称" min-width="180" />
          <el-table-column label="小区名" min-width="150">
            <template #default="{ row }">{{ scanResultValue(row, 'residential') }}</template>
          </el-table-column>
          <el-table-column label="成交日期" width="120">
            <template #default="{ row }">{{ scanResultValue(row, 'signing_date') }}</template>
          </el-table-column>
          <el-table-column label="成交人" width="110">
            <template #default="{ row }">{{ scanResultValue(row, 'agent') }}</template>
          </el-table-column>
          <el-table-column label="维护人" width="110">
            <template #default="{ row }">{{ scanResultValue(row, 'maintainor') }}</template>
          </el-table-column>
          <el-table-column label="成交面积" width="110">
            <template #default="{ row }">{{ scanResultValue(row, 'acreage') }}</template>
          </el-table-column>
          <el-table-column label="成交价" width="120">
            <template #default="{ row }">{{ scanResultValue(row, 'price') }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'failed' ? 'danger' : 'warning'" effect="plain">
                {{ row.status === 'failed' ? '识别失败' : '待审核' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="问题说明" min-width="260" />
          <el-table-column label="成交ID" width="100">
            <template #default="{ row }">{{ row.order_id || '-' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无需人工审核图片" />
      </section>

      <template #footer>
        <el-button type="primary" @click="closeScanResultDialog">知道了</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showPasswordDialog" title="修改密码" width="420px">
      <el-form label-position="top">
        <el-form-item label="原密码">
          <el-input v-model="passwordForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="passwordForm.confirm_password" type="password" show-password @keyup.enter="changeMyPassword" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPasswordDialog = false">取消</el-button>
        <el-button type="primary" :loading="isChangingPassword" @click="changeMyPassword">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="Boolean(selectedDutyDay)"
      title="修改值班人员"
      width="420px"
      @close="closeDutyDialog"
    >
      <div v-if="selectedDutyDay" class="form-grid single">
        <label>
          日期
          <span class="readonly">{{ selectedDutyDay.date }}</span>
        </label>
        <label>
          值班人员
          <el-select v-model="selectedDutyUserId" placeholder="请选择值班人员">
            <el-option v-for="item in dutyRoster" :key="item.id" :label="item.display_name" :value="item.id" />
          </el-select>
        </label>
      </div>
      <template #footer>
        <el-button @click="closeDutyDialog">取消</el-button>
        <el-button type="primary" @click="saveDutyAssignment">保存</el-button>
      </template>
    </el-dialog>

    <div v-if="selectedLease" class="dialog-backdrop" @click.self="closeLeaseDialog">
      <section class="dialog">
        <div class="panel-header">
          <h2>{{ leaseDialogMode === 'edit' ? (selectedLease.id ? '修改租赁房源' : '添加租赁房源') : '租赁房源详情' }}</h2>
          <button class="secondary" @click="closeLeaseDialog">关闭</button>
        </div>
        <div class="form-grid">
          <label v-for="[key, label, type] in leaseFields" :key="key">
            {{ label }}
            <input v-if="leaseDialogMode === 'edit'" v-model="leaseForm[key]" :type="type" />
            <span v-else class="readonly">{{ selectedLease[key] || '-' }}</span>
          </label>
          <label>
            是否有钥匙
            <select v-if="leaseDialogMode === 'edit'" v-model.number="leaseForm.has_key">
              <option :value="0">否</option>
              <option :value="1">是</option>
            </select>
            <span v-else class="readonly">{{ selectedLease.has_key ? '是' : '否' }}</span>
          </label>
          <label>
            是否出售
            <select v-if="leaseDialogMode === 'edit'" v-model.number="leaseForm.for_sale">
              <option :value="0">否</option>
              <option :value="1">是</option>
            </select>
            <span v-else class="readonly">{{ selectedLease.for_sale ? '是' : '否' }}</span>
          </label>
        </div>
        <div class="actions">
          <button v-if="leaseDialogMode === 'detail'" @click="leaseDialogMode = 'edit'">修改</button>
          <button v-if="leaseDialogMode === 'edit'" @click="saveLease">保存</button>
          <button v-if="selectedLease.id" class="danger" @click="deleteLease()">删除</button>
        </div>
      </section>
    </div>

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
          <button v-if="canDeleteOrders" class="danger" @click="deleteOrder(selectedOrder)">删除</button>
        </div>
      </section>
    </div>

    <div v-if="selectedTask" class="dialog-backdrop" @click.self="closeTaskDialog">
      <section class="dialog">
        <div class="panel-header">
          <h2>{{ canEditTask(selectedTask) ? '处理待办' : '查看待办' }}</h2>
          <button class="secondary" @click="closeTaskDialog">关闭</button>
        </div>
        <div class="task-source">
          <strong>{{ selectedTask.file_name || selectedTask.title }}</strong>
          <span>{{ selectedTask.city }} · {{ selectedTask.business_date || '-' }}</span>
          <p>{{ isLeaseTask(selectedTask) ? selectedTask.reason : imageTaskSummary(selectedTask) }}</p>
          <pre v-if="isLeaseTask(selectedTask) && selectedTask.ocr_text">{{ selectedTask.ocr_text }}</pre>
        </div>
        <div v-if="isLeaseTask(selectedTask)" class="task-source">
          <p>{{ leaseTaskSummary(selectedTask) }}</p>
        </div>
        <div v-else class="form-grid">
          <label v-for="[key, label] in imageTaskFields" :key="key">
            {{ label }}
            <span class="readonly" :class="{ missing: imageTaskMissingLabels(selectedTask).includes(label) }">
              {{ imageTaskValue(taskForm, key) }}
            </span>
          </label>
        </div>
        <div v-if="!isLeaseTask(selectedTask) && imageTaskMissingLabels(selectedTask).length" class="missing-hint">
          缺失：{{ imageTaskMissingLabels(selectedTask).join('、') }}
        </div>
        <div v-if="canEditTask(selectedTask) && isLeaseTask(selectedTask)" class="actions">
          <button class="secondary" @click="saveTaskDraft">保存修改</button>
          <button @click="completeTask">确认入库</button>
          <button v-if="canDeleteTask(selectedTask)" class="danger" @click="deleteTask()">删除待办</button>
        </div>
        <div v-else-if="canEditTask(selectedTask)" class="actions">
          <button @click="openTaskOrder(selectedTask)">去成交列表修改</button>
          <button v-if="canDeleteTask(selectedTask)" class="danger" @click="deleteTask()">删除待办</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.qa-workspace {
  display: grid;
  grid-template-rows: auto 1fr auto;
  height: calc(100vh - 112px);
  min-height: 620px;
  background: #f7f8fb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.qa-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
}

.qa-topbar h2 {
  margin: 0 0 4px;
  font-size: 20px;
}

.qa-topbar span {
  color: #6b7280;
  font-size: 13px;
}

.qa-messages {
  overflow-y: auto;
  padding: 20px;
}

.qa-empty {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  min-height: 240px;
}

.qa-message {
  display: flex;
  margin-bottom: 16px;
}

.qa-message-user {
  justify-content: flex-end;
}

.qa-message-assistant {
  justify-content: flex-start;
}

.qa-bubble {
  max-width: min(860px, 84%);
  padding: 14px 16px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.qa-message-user .qa-bubble {
  color: #ffffff;
  background: #2563eb;
  border-color: #2563eb;
}

.qa-bubble-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: #6b7280;
  font-size: 13px;
}

.qa-content {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.qa-chart {
  width: min(760px, 100%);
  height: 320px;
  margin-top: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
}

.qa-evidence {
  margin-top: 12px;
}

.qa-evidence pre {
  max-height: 260px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  color: #374151;
  background: #f3f4f6;
  border-radius: 6px;
}

.source-list {
  display: grid;
  gap: 10px;
}

.source-item {
  padding: 10px;
  background: #f9fafb;
  border: 1px solid #edf0f3;
  border-radius: 6px;
}

.source-item strong,
.source-item span {
  display: block;
}

.source-item span {
  margin-top: 2px;
  color: #6b7280;
  font-size: 12px;
}

.source-item p {
  margin: 8px 0 0;
  color: #374151;
  line-height: 1.6;
}

.qa-composer {
  padding: 14px 18px 18px;
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
}

.qa-input-row {
  display: grid;
  grid-template-columns: 1fr 88px;
  gap: 10px;
  align-items: stretch;
  margin-top: 10px;
}

.qa-input-row .el-button {
  height: 100%;
}

.knowledge-page {
  display: grid;
  gap: 16px;
}

.knowledge-upload {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.knowledge-upload .el-form-item:nth-child(4),
.knowledge-upload .el-form-item:nth-child(5),
.knowledge-upload .el-form-item:nth-child(6) {
  grid-column: 1 / -1;
}

.knowledge-table {
  width: 100%;
}

@media (max-width: 760px) {
  .qa-workspace {
    height: calc(100vh - 80px);
    min-height: 520px;
  }

  .qa-bubble {
    max-width: 94%;
  }

  .qa-chart {
    height: 260px;
  }

  .qa-input-row,
  .knowledge-upload {
    grid-template-columns: 1fr;
  }
}
</style>
