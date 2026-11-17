import request from './index'

/**
 * 查询当天的排班列表，可带查询参数。
 */
export const listDutyToday = (params) => {
  return request({
    url: '/duty-schedules/today',
    method: 'get',
    params
  })
}

/**
 * 获取班次元数据，例如班次名称和时间段。
 */
export const getShiftMeta = () => {
  return request({
    url: '/duty-schedules/shift-meta',
    method: 'get',
  })
}

/**
 * 批量创建排班记录。
 */
export const createDutyBatch = (data) => {
  return request({
    url: '/duty-schedules/batch',
    method: 'post',
    data
  })
}

/**
 * 列出角色为维修员的用户，用于排班选人。
 */
export const listTechnicians = (params) => {
  return request({
    url: '/users',
    method: 'get',
    params: { role: 'technician', ...params }
  })
}

/**
 * 按条件分页查询排班记录。
 */
export const scheduleList = (params) => {
  return request({
    url: '/duty-schedules',
    method: 'get',
    params
  })
}

/**
 * 新建一条排班。
 */
export const scheduleCreate = (data) => {
  return request({
    url: '/duty-schedules',
    method: 'post',
    data
  })
}

/**
 * 按编号删除一条排班。
 */
export const scheduleDelete = (id) => {
  return request({
    url: `/duty-schedules/${id}`,
    method: 'delete'
  })
}

/**
 * 按编号列表批量删除排班。
 */
export const scheduleBatchDelete = (ids) => {
  return request({
    url: '/duty-schedules/batch',
    method: 'delete',
    data: { ids }
  })
}

/**
 * 批量登记请假。
 */
export const leaveBatchCreate = (data) => {
  return request({
    url: '/duty-schedules/leave/batch',
    method: 'post',
    data
  })
}

/**
 * 查询指定日期的请假汇总。
 */
export const leaveSummary = (date) => {
  return request({
    url: '/duty-schedules/leave/summary',
    method: 'get',
    params: { date }
  })
}

export const leaveSummaryByDate = leaveSummary

/**
 * 对指定工单发起状态流转。
 */
export const workOrderTransition = (workOrderId, data) => {
  return request({
    url: `/work-orders/${workOrderId}/transition`,
    method: 'post',
    data
  })
}

// ===========================================
// Phase 2.1: 请假申请 API
// ===========================================

/** 提交前预检：未完成工单冲突 + 在岗人数不足警告 */
export const leavePreCheck = (params) => {
  return request({
    url: '/leave-requests/check-conflicts',
    method: 'get',
    params
  })
}

/** 提交请假申请 */
export const leaveSubmit = (data) => {
  return request({
    url: '/leave-requests',
    method: 'post',
    data
  })
}

/** 请假列表（主管端分页） */
export const leaveList = (params) => {
  return request({
    url: '/leave-requests',
    method: 'get',
    params
  })
}

/** 我的请假记录 */
export const leaveMyList = (params) => {
  return request({
    url: '/leave-requests/my',
    method: 'get',
    params
  })
}

/** 请假详情（含冲突工单 + 在岗人数附加信息） */
export const leaveDetail = (id) => {
  return request({
    url: `/leave-requests/${id}`,
    method: 'get'
  })
}

/** 主管批准（携带 substitute_user_id 强制顶岗人） */
export const leaveApprove = (id, data) => {
  return request({
    url: `/leave-requests/${id}/approve`,
    method: 'post',
    data
  })
}

/** 主管拒绝 */
export const leaveReject = (id, data) => {
  return request({
    url: `/leave-requests/${id}/reject`,
    method: 'post',
    data
  })
}

/** 师傅撤销（仅 PENDING 状态） */
export const leaveCancel = (id) => {
  return request({
    url: `/leave-requests/${id}/cancel`,
    method: 'post'
  })
}

/** 复制上周排班矩阵 */
export const copyLastWeekSchedule = (data) => {
  return request({
    url: '/duty-schedules/copy-week',
    method: 'post',
    data
  })
}

/** 查询周排班矩阵 */
export const listWeekScheduleMatrix = (params) => {
  return request({
    url: '/duty-schedules/week',
    method: 'get',
    params
  })
}

/**
 * 批量创建排班的兼容导出，实际仍请求同一批量接口。
 */
export const batchCreateDutySchedules = (data) => {
  return request({
    url: '/duty-schedules/batch',
    method: 'post',
    data
  })
}
