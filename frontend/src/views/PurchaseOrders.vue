<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">采购入库</h2>
      <el-button type="primary" @click="openCreate">新建采购单</el-button>
    </div>

    <el-card shadow="never">
      <div class="filter-bar">
        <el-select v-model="status" clearable placeholder="状态" style="width: 140px" @change="load">
          <el-option label="已下单" value="ORDERED" />
          <el-option label="部分入库" value="PARTIAL" />
          <el-option label="已入库" value="RECEIVED" />
          <el-option label="已取消" value="CANCELLED" />
        </el-select>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="orders" v-loading="loading">
        <el-table-column prop="po_no" label="采购单号" width="180" />
        <el-table-column prop="supplier" label="供应商" min-width="140" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column label="明细" min-width="240">
          <template #default="{ row }">
            <div v-for="line in row.lines" :key="line.id">
              {{ line.part_name }}（{{ line.part_code }}）订 {{ line.qty_ordered }} / 已收 {{ line.qty_received }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button v-if="row.status === 'ORDERED' || row.status === 'PARTIAL'" size="small" type="primary" @click="receive(row)">入库</el-button>
            <el-button v-if="row.status === 'ORDERED'" size="small" @click="cancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createDialog" title="新建采购单" width="640px">
      <el-form label-width="90px">
        <el-form-item label="门店">
          <el-select v-model="form.store_id" placeholder="选择门店" style="width: 100%">
            <el-option v-for="item in stores" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="供应商"><el-input v-model="form.supplier" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" /></el-form-item>
        <el-form-item label="备件">
          <div v-for="(line, index) in form.lines" :key="index" class="line">
            <el-input v-model="line.part_code" placeholder="编码" />
            <el-input v-model="line.part_name" placeholder="名称" />
            <el-input v-model="line.qty" placeholder="数量" />
            <el-input v-model="line.unit_price" placeholder="单价" />
          </div>
          <el-button text type="primary" @click="form.lines.push({ part_code: '', part_name: '', qty: 1, unit_price: 0 })">加一行</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'

const loading = ref(false)
const orders = ref([])
const stores = ref([])
const status = ref('')
const createDialog = ref(false)
const form = ref({ store_id: null, supplier: '', note: '', lines: [] })

const labels = { ORDERED: '已下单', PARTIAL: '部分入库', RECEIVED: '已入库', CANCELLED: '已取消' }
const statusLabel = (value) => labels[value] || value

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/purchase-orders/', { params: { page: 1, page_size: 50, status: status.value || undefined } })
    orders.value = res.items || []
  } finally {
    loading.value = false
  }
}

const openCreate = async () => {
  const saved = localStorage.getItem('current_store_id')
  form.value = {
    store_id: saved ? Number(saved) : null,
    supplier: '',
    note: '',
    lines: [{ part_code: '', part_name: '', qty: 1, unit_price: 0 }],
  }
  const res = await request.get('/stores/', { params: { page: 1, page_size: 200 } })
  stores.value = res.items || []
  createDialog.value = true
}

const save = async () => {
  if (!form.value.store_id) {
    ElMessage.warning('请选择门店')
    return
  }
  await request.post('/purchase-orders/', {
    store_id: form.value.store_id,
    supplier: form.value.supplier || null,
    note: form.value.note || null,
    lines: form.value.lines.filter(line => line.part_code).map(line => ({
      part_code: line.part_code,
      part_name: line.part_name || line.part_code,
      qty: Number(line.qty),
      unit_price: Number(line.unit_price || 0),
    })),
  })
  ElMessage.success('采购单已创建')
  createDialog.value = false
  load()
}

const receive = async (row) => {
  await ElMessageBox.confirm(`确认将 ${row.po_no} 的未收数量全部入库？`, '采购入库')
  await request.post(`/purchase-orders/${row.id}/receive`, {})
  ElMessage.success('已入库')
  load()
}

const cancel = async (row) => {
  await ElMessageBox.confirm(`取消采购单 ${row.po_no}？`, '确认')
  await request.post(`/purchase-orders/${row.id}/cancel`)
  ElMessage.success('已取消')
  load()
}

onMounted(load)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.line { display: grid; grid-template-columns: 1fr 1.4fr 80px 90px; gap: 8px; margin-bottom: 8px; }
</style>
