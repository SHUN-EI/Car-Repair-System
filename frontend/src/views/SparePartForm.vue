<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">{{ isNew ? '新增备件' : '编辑备件' }}</h2>
    </div>

    <el-card shadow="never">
      <el-form :model="form" label-width="100px" style="max-width: 800px">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="备件编码" required>
              <el-input v-model="form.part_code" placeholder="如 P-001" :disabled="!isNew" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="备件名称" required>
              <el-input v-model="form.part_name" placeholder="如 轴承 6205-2RS" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="规格型号">
              <el-input v-model="form.specification" placeholder="规格型号" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="单位">
              <el-input v-model="form.unit" placeholder="个/套/台" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="库存数量">
              <el-input-number v-model="form.stock_quantity" :min="0" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="安全库存">
              <el-input-number v-model="form.safety_stock" :min="0" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="单价">
              <el-input-number v-model="form.unit_price" :min="0" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="适用设备">
              <el-input v-model="form.device_type" placeholder="适用设备类型" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="存放位置">
              <el-input v-model="form.location" placeholder="仓库/货架位置" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="供应商">
          <el-input v-model="form.supplier" placeholder="供应商名称" />
        </el-form-item>
        <el-form-item label="车型适配">
          <div class="fitment-tip">品牌对应车辆品牌，车系对应车型。某一行全部留空表示不限车型；不添加规则的备件不会出现在适配查询里。</div>
          <div v-for="(rule, index) in form.fitment" :key="index" class="fitment-row">
            <el-input v-model="rule.brand" placeholder="品牌" />
            <el-input v-model="rule.series" placeholder="车系" />
            <el-input v-model="rule.year_from" placeholder="年款起" />
            <el-input v-model="rule.year_to" placeholder="年款止" />
            <el-input v-model="rule.engine" placeholder="发动机" />
            <el-button link type="danger" @click="form.fitment.splice(index, 1)">删除</el-button>
          </div>
          <el-button @click="form.fitment.push({ brand: '', series: '', year_from: '', year_to: '', engine: '' })">添加适配</el-button>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
          <el-button @click="$router.push('/spare-parts')">返回列表</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../api'

const route = useRoute()
const router = useRouter()
const isNew = computed(() => !route.params.id || route.params.id === 'new')
const saving = ref(false)

const form = ref({
  part_code: '', part_name: '', specification: '', unit: '个',
  stock_quantity: 0, safety_stock: 0, unit_price: 0,
  device_type: '', location: '', supplier: '', fitment: []
})

const loadData = async () => {
  if (isNew.value) return
  const res = await request.get(`/spare-parts/${route.params.id}`)
  Object.assign(form.value, res)
  form.value.fitment = (res.fitment || []).map(rule => ({
    brand: rule.brand || '',
    series: rule.series || '',
    year_from: rule.year_from ?? '',
    year_to: rule.year_to ?? '',
    engine: rule.engine || '',
  }))
}

const handleSave = async () => {
  saving.value = true
  try {
    const data = {
      ...form.value,
      fitment: (form.value.fitment || []).map(rule => ({
        brand: rule.brand || null,
        series: rule.series || null,
        year_from: rule.year_from === '' || rule.year_from == null ? null : Number(rule.year_from),
        year_to: rule.year_to === '' || rule.year_to == null ? null : Number(rule.year_to),
        engine: rule.engine || null,
      })),
    }
    if (isNew.value) {
      await request.post('/spare-parts/', data)
      ElMessage.success('创建成功')
    } else {
      await request.put(`/spare-parts/${route.params.id}`, data)
      ElMessage.success('更新成功')
    }
    router.push('/spare-parts')
  } finally { saving.value = false }
}

onMounted(loadData)
</script>

<style scoped>
.fitment-tip { color: #86909C; font-size: 12px; margin-bottom: 8px; }
.fitment-row { display: flex; gap: 8px; margin-bottom: 8px; }
.fitment-row .el-input { width: 120px; }
</style>
