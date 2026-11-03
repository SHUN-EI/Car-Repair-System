<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">维修报表</h2>
      <div>
        <el-button @click="openIntake">接车开单</el-button>
        <el-button type="primary" @click="$router.push('/work-orders/new')">新建工单</el-button>
      </div>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索工单编号/故障描述" clearable class="filter-input" @clear="handleSearch" @keyup.enter="handleSearch" />
        <el-select v-model="statusFilter" placeholder="工单状态" clearable class="filter-select" @change="handleSearch">
          <el-option label="草稿" value="DRAFT" />
          <el-option label="接车" value="INTAKE" />
          <el-option label="诊断中" value="DIAGNOSING" />
          <el-option label="报价中" value="QUOTING" />
          <el-option label="报价已确认" value="APPROVED" />
          <el-option label="维修中" value="IN_PROGRESS" />
          <el-option label="质检" value="QC" />
          <el-option label="已完成" value="COMPLETED" />
          <el-option label="已结案" value="CLOSED" />
          <el-option label="已取消" value="CANCELLED" />
          <el-option label="待归档" value="ARCHIVING" />
          <el-option label="已归档" value="ARCHIVED" />
        </el-select>
        <el-select v-model="deviceTypeFilter" placeholder="设备类型" clearable class="filter-select" @change="handleSearch">
          <el-option v-for="d in deviceTypeOptions" :key="d.value" :label="d.label" :value="d.value" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="filter-date"
          @change="handleSearch"
          clearable
        />
        <el-button type="primary" @click="handleSearch" class="action-btn">查询</el-button>
        <el-button class="action-btn secondary-btn" @click="handleReset">重置</el-button>
      </div>
    </el-card>

    <el-card class="table-card" shadow="never">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column prop="work_order_no" label="工单编号" width="170" />
        <el-table-column prop="fault_description" label="故障描述" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.allowed_transitions && row.allowed_transitions.length"
              :content="'可流转：' + transitionText(row)"
              placement="top"
            >
              <span class="status-tag" :class="'status-' + row.status">{{ statusLabel(row.status) }}</span>
            </el-tooltip>
            <span v-else class="status-tag" :class="'status-' + row.status">{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="车牌" width="110">
          <template #default="{ row }">{{ row.vehicle_plate || '-' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="480" fixed="right">
          <template #default="{ row }">
            <div class="col-actions">
              <div class="action-row">
                <el-button size="small" type="primary" @click="$router.push(`/work-orders/${row.id}`)">查看</el-button>
                <el-button v-if="!isSupervisor" size="small" type="warning" :disabled="['COMPLETED', 'ARCHIVED'].includes(row.status) || (!isCreatedByMe(row) && !isAdmin && !isAssignedTech(row))" @click="$router.push(`/work-orders/${row.id}?edit=1`)">编辑</el-button>
                <el-button v-if="!isSupervisor" size="small" type="danger" :disabled="['COMPLETED', 'ARCHIVED'].includes(row.status) || (!isCreatedByMe(row) && !isAdmin)" @click="handleDelete(row)">删除</el-button>
              </div>
              <div class="action-row progress-row" v-if="canOperateProgress(row)">
                <el-button
                  v-if="row.status === 'ASSIGNED'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_ACCEPTED`]"
                  @click="handleTransition(row, 'ACCEPTED')"
                >接受任务</el-button>
                <el-button
                  v-if="row.status === 'ACCEPTED'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_ARRIVED`]"
                  @click="handleTransition(row, 'ARRIVED')"
                >已到达现场</el-button>
                <el-button
                  v-if="row.status === 'ARRIVED'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_INSPECTING`]"
                  @click="handleTransition(row, 'INSPECTING')"
                >开始检查</el-button>
                <el-button
                  v-if="row.status === 'INSPECTING'"
                  size="small"
                  type="primary"
                  :disabled="!isAssignedTech(row) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_IN_PROGRESS`]"
                  @click="handleTransition(row, 'IN_PROGRESS')"
                >开始维修</el-button>
                <el-button
                  v-if="row.status === 'IN_PROGRESS' && !isAutoLane(row)"
                  size="small"
                  type="success"
                  :loading="transitionLoading[`${row.id}_ARCHIVING`]"
                  @click="handleFinishRepair(row)"
                >完成维修</el-button>
                <el-button
                  v-if="row.status === 'ARCHIVING'"
                  size="small"
                  type="primary"
                  @click="$router.push(`/work-orders/${row.id}?edit=1`)"
                >去归档</el-button>
              </div>
              <div class="action-row progress-row" v-if="isAutoLane(row) && (autoNext(row) || canCancel(row))">
                <el-button
                  v-if="autoNext(row)"
                  size="small"
                  type="primary"
                  :disabled="needsSupervisor(autoNext(row)) && !isSupervisor"
                  :loading="transitionLoading[`${row.id}_${autoNext(row)}`]"
                  @click="handleTransition(row, autoNext(row), 'WEB')"
                >{{ actionLabel(autoNext(row)) }}</el-button>
                <el-button
                  v-if="canCancel(row)"
                  size="small"
                  :loading="transitionLoading[`${row.id}_CANCELLED`]"
                  @click="handleTransition(row, 'CANCELLED', 'WEB')"
                >取消</el-button>
                <el-button
                  v-if="isSupervisor && !['CLOSED', 'CANCELLED', 'COMPLETED'].includes(row.status)"
                  size="small"
                  @click="openBind(row)"
                >派工</el-button>
                <el-button
                  v-if="canIssue(row)"
                  size="small"
                  @click="openIssue(row)"
                >领料</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchData"
        />
      </div>
    </el-card>

    <el-dialog v-model="intakeVisible" title="接车开单" width="520px">
      <el-form label-width="88px">
        <el-form-item label="预约">
          <el-select v-model="intakeForm.appointment_id" clearable placeholder="可选，选中后按预约接车" style="width: 100%" @change="onAppointmentPick">
            <el-option v-for="item in appointmentOptions" :key="item.id" :label="appointmentLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="门店">
          <el-select v-model="intakeForm.store_id" clearable placeholder="门店" style="width: 100%" @change="loadBays">
            <el-option v-for="item in storeOptions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="工位">
          <el-select v-model="intakeForm.bay_id" clearable placeholder="工位" style="width: 100%">
            <el-option v-for="item in bayOptions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆">
          <el-select v-model="intakeForm.vehicle_id" filterable clearable placeholder="车牌" style="width: 100%">
            <el-option v-for="item in vehicleOptions" :key="item.id" :label="vehicleLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="症状">
          <el-input v-model="intakeForm.fault_description" type="textarea" :rows="3" placeholder="车主描述或到店现象" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="intakeVisible = false">取消</el-button>
        <el-button type="primary" :loading="intakeSaving" @click="submitIntake">开单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bindVisible" title="绑定技师和工位" width="420px">
      <el-form label-width="72px">
        <el-form-item label="技师">
          <el-select v-model="bindForm.technician_id" filterable placeholder="选择技师" style="width: 100%">
            <el-option v-for="item in technicians" :key="item.id" :label="item.real_name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="工位">
          <el-select v-model="bindForm.bay_id" clearable placeholder="工位" style="width: 100%">
            <el-option v-for="item in bindBays" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindVisible = false">取消</el-button>
        <el-button type="primary" :loading="bindSaving" @click="submitBind">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="issueVisible" title="领料出库" width="420px">
      <el-form label-width="72px">
        <el-form-item label="备件">
          <el-select v-model="issueForm.part_code" filterable placeholder="选择备件" style="width: 100%">
            <el-option v-for="item in partOptions" :key="item.part_code" :label="`${item.part_code} ${item.part_name}（库存 ${item.stock_quantity}）`" :value="item.part_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="issueForm.qty" :min="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="issueVisible = false">取消</el-button>
        <el-button type="primary" :loading="issueSaving" @click="submitIssue">出库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'
import { workOrderTransition } from '../api/supervisor'
import dayjs from 'dayjs'

const router = useRouter()

const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push({ label: node.name, value: node.name })
    if (node.children && node.children.length > 0) flattenTree(node.children, result)
  }
  return result
}
const deviceTypeOptions = ref([])

