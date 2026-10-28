/* Shared API helper */
const API = '';
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form').forEach(form => { form.noValidate = true; });
});
function token() { return sessionStorage.getItem('token'); }
function clearSession() {
  ['token', 'role', 'full_name', 'email', 'avatar'].forEach(key => sessionStorage.removeItem(key));
}
function saveSession(session) {
  sessionStorage.setItem('token', session.access_token);
  sessionStorage.setItem('role', session.role);
  sessionStorage.setItem('full_name', session.full_name);
  sessionStorage.setItem('email', session.email);
}
function authHeaders() {
  return { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' };
}
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { ...authHeaders(), ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    clearSession();
    location.href = '/login';
    throw new Error('Unauthorized');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.message || 'Lỗi API');
  return data;
}
function fmt(n) { return (Number(n) || 0).toLocaleString('vi-VN') + 'đ'; }
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
}
function toast(msg, ok = true) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  const box = document.createElement('div');
  box.className = `toast-box ${ok ? '' : 'err'}`;
  box.textContent = `${ok ? '✅' : '🚨'} ${String(msg ?? '')}`;
  el.replaceChildren(box);
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3500);
}
function chatErrorMessage(error) {
  const message = error?.message || '';
  if (error?.name === 'TypeError' || message === 'Failed to fetch') {
    return 'AI hiện đang quá tải hoặc hết lượt sử dụng. Vui lòng thử lại sau.';
  }
  if (/AI|Gemini|quota|rate.?limit|503|429|401|403|API key|xử lý ảnh/i.test(message)) {
    return 'AI hiện đang quá tải hoặc hết lượt sử dụng. Vui lòng thử lại sau.';
  }
  return message || 'AI hiện đang quá tải hoặc hết lượt sử dụng. Vui lòng thử lại sau.';
}
function logout() {
  const modal = document.getElementById('modal-logout');
  if (modal) {
    modal.classList.add('show');
    return;
  }
  clearSession();
  location.href = '/login';
}
function cancelLogout() {
  document.getElementById('modal-logout')?.classList.remove('show');
}
function confirmLogout() {
  clearSession();
  location.href = '/login';
}
function setAvatar(element, avatar, name, fallback = 'U') {
  if (!element) return;
  element.textContent = '';
  if (avatar) {
    const image = document.createElement('img');
    image.src = avatar;
    image.alt = '';
    image.onerror = () => setAvatar(element, '', name, fallback);
    element.appendChild(image);
    return;
  }
  element.textContent = (name || fallback).charAt(0).toUpperCase();
}
async function requireAuth(role) {
  if (!token()) {
    location.href = '/login';
    return false;
  }
  try {
    const res = await fetch(API + '/api/auth/me', {
      headers: { Authorization: 'Bearer ' + token() }
    });
    if (!res.ok) {
      clearSession();
      location.href = '/login';
      return false;
    }
    const me = await res.json();
    sessionStorage.setItem('role', me.role);
    sessionStorage.setItem('full_name', me.full_name || '');
    sessionStorage.setItem('email', me.email || '');
    sessionStorage.setItem('avatar', me.avatar || '');
    if (role && me.role !== role) {
      location.href = me.role === 'admin' ? '/admin' : '/';
      return false;
    }
    return true;
  } catch (_) {
    toast('Không thể xác minh phiên đăng nhập. Vui lòng thử lại.', false);
    return false;
  }
}
