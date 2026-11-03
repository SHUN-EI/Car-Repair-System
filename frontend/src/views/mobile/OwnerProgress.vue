<template>
  <div class="owner-progress">
    <template v-if="!detailId">
      <div v-if="!list.length" class="hint">还没有维保进度。预约到店并接车后会显示在这里。</div>
      <div v-for="item in list" :key="item.id" class="card" @click="open(item.id)">
        <div class="row">
          <span>{{ item.work_order_no }}</span>
          <span class="tag">{{ label(item.status) }}</span>
        </div>
        <div class="desc">{{ item.fault_description }}</div>
        <div class="meta">{{ item.vehicle_plate || '未关联车牌' }}</div>
      </div>
    </template>
    <template v-else>
      <div class="card" v-if="detail">
        <div class="row">
          <span>{{ detail.work_order_no }}</span>
          <span class="tag">{{ label(detail.status) }}</span>
        </div>
        <div class="desc">{{ detail.fault_description }}</div>
        <div class="meta">{{ detail.vehicle_plate || '' }}</div>
      </div>
      <div class="steps">
        <div v-for="step in steps" :key="step.value" class="step" :class="{ on: step.reached, now: step.value === detail?.status }">
          <span class="dot"></span>
          <span>{{ step.label }}</span>
        </div>
      </div>
      <div class="logs">
        <div v-for="log in logs" :key="log.id" class="log">
          <div>{{ label(log.to_status) }}</div>
          <div class="meta">{{ log.operator_name || '门店' }} · {{ log.created_at }}</div>
          <div v-if="log.remark" class="meta">{{ log.remark }}</div>
        </div>
        <div v-if="!logs.length" class="hint">暂无进度记录</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '../../api'

const route = useRoute()
const router = useRouter()
const list = ref([])
const detail = ref(null)
const logs = ref([])
const detailId = ref(route.params.id || '')

const labels = {
  DRAFT: '草稿', INTAKE: '接车', DIAGNOSING: '诊断中', QUOTING: '报价中', APPROVED: '报价已确认',
  IN_PROGRESS: '维修中', QC: '质检', COMPLETED: '已完成', CLOSED: '已结案', CANCELLED: '已取消',
}
const path = ['INTAKE', 'DIAGNOSING', 'QUOTING', 'APPROVED', 'IN_PROGRESS', 'QC', 'COMPLETED', 'CLOSED']
const label = (status) => labels[status] || status || '-'
const steps = ref([])

const buildSteps = (status) => {
  const index = path.indexOf(status)
  steps.value = path.map((value, i) => ({
    value,
    label: labels[value],
    reached: index >= 0 && i <= index,
  }))
}

const loadList = async () => {
  const res = await request.get('/work-orders/', { params: { page_size: 50 } })
  list.value = res.items || []
}

const loadDetail = async (id) => {
  const [order, progress] = await Promise.all([
    request.get(`/work-orders/${id}`),
    request.get(`/work-orders/${id}/progress`),
  ])
  detail.value = order
  logs.value = progress.progress_logs || []
  buildSteps(order.status)
}

const open = (id) => router.push(`/m/progress/${id}`)

watch(() => route.params.id, (id) => {
  detailId.value = id || ''
  if (id) loadDetail(id)
  else loadList()
})

onMounted(() => {
  if (detailId.value) loadDetail(detailId.value)
  else loadList()
})
</script>

<style scoped>
.owner-progress { padding: 16px; }
.card, .log {
  background: #fff; border-radius: 10px; padding: 14px; margin-bottom: 10px;
}
.row { display: flex; justify-content: space-between; font-weight: 600; }
.tag { color: #1677FF; font-weight: 500; font-size: 13px; }
.desc { margin-top: 8px; color: #1D2129; }
.meta, .hint { color: #86909C; font-size: 12px; margin-top: 6px; }
.steps { background: #fff; border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
.step { display: flex; align-items: center; gap: 8px; color: #C9CDD4; padding: 6px 0; font-size: 14px; }
.step.on { color: #1D2129; }
.step.now { color: #1677FF; font-weight: 600; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
</style>