// 当前登录用户（用于权限判断：仅创建者或管理员可编辑）
const currentUser = (() => {
  try {
    const raw = localStorage.getItem('current_user')
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
})()
const isAdmin = currentUser.role === 'ADMIN'
const isSupervisor = currentUser.role === 'SUPERVISOR' || isAdmin
const isCreatedByMe = (row) => {
  if (row.created_by_employee_id && currentUser.employee_id) {
    return row.created_by_employee_id === currentUser.employee_id
  }
  return !!row.created_by && row.created_by === currentUser.id
}
const isAssignedTech = (row) => {
  const tid = row.technician_id || row.assigned_technician_id
  if (!tid) return false
  return tid === currentUser.id
}
const canOperateProgress = (row) => isAssignedTech(row)
const transitionLoading = ref({})

const AUTO_ONLY = ['INTAKE', 'DIAGNOSING', 'QUOTING', 'QC']
const AUTO_NEXT = {
  DRAFT: 'INTAKE',
  INTAKE: 'DIAGNOSING',
  DIAGNOSING: 'QUOTING',
  QUOTING: 'APPROVED',
  APPROVED: 'IN_PROGRESS',
  IN_PROGRESS: 'QC',
  QC: 'COMPLETED',
  COMPLETED: 'CLOSED',
}
const ACTION_LABEL = {
  INTAKE: '接车',
  DIAGNOSING: '开始诊断',
  QUOTING: '出具报价',
  APPROVED: '确认报价',
  IN_PROGRESS: '开始施工',
  QC: '提交质检',
  COMPLETED: '质检通过',
  CLOSED: '结案交车',
}
const isAutoLane = (row) => !!(row.vehicle_id || row.appointment_id || row.store_id || AUTO_ONLY.includes(row.status))
const autoNext = (row) => {
  const next = AUTO_NEXT[row.status]
  if (!next) return ''
  return (row.allowed_transitions || []).includes(next) ? next : ''
}
const actionLabel = (status) => ACTION_LABEL[status] || statusLabel(status)
const needsSupervisor = (status) => status === 'APPROVED' || status === 'CLOSED'
const canCancel = (row) => (row.allowed_transitions || []).includes('CANCELLED')
const canIssue = (row) => ['INTAKE', 'DIAGNOSING', 'QUOTING', 'APPROVED', 'IN_PROGRESS', 'QC'].includes(row.status)

const intakeVisible = ref(false)
const intakeSaving = ref(false)
const intakeForm = ref({ appointment_id: null, store_id: null, bay_id: null, vehicle_id: null, fault_description: '' })
const storeOptions = ref([])
const bayOptions = ref([])
const vehicleOptions = ref([])
const appointmentOptions = ref([])
const bindVisible = ref(false)
const bindSaving = ref(false)
const bindForm = ref({ work_order_id: null, technician_id: null, bay_id: null, store_id: null })
const technicians = ref([])
const bindBays = ref([])
const issueVisible = ref(false)
const issueSaving = ref(false)
const issueForm = ref({ work_order_id: null, part_code: '', qty: 1 })
const partOptions = ref([])

const vehicleLabel = (item) => [item.plate, item.make, item.model].filter(Boolean).join(' ')
const appointmentLabel = (item) => `#${item.id} ${item.scheduled_at || ''} ${item.remark || ''}`.trim()

const loadBays = async (storeId) => {
  bayOptions.value = []
  if (!storeId) return
  const res = await request.get('/bays/', { params: { store_id: storeId, page_size: 100 } })
  bayOptions.value = res.items || []
}

const openIntake = async () => {
  intakeForm.value = { appointment_id: null, store_id: null, bay_id: null, vehicle_id: null, fault_description: '' }
  intakeVisible.value = true
  const [stores, vehicles, appointments] = await Promise.all([
    request.get('/stores/', { params: { page_size: 50 } }),
    request.get('/vehicles/', { params: { page_size: 100 } }),
    request.get('/appointments/', { params: { page_size: 50, status: 'PENDING' } }),
  ])
  storeOptions.value = stores.items || []
  vehicleOptions.value = vehicles.items || []
  const confirmed = await request.get('/appointments/', { params: { page_size: 50, status: 'CONFIRMED' } })
  appointmentOptions.value = [...(appointments.items || []), ...(confirmed.items || [])]
}

const onAppointmentPick = (id) => {
  const row = appointmentOptions.value.find(item => item.id === id)
  if (!row) return
  intakeForm.value.store_id = row.store_id
  intakeForm.value.bay_id = row.bay_id
  intakeForm.value.vehicle_id = row.vehicle_id
  if (!intakeForm.value.fault_description) intakeForm.value.fault_description = row.remark || '预约到店接车'
  loadBays(row.store_id)
}

const submitIntake = async () => {
  intakeSaving.value = true
  try {
    if (intakeForm.value.appointment_id) {
      await request.post('/work-orders/from-appointment', {
        appointment_id: intakeForm.value.appointment_id,
        bay_id: intakeForm.value.bay_id || undefined,
        fault_description: intakeForm.value.fault_description || undefined,
      })
    } else {
      if (!intakeForm.value.vehicle_id && !intakeForm.value.store_id) {
        ElMessage.warning('请选择车辆或门店')
        return
      }
      if (!intakeForm.value.fault_description.trim()) {
        ElMessage.warning('请填写症状')
        return
      }
      await request.post('/work-orders/', {
        fault_description: intakeForm.value.fault_description.trim(),
        vehicle_id: intakeForm.value.vehicle_id || undefined,
        store_id: intakeForm.value.store_id || undefined,
        bay_id: intakeForm.value.bay_id || undefined,
        status: 'INTAKE',
      })
    }
    ElMessage.success('已开接车工单')
    intakeVisible.value = false
    fetchData()
  } finally {
    intakeSaving.value = false
  }
}

const openBind = async (row) => {
  bindForm.value = { work_order_id: row.id, technician_id: row.technician_id || null, bay_id: row.bay_id || null, store_id: row.store_id || null }
  bindVisible.value = true
  const [techRes, bayRes] = await Promise.all([
    request.get('/dispatch/technicians'),
    row.store_id ? request.get('/bays/', { params: { store_id: row.store_id, page_size: 100 } }) : Promise.resolve({ items: [] }),
  ])
  technicians.value = techRes || []
  bindBays.value = bayRes.items || []
}

const submitBind = async () => {
  if (!bindForm.value.technician_id) {
    ElMessage.warning('请选择技师')
    return
  }
  bindSaving.value = true
  try {
    await request.post('/dispatch/bind', {
      work_order_id: bindForm.value.work_order_id,
      technician_id: bindForm.value.technician_id,
      bay_id: bindForm.value.bay_id || undefined,
    })
    ElMessage.success('已绑定技师和工位')
    bindVisible.value = false
    fetchData()
  } finally {
    bindSaving.value = false
  }
}

const openIssue = async (row) => {
  issueForm.value = { work_order_id: row.id, part_code: '', qty: 1 }
  issueVisible.value = true
  if (!partOptions.value.length) {
    const res = await request.get('/spare-parts/', { params: { page_size: 200 } })
    partOptions.value = res.items || []
  }
}

const submitIssue = async () => {
  if (!issueForm.value.part_code) {
    ElMessage.warning('请选择备件')
    return
  }
  issueSaving.value = true
  try {
    await request.post('/spare-parts/issue', issueForm.value)
    ElMessage.success('已出库')
    issueVisible.value = false
  } finally {
    issueSaving.value = false
  }
}

const handleTransition = async (row, toStatus, source = 'TECH_PROGRESS') => {
  try {
    transitionLoading.value[`${row.id}_${toStatus}`] = true
    await workOrderTransition(row.id, {
      to_status: toStatus,
      source,
      remark: undefined,
    })
    await fetchData()
  } catch {
    // handled
  } finally {
    transitionLoading.value[`${row.id}_${toStatus}`] = false
  }
}

const handleFinishRepair = async (row) => {
  await handleTransition(row, 'ARCHIVING')
  router.push(`/work-orders/${row.id}?edit=1`)
}

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const deviceTypeFilter = ref('')
const dateRange = ref(null)
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)

