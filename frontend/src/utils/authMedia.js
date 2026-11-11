/** 登录后读取上传附件。img/video 不能带 Authorization，先换成 blob 地址。 */
export async function toAuthObjectUrl(url) {
  if (!url || String(url).startsWith('blob:') || String(url).startsWith('data:')) return url
  if (!String(url).includes('/upload/files/')) return url
  const token = localStorage.getItem('auth_token')
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) return ''
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}
