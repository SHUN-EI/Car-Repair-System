<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">保养套餐</h2>
      <el-button type="primary" @click="openPackage()">新增套餐</el-button>
    </div>

    <el-card shadow="never" class="block">
      <el-table :data="packages" v-loading="loading">
        <el-table-column prop="code" label="编码" width="140" />
        <el-table-column prop="name" label="套餐名称" min-width="160" />
        <el-table-column prop="brand" label="品牌" width="100" />
        <el-table-column prop="series" label="车系" width="120" />
        <el-table-column label="里程 km" width="140">
          <template #default="{ row }">{{ mileageText(row) }}</template>
        </el-table-column>
        <el-table-column prop="list_price" label="套餐价" width="90" />
        <el-table-column label="症状关键词" min-width="160">
          <template #default="{ row }">{{ (row.symptom_keywords || []).join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openPackage(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="removePackage(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div class="page-header">
      <h3>服务项目</h3>
      <el-button type="primary" @click="openSku()">新增项目</el-button>
    </div>
    <el-card shadow="never">
      <el-table :data="skus" v-loading="loading">
        <el-table-column prop="code" label="编码" width="140" />
        <el-table-column prop="name" label="项目名称" min-width="160" />
        <el-table-column prop="category" label="类别" width="100" />
        <el-table-column prop="labor_minutes" label="分钟" width="80" />
        <el-table-column prop="base_price" label="基础价" width="90" />
        <el-table-column label="所属套餐" width="140">
          <template #default="{ row }">{{ packageName(row.package_id) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openSku(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="removeSku(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="packageDialog" :title="packageForm.id ? '编辑套餐' : '新增套餐'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="编码"><el-input v-model="packageForm.code" :disabled="!!packageForm.id" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="packageForm.name" /></el-form-item>
        <el-form-item label="品牌"><el-input v-model="packageForm.brand" placeholder="空为不限" /></el-form-item>
        <el-form-item label="车系"><el-input v-model="packageForm.series" placeholder="空为不限" /></el-form-item>
        <el-form-item label="里程起"><el-input v-model="packageForm.mileage_from" placeholder="公里，可空" /></el-form-item>
        <el-form-item label="里程止"><el-input v-model="packageForm.mileage_to" placeholder="公里，可空" /></el-form-item>
        <el-form-item label="关键词"><el-input v-model="packageForm.keywords" placeholder="用逗号分隔，如 刹车,异响" /></el-form-item>
        <el-form-item label="套餐价"><el-input v-model="packageForm.list_price" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="packageForm.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packageDialog = false">取消</el-button>
        <el-button type="primary" @click="savePackage">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="skuDialog" :title="skuForm.id ? '编辑项目' : '新增项目'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="编码"><el-input v-model="skuForm.code" :disabled="!!skuForm.id" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="skuForm.name" /></el-form-item>
        <el-form-item label="类别"><el-input v-model="skuForm.category" placeholder="保养 / 维修 / 检测" /></el-form-item>
        <el-form-item label="分钟"><el-input v-model="skuForm.labor_minutes" /></el-form-item>
        <el-form-item label="基础价"><el-input v-model="skuForm.base_price" /></el-form-item>
        <el-form-item label="所属套餐">
          <el-select v-model="skuForm.package_id" clearable placeholder="可不选" style="width: 100%">
            <el-option v-for="item in packages" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌"><el-input v-model="skuForm.brand" placeholder="空为不限" /></el-form-item>
        <el-form-item label="车系"><el-input v-model="skuForm.series" placeholder="空为不限" /></el-form-item>
        <el-form-item label="关键词"><el-input v-model="skuForm.keywords" placeholder="用逗号分隔" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="skuDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSku">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'

const loading = ref(false)
const packages = ref([])
const skus = ref([])
const packageDialog = ref(false)
const skuDialog = ref(false)
const packageForm = ref({})
const skuForm = ref({})

const mileageText = (row) => {
  if (row.mileage_from == null && row.mileage_to == null) return '不限'
  return `${row.mileage_from ?? 0} - ${row.mileage_to ?? '不限'}`
}
const packageName = (id) => packages.value.find(item => item.id === id)?.name || '-'
const splitKeywords = (text) => (text || '').split(/[,，]/).map(item => item.trim()).filter(Boolean)
const joinKeywords = (list) => (list || []).join(',')
const numberOrNull = (value) => (value === '' || value == null ? null : Number(value))

const load = async () => {
  loading.value = true
  try {
    const [packageRes, skuRes] = await Promise.all([
      request.get('/service-packages/', { params: { page_size: 200 } }),
      request.get('/service-skus/', { params: { page_size: 200 } }),
    ])
    packages.value = packageRes.items || []
    skus.value = skuRes.items || []
  } finally {
    loading.value = false
  }
}

const openPackage = (row) => {
  packageForm.value = row ? {
    ...row,
    mileage_from: row.mileage_from ?? '',
    mileage_to: row.mileage_to ?? '',
    keywords: joinKeywords(row.symptom_keywords),
  } : { code: '', name: '', brand: '', series: '', mileage_from: '', mileage_to: '', keywords: '', list_price: 0, description: '' }
  packageDialog.value = true
}
const savePackage = async () => {
  const payload = {
    code: packageForm.value.code,
    name: packageForm.value.name,
    description: packageForm.value.description || null,
    brand: packageForm.value.brand || null,
    series: packageForm.value.series || null,
    mileage_from: numberOrNull(packageForm.value.mileage_from),
    mileage_to: numberOrNull(packageForm.value.mileage_to),
    symptom_keywords: splitKeywords(packageForm.value.keywords),
    list_price: Number(packageForm.value.list_price || 0),
    is_active: true,
  }
  if (packageForm.value.id) await request.put(`/service-packages/${packageForm.value.id}`, payload)
  else await request.post('/service-packages/', payload)
  ElMessage.success('套餐已保存')
  packageDialog.value = false
  load()
}
const removePackage = async (row) => {
  await ElMessageBox.confirm(`删除套餐 ${row.name}？`, '确认')
  await request.delete(`/service-packages/${row.id}`)
  ElMessage.success('已删除')
  load()
}

const openSku = (row) => {
  skuForm.value = row ? {
    ...row,
    keywords: joinKeywords(row.symptom_keywords),
  } : { code: '', name: '', category: '保养', labor_minutes: 30, base_price: 0, package_id: null, brand: '', series: '', keywords: '' }
  skuDialog.value = true
}
const saveSku = async () => {
  const payload = {
    code: skuForm.value.code,
    name: skuForm.value.name,
    category: skuForm.value.category || null,
    labor_minutes: Number(skuForm.value.labor_minutes || 0),
    base_price: Number(skuForm.value.base_price || 0),
    package_id: skuForm.value.package_id || null,
    brand: skuForm.value.brand || null,
    series: skuForm.value.series || null,
    symptom_keywords: splitKeywords(skuForm.value.keywords),
    is_active: true,
  }
  if (skuForm.value.id) await request.put(`/service-skus/${skuForm.value.id}`, payload)
  else await request.post('/service-skus/', payload)
  ElMessage.success('项目已保存')
  skuDialog.value = false
  load()
}
const removeSku = async (row) => {
  await ElMessageBox.confirm(`删除项目 ${row.name}？`, '确认')
  await request.delete(`/service-skus/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.block { margin-bottom: 16px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin: 8px 0 12px; }
</style>