const statusMap = {
  DRAFT: '草稿',
  SUBMITTED: '待派工',
  ASSIGNED: '已派单',
  ACCEPTED: '已接单',
  ARRIVED: '已到达',
  INSPECTING: '检查中',
  IN_PROGRESS: '维修中',
  ARCHIVING: '待归档',
  ARCHIVED: '已归档',
  COMPLETED: '已完成',
  REJECTED: '已退回',
  APPROVED: '报价已确认',
  INTAKE: '接车',
  DIAGNOSING: '诊断中',
  QUOTING: '报价中',
  QC: '质检',
  CLOSED: '已结案',
  CANCELLED: '已取消',
}

const statusLabel = (s) => statusMap[s] || s
const transitionText = (row) => (row.allowed_transitions || []).map(s => statusLabel(s)).join('、')
const formatTime = (t) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'

const STORAGE_KEY = 'workorders_filter'

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    if (statusFilter.value) params.status = statusFilter.value
    if (deviceTypeFilter.value) params.device_type = deviceTypeFilter.value
    if (dateRange.value) {
      params.date_from = dayjs(dateRange.value[0]).format('YYYY-MM-DD')
      params.date_to = dayjs(dateRange.value[1]).format('YYYY-MM-DD')
    }
    const res = await request.get('/work-orders/', { params })
    list.value = res.items
    total.value = res.total

    // 保存筛选条件到 sessionStorage，返回列表时恢复
    saveFilter()
  } catch { /* handled by interceptor */ }
  finally { loading.value = false }
}

