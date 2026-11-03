<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">车辆档案</h2>
      <el-button v-if="!isSupervisor" type="primary" @click="openCreate">新增车辆</el-button>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="搜索车牌 / VIN / 品牌 / 车型"
          clearable
          class="filter-input"
          @clear="handleSearch"
          @keyup.enter="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>
    </el-card>

    <el-card class="table-card" shadow="never">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column prop="plate" label="车牌号" width="140" />
        <el-table-column prop="vin" label="VIN" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.vin || '-' }}</template>
        </el-table-column>
        <el-table-column label="品牌车型" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ vehicleTitle(row) }}</template>
        </el-table-column>
        <el-table-column prop="year" label="年款" width="90">
          <template #default="{ row }">{{ row.year || '-' }}</template>
        </el-table-column>
        <el-table-column label="车主" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.owner_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openEdit(row)" :disabled="isSupervisor">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)" :disabled="isSupervisor">删除</el-button>
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

    <el-dialog :title="editingId ? '编辑车辆' : '新增车辆'" v-model="dialogVisible" width="520px" destroy-on-close>
      <el-form :model="form" label-width="80px">
        <el-form-item label="车牌号" required>
          <el-input v-model="form.plate" placeholder="例如 粤B12345" maxlength="20" />
        </el-form-item>
        <el-form-item label="VIN">
          <el-input v-model="form.vin" placeholder="17 位车架号，可空" maxlength="17" />
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="form.make" placeholder="例如 丰田" maxlength="50" />
        </el-form-item>
        <el-form-item label="车型">
          <el-input v-model="form.model" placeholder="例如 凯美瑞" maxlength="80" />
        </el-form-item>
        <el-form-item label="年款">
          <el-input-number v-model="form.year" :min="1980" :max="2100" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="车主">
          <el-select v-model="form.owner_id" clearable filterable placeholder="选择客户" style="width: 100%">
            <el-option v-for="c in customers" :key="c.id" :label="customerLabel(c)" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'

const currentUser = (() => {
  try {
    const raw = localStorage.getItem('current_user')
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
})()
const isSupervisor = currentUser.role === 'SUPERVISOR'

const list = ref([])
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref(null)
const customers = ref([])
const emptyForm = () => ({ plate: '', vin: '', make: '', model: '', year: null, owner_id: null })
const form = ref(emptyForm())

const vehicleTitle = (row) => {
  const parts = [row.make, row.model].filter(Boolean)
  return parts.length ? parts.join(' ') : '-'
}
const customerLabel = (c) => c.phone ? `${c.name}（${c.phone}）` : c.name

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (keyword.value) params.keyword = keyword.value
    const res = await request.get('/vehicles/', { params })
    list.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

const loadCustomers = async () => {
  try {
    const res = await request.get('/customers/', { params: { page: 1, page_size: 200 } })
    customers.value = res.items || []
  } catch { /* 拦截器已提示 */ }
}

const handleSearch = () => { page.value = 1; fetchData() }
const handleReset = () => { keyword.value = ''; page.value = 1; fetchData() }

const openCreate = async () => {
  editingId.value = null
  form.value = emptyForm()
  await loadCustomers()
  dialogVisible.value = true
}

const openEdit = async (row) => {
  editingId.value = row.id
  form.value = {
    plate: row.plate || '',
    vin: row.vin || '',
    make: row.make || '',
    model: row.model || '',
    year: row.year || null,
    owner_id: row.owner_id || null,
  }
  await loadCustomers()
  dialogVisible.value = true
}

const handleSave = async () => {
  if (!form.value.plate || !form.value.plate.trim()) {
    ElMessage.warning('请填写车牌号')
    return
  }
  saving.value = true
  try {
    const payload = {
      plate: form.value.plate.trim(),
      vin: form.value.vin ? form.value.vin.trim() : null,
      make: form.value.make || null,
      model: form.value.model || null,
      year: form.value.year || null,
      owner_id: form.value.owner_id || null,
    }
    if (editingId.value) {
      await request.put(`/vehicles/${editingId.value}`, payload)
      ElMessage.success('车辆已更新')
    } else {
      await request.post('/vehicles/', payload)
      ElMessage.success('车辆已创建')
    }
    dialogVisible.value = false
    fetchData()
  } finally {
    saving.value = false
  }
}

const handleDelete = (row) => {
  ElMessageBox.confirm(`确认删除车辆 ${row.plate}？`, '删除车辆', { type: 'warning' })
    .then(async () => {
      await request.delete(`/vehicles/${row.id}`)
      ElMessage.success('已删除')
      fetchData()
    })
    .catch(() => {})
}

onMounted(fetchData)
</script>

<style scoped>
.filter-card { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filter-input { width: 280px; }
.table-card { min-height: 240px; }
</style>
