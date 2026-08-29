import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // sessionStorage 每个标签页独立，允许多账号同时在线
    const saved = sessionStorage.getItem('wiki_token')
    const savedUser = sessionStorage.getItem('wiki_user')
    if (saved && savedUser) {
      try {
        setToken(saved)
        setUser(JSON.parse(savedUser))
      } catch { sessionStorage.clear() }
    }
    setLoading(false)
  }, [])

  const apiFetch = useCallback(async (url, options = {}) => {
    const t = token || sessionStorage.getItem('wiki_token')
    const headers = { ...options.headers }
    if (t) headers['Authorization'] = 'Bearer ' + t
    if (!(options.body instanceof FormData) && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json'
    }
    const res = await fetch(url, { ...options, headers })
    if (res.status === 401) {
      logout()
      throw new Error('token expired')
    }
    return res
  }, [token])

  const login = async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'login failed' }))
      throw new Error(err.detail || 'login failed')
    }
    const data = await res.json()
    setToken(data.token)
    setUser({ user_id: data.user_id, username: data.username, role: data.role || 'user' })
    sessionStorage.setItem('wiki_token', data.token)
    sessionStorage.setItem('wiki_user', JSON.stringify({ user_id: data.user_id, username: data.username, role: data.role || 'user' }))
    return data
  }

  const register = async (username, password) => {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'register failed' }))
      throw new Error(err.detail || 'register failed')
    }
    const data = await res.json()
    setToken(data.token)
    setUser({ user_id: data.user_id, username: data.username, role: data.role || 'user' })
    sessionStorage.setItem('wiki_token', data.token)
    sessionStorage.setItem('wiki_user', JSON.stringify({ user_id: data.user_id, username: data.username, role: data.role || 'user' }))
    return data
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    sessionStorage.removeItem('wiki_token')
    sessionStorage.removeItem('wiki_user')
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, apiFetch }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be inside AuthProvider')
  return ctx
}