const saveFilter = () => {
  const data = {}
  if (keyword.value) data.keyword = keyword.value
  if (statusFilter.value) data.status = statusFilter.value
  if (deviceTypeFilter.value) data.device_type = deviceTypeFilter.value
  if (dateRange.value) {
    data.date_from = dayjs(dateRange.value[0]).format('YYYY-MM-DD')
    data.date_to = dayjs(dateRange.value[1]).format('YYYY-MM-DD')
  }
  if (page.value > 1) data.page = page.value
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => {
  keyword.value = ''
  statusFilter.value = ''
  deviceTypeFilter.value = ''
  dateRange.value = null
  page.value = 1
  sessionStorage.removeItem(STORAGE_KEY)
  fetchData()
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除该工单？', '删除确认', { type: 'warning' })
    await request.delete(`/work-orders/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch { /* cancelled */ }
}

onMounted(() => {
  // 从 sessionStorage 恢复筛选条件
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (raw) {
    try {
      const data = JSON.parse(raw)
      if (data.keyword) keyword.value = data.keyword
      if (data.status) statusFilter.value = data.status
      if (data.device_type) deviceTypeFilter.value = data.device_type
      if (data.date_from && data.date_to) {
        dateRange.value = [new Date(data.date_from), new Date(data.date_to)]
      }
      if (data.page) page.value = data.page
    } catch { /* ignore bad data */ }
  }
  // 拉取设备类型选项
  request.get('/categories/', { params: { category_type: 'DEVICE_TYPE', page_size: 1000 } })
    .then(res => { deviceTypeOptions.value = flattenTree(res.items || []) })
    .catch(() => {})
  fetchData()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title { font-size: 20px; font-weight: 600; color: var(--color-text-primary); }
.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filter-input { width: 260px; }
.filter-select { width: 150px; }
.action-btn { flex-shrink: 0; }
.secondary-btn { background: #fff; border-color: #d9d9d9; color: #333; }
.table-card { min-height: 300px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
.col-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.action-row { display: flex; gap: 6px; align-items: center; }
.progress-row { padding: 6px 8px; background: #F7F8FA; border-radius: 6px; width: 100%; justify-content: flex-end; }

.status-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.status-DRAFT { background: #F2F3F5; color: #4E5969; }
.status-IN_PROGRESS { background: #FFF3E8; color: #FF7D00; }
.status-ARCHIVING { background: #FFF7E8; color: #FF8800; }
.status-ARCHIVED { background: #E8F8EE; color: #00B42A; }
.status-COMPLETED { background: #E8F8EE; color: #00B42A; }
.status-INTAKE { background: #E8F3FF; color: #1677FF; }
.status-DIAGNOSING { background: #F5E8FF; color: #722ED1; }
.status-QUOTING { background: #FFF7E8; color: #FF8800; }
.status-APPROVED { background: #E8FFFB; color: #0FC6C2; }
.status-QC { background: #FFF3E8; color: #FF7D00; }
.status-CLOSED { background: #E8F8EE; color: #00B42A; }
.status-CANCELLED { background: #FFECEC; color: #F53F3F; }
.filter-date { width: 240px; }
</style>
