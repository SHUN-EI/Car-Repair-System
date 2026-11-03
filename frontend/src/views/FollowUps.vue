<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">回访提醒</h2>
      <div>
        <el-button @click="openCreate">手工排期</el-button>
        <el-button type="primary" :loading="dispatching" @click="dispatchDue">发送到期提醒</el-button>
      </div>
    </div>
    <el-alert
      title="结案交车后会自动排一条评价提醒和一条回访提醒。这里只记录是否发出，不统计回复率。"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
    />
    <el-card shadow="never">
      <el-table :data="rows" v-loading="loading">
        <el-table-column prop="work_order_no" label="工单" width="170" />
        <el-table-column prop="kind_label" label="类型" width="110" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column prop="scheduled_at" label="计划时间" min-width="170" />
        <el-table-column prop="sent_at" label="发送时间" min-width="170" />
        <el-table-column prop="note" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="row.status === 'SCHEDULED'" size="small" @click="cancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" title="排期提醒" width="480px">
      <el-form label-width="90px">
        <el-form-item label="工单 ID"><el-input v-model="form.work_order_id" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.kind" style="width: 100%">
            <el-option label="服务评价" value="RATING" />
            <el-option label="回访复查" value="REVISIT" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划时间">
          <el-date-picker v-model="form.scheduled_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
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
const dispatching = ref(false)
const rows = ref([])
const dialog = ref(false)
const form = ref({ work_order_id: '', kind: 'RATING', scheduled_at: '', note: '' })
const labels = { SCHEDULED: '待发送', SENT: '已发送', CANCELLED: '已取消', SKIPPED: '已跳过' }
const statusLabel = (value) => labels[value] || value

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/follow-ups/', { params: { page: 1, page_size: 50 } })
    rows.value = res.items || []
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  form.value = { work_order_id: '', kind: 'RATING', scheduled_at: '', note: '' }
  dialog.value = true
}

const save = async () => {
  await request.post('/follow-ups/', {
    work_order_id: Number(form.value.work_order_id),
    kind: form.value.kind,
    scheduled_at: form.value.scheduled_at || null,
    note: form.value.note || null,
  })
  ElMessage.success('已排期')
  dialog.value = false
  load()
}

const dispatchDue = async () => {
  dispatching.value = true
  try {
    const res = await request.post('/follow-ups/dispatch')
    ElMessage.success(`已检查 ${res.checked} 条，发出 ${res.sent} 条，跳过 ${res.skipped} 条`)
    load()
  } finally {
    dispatching.value = false
  }
}

const cancel = async (row) => {
  await ElMessageBox.confirm('取消这条未发送的提醒？', '确认')
  await request.post(`/follow-ups/${row.id}/cancel`)
  ElMessage.success('已取消')
  load()
}

onMounted(load)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
</style>
