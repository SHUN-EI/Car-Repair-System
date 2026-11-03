<template>
  <div class="owner-book">
    <div class="block">
      <div class="label">门店</div>
      <select v-model="storeId" @change="loadSlots">
        <option value="">请选择门店</option>
        <option v-for="item in stores" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select>
    </div>
    <div class="block">
      <div class="label">日期</div>
      <input v-model="day" type="date" @change="loadSlots" />
    </div>
    <div class="block">
      <div class="label">车辆</div>
      <select v-model="vehicleId">
        <option value="">请选择车辆</option>
        <option v-for="item in vehicles" :key="item.id" :value="item.id">{{ vehicleText(item) }}</option>
      </select>
      <button class="link" type="button" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '添加我的车' }}</button>
      <div v-if="showCreate" class="create-car">
        <input v-model="plate" placeholder="车牌" />
        <input v-model="make" placeholder="品牌" />
        <input v-model="model" placeholder="车型" />
        <button type="button" :disabled="creating" @click="createVehicle">保存车辆</button>
      </div>
    </div>

    <div v-if="loading" class="hint">正在加载时段</div>
    <div v-else-if="!storeId" class="hint">选择门店和日期后查看可预约工位</div>
    <div v-else-if="!slots.length" class="hint">这一天没有可预约工位</div>
    <div v-else class="slots">
      <button
        v-for="slot in slots"
        :key="slot.bay_id + slot.start"
        type="button"
        class="slot"
        :class="{ on: picked && picked.bay_id === slot.bay_id && picked.start === slot.start, off: !slot.available }"
        :disabled="!slot.available"
        @click="picked = slot"
      >
        <span>{{ timeText(slot.start) }}</span>
        <span>{{ slot.bay_name }}</span>
        <span>{{ slot.available ? '可约' : '已满' }}</span>
      </button>
    </div>

    <div class="block">
      <div class="label">备注</div>
      <textarea v-model="remark" rows="3" placeholder="症状或保养项目，例如刹车异响"></textarea>
    </div>
    <button class="submit" type="button" :disabled="booking" @click="book">预约</button>
    <p v-if="message" class="ok">{{ message }}</p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import request from '../../api'

const stores = ref([])
const vehicles = ref([])
const slots = ref([])
const storeId = ref('')
const vehicleId = ref('')
const day = ref(new Date().toISOString().slice(0, 10))
const picked = ref(null)
const remark = ref('')
const loading = ref(false)
const booking = ref(false)
const message = ref('')
const showCreate = ref(false)
const creating = ref(false)
const plate = ref('')
const make = ref('')
const model = ref('')

const vehicleText = (item) => [item.plate, item.make, item.model].filter(Boolean).join(' ')
const timeText = (value) => (value || '').slice(11, 16)

const loadVehicles = async () => {
  const res = await request.get('/vehicles/', { params: { page_size: 50 } })
  vehicles.value = res.items || []
  if (!vehicleId.value && vehicles.value.length) vehicleId.value = String(vehicles.value[0].id)
}

const loadSlots = async () => {
  picked.value = null
  slots.value = []
  if (!storeId.value || !day.value) return
  loading.value = true
  try {
    const res = await request.get('/appointments/slots', { params: { store_id: storeId.value, day: day.value } })
    slots.value = res.slots || []
  } finally {
    loading.value = false
  }
}

const createVehicle = async () => {
  if (!plate.value.trim()) return
  creating.value = true
  try {
    const res = await request.post('/vehicles/', {
      plate: plate.value.trim(),
      make: make.value.trim() || undefined,
      model: model.value.trim() || undefined,
    })
    await loadVehicles()
    vehicleId.value = String(res.id)
    showCreate.value = false
    plate.value = ''
  } finally {
    creating.value = false
  }
}

const book = async () => {
  message.value = ''
  if (!picked.value || !vehicleId.value) {
    message.value = '请选择车辆和可预约时段'
    return
  }
  booking.value = true
  try {
    await request.post('/appointments/book', {
      store_id: Number(storeId.value),
      bay_id: picked.value.bay_id,
      vehicle_id: Number(vehicleId.value),
      scheduled_at: picked.value.start.replace(' ', 'T'),
      remark: remark.value.trim() || undefined,
    })
    message.value = '预约已提交，等待门店确认'
    await loadSlots()
  } finally {
    booking.value = false
  }
}

onMounted(async () => {
  const res = await request.get('/stores/', { params: { page_size: 20 } })
  stores.value = (res.items || []).filter(item => item.is_active !== false)
  if (stores.value.length) {
    storeId.value = String(stores.value[0].id)
    await loadSlots()
  }
  await loadVehicles()
})
</script>

<style scoped>
.owner-book { padding: 16px; }
.block { margin-bottom: 14px; }
.label { font-size: 13px; color: #4E5969; margin-bottom: 6px; }
select, input, textarea {
  width: 100%; box-sizing: border-box; border: 1px solid #E5E6EB; border-radius: 8px;
  padding: 10px 12px; font-size: 14px; background: #fff;
}
.link { margin-top: 8px; border: 0; background: none; color: #1677FF; padding: 0; }
.create-car { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.create-car button, .submit {
  border: 0; background: #1677FF; color: #fff; border-radius: 8px; padding: 10px 12px;
}
.slots { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.slot {
  display: flex; justify-content: space-between; border: 1px solid #E5E6EB; background: #fff;
  border-radius: 8px; padding: 12px; font-size: 14px;
}
.slot.on { border-color: #1677FF; background: #E8F3FF; }
.slot.off { color: #C9CDD4; }
.hint, .ok { color: #4E5969; font-size: 13px; }
.ok { color: #00B42A; }
.submit { width: 100%; margin-top: 4px; }
</style>
