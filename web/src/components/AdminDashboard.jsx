import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function AdminDashboard({ onClose }) {
  const { apiFetch } = useAuth()
  const [activeTab, setActiveTab] = useState('users')
  const [users, setUsers] = useState([])
  const [selectedUser, setSelectedUser] = useState(null)
  const [sessions, setSessions] = useState([])
  const [selectedSession, setSelectedSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { fetchUsers() }, [])
  useEffect(() => { if (selectedUser) fetchSessions(selectedUser) }, [selectedUser])
  useEffect(() => { if (selectedSession) fetchMessages(selectedSession) }, [selectedSession])

  const fetchUsers = async () => {
    setLoading(true)
    try { const r = await apiFetch('/api/admin/users'); setUsers(await r.json()) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }
  const fetchSessions = async (uid) => {
    try { const r = await apiFetch(`/api/admin/sessions?user_id=${encodeURIComponent(uid)}`); setSessions(await r.json()) }
    catch { setSessions([]) }
    setSelectedSession(null); setMessages([])
  }
  const fetchMessages = async (sid) => {
    try { const r = await apiFetch(`/api/admin/sessions/${encodeURIComponent(sid)}/messages`); setMessages((await r.json()).messages || []) }
    catch { setMessages([]) }
  }
  const formatTime = (ts) => {
    if (!ts) return '—'
    const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative ml-auto w-[92vw] max-w-[1300px] h-full bg-slate-900/98 border-l border-slate-700/50 overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-3 border-b border-slate-700/50 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <span>🔍</span> 管理员监控台
            </h3>
            <div className="flex gap-1">
              {[
                { id: 'users', label: '👥 用户 & 会话' },
                { id: 'tasks', label: '📋 任务日志' },
                { id: 'console', label: '🖥️ 控制台' },
              ].map(tab => (
                <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    activeTab === tab.id
                      ? tab.id === 'tasks' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                        : tab.id === 'console' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                      : 'text-slate-500 hover:text-slate-300 border border-transparent'
                  }`}
                >{tab.label}</button>
              ))}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors text-lg">✕</button>
        </div>

        <div className="flex-1 overflow-hidden">
          {activeTab === 'users' && (
            <UsersTab users={users} sessions={sessions} messages={messages} loading={loading}
              selectedUser={selectedUser} selectedSession={selectedSession}
              onSelectUser={setSelectedUser} onSelectSession={setSelectedSession} formatTime={formatTime} />
          )}
          {activeTab === 'tasks' && <TasksTab apiFetch={apiFetch} users={users} />}
          {activeTab === 'console' && <ConsoleTab apiFetch={apiFetch} />}
        </div>
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════
   Users Tab
   ═══════════════════════════════════════════ */
function UsersTab({ users, sessions, messages, loading, selectedUser, selectedSession, onSelectUser, onSelectSession, formatTime }) {
  return (
    <div className="flex h-full">
      <div className="w-56 border-r border-slate-700/40 flex flex-col">
        <div className="px-4 py-2 border-b border-slate-700/30"><p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Users</p></div>
        <div className="flex-1 overflow-y-auto">
          {loading ? <div className="text-center text-slate-500 py-6 text-xs">Loading...</div> : users.map(u => (
            <button key={u.user_id} onClick={() => onSelectUser(u.user_id)}
              className={`w-full text-left px-4 py-3 border-b border-slate-800/40 hover:bg-slate-800/50 transition-colors ${selectedUser === u.user_id ? 'bg-slate-800/70 border-l-2 border-l-cyan-400' : ''}`}>
              <p className="text-xs text-slate-200 font-medium">{u.username}</p>
              <div className="flex items-center gap-2 mt-1">
                <span className={`text-[9px] px-1.5 py-0.5 rounded ${u.role === 'admin' ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-700/50 text-slate-400'}`}>{u.role}</span>
                <span className="text-[9px] text-slate-500">{u.session_count} 会话</span>
              </div>
              <p className="text-[9px] text-slate-600 mt-0.5">活跃: {formatTime(u.last_active)}</p>
            </button>
          ))}
        </div>
      </div>
      <div className="w-64 border-r border-slate-700/40 flex flex-col">
        <div className="px-4 py-2 border-b border-slate-700/30"><p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Sessions {selectedUser ? `— ${selectedUser}` : ''}</p></div>
        <div className="flex-1 overflow-y-auto">
          {!selectedUser ? <div className="text-center text-slate-600 py-8 text-xs">← 选择用户</div>
            : sessions.length === 0 ? <div className="text-center text-slate-600 py-8 text-xs">无会话记录</div>
            : sessions.map(s => (
              <button key={s.session_id} onClick={() => onSelectSession(s.session_id)}
                className={`w-full text-left px-4 py-3 border-b border-slate-800/40 hover:bg-slate-800/50 transition-colors ${selectedSession === s.session_id ? 'bg-slate-800/70 border-l-2 border-l-emerald-400' : ''}`}>
                <p className="text-xs text-slate-200 truncate">{s.name || '(未命名)'}</p>
                <p className="text-[9px] text-slate-500 mt-1 font-mono">{formatTime(s.updated_at)}</p>
              </button>
            ))}
        </div>
      </div>
      <div className="flex-1 flex flex-col">
        <div className="px-4 py-2 border-b border-slate-700/30"><p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Messages {selectedSession ? `— ${selectedSession.split(':').pop()?.slice(0, 12)}` : ''}</p></div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {!selectedSession ? <div className="h-full flex items-center justify-center text-slate-600 text-xs">← 选择会话查看消息</div>
            : messages.length === 0 ? <div className="h-full flex items-center justify-center text-slate-600 text-xs">无消息</div>
            : messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-xl px-4 py-2.5 text-xs ${m.role === 'user' ? 'bg-cyan-500/10 border border-cyan-500/20 text-cyan-200' : 'bg-slate-800/60 border border-slate-700/40 text-slate-300'}`}>
                  <p className="text-[9px] text-slate-500 mb-1 font-mono">{m.role === 'user' ? '👤 用户' : '🤖 AI'}</p>
                  <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════
   Tasks Tab — Per-user/workspace task logs
   ═══════════════════════════════════════════ */
function TasksTab({ apiFetch, users }) {
  const [taskKeys, setTaskKeys] = useState([])
  const [selected, setSelected] = useState(null) // { user_id, workspace }
  const [logs, setLogs] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const logEndRef = useRef(null)
  const esRef = useRef(null)

  useEffect(() => { fetchTaskKeys() }, [])
  useEffect(() => {
    if (selected) startStream(selected.user_id, selected.workspace)
    return () => stopStream()
  }, [selected])
  useEffect(() => {
    if (autoScroll && logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const fetchTaskKeys = async () => {
    try { const r = await apiFetch('/api/admin/task-logs'); setTaskKeys(await r.json()) }
    catch { setTaskKeys([]) }
  }

  const startStream = (userId, workspace) => {
    stopStream()
    setLogs([])
    setIsStreaming(true)
    const token = sessionStorage.getItem('wiki_token')
    const url = `/api/admin/task-logs/${encodeURIComponent(userId)}/${encodeURIComponent(workspace)}/stream?token=${encodeURIComponent(token)}`
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const entry = JSON.parse(e.data)
        setLogs(prev => {
          const next = [...prev, entry]
          return next.length > 1000 ? next.slice(-800) : next
        })
      } catch {}
    }
    es.onerror = () => { setIsStreaming(false); es.close(); esRef.current = null }
  }

  const stopStream = () => {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    setIsStreaming(false)
  }

  const clearLogs = async () => {
    if (!selected) return
    try { await apiFetch(`/api/admin/task-logs/${encodeURIComponent(selected.user_id)}/${encodeURIComponent(selected.workspace)}`, { method: 'DELETE' }) }
    catch {}
    setLogs([])
    fetchTaskKeys()
  }

  const getColor = (level) => {
    switch (level) {
      case 'error': return 'text-red-400'
      case 'warning': return 'text-amber-400'
      case 'success': return 'text-emerald-400'
      default: return 'text-slate-400'
    }
  }

  const getIcon = (level) => {
    switch (level) {
      case 'error': return '❌'
      case 'warning': return '⚠️'
      case 'success': return '✅'
      default: return '▸'
    }
  }

  const formatAgo = (ts) => {
    if (!ts) return ''
    const diff = Math.floor(Date.now() / 1000 - ts)
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  // Group task keys by user
  const grouped = {}
  taskKeys.forEach(tk => {
    if (!grouped[tk.user_id]) grouped[tk.user_id] = []
    grouped[tk.user_id].push(tk)
  })

  return (
    <div className="h-full flex">
      {/* Left: workspace list */}
      <div className="w-64 border-r border-slate-700/40 flex flex-col">
        <div className="px-4 py-2 border-b border-slate-700/30 flex items-center justify-between">
          <p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Task History</p>
          <button onClick={fetchTaskKeys} className="text-[10px] text-slate-500 hover:text-slate-300">🔄</button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {taskKeys.length === 0 ? (
            <div className="text-center text-slate-600 py-8 text-xs">
              暂无任务日志<br/>
              <span className="text-[9px] text-slate-700">用户上传文件并触发摄入后出现</span>
            </div>
          ) : Object.entries(grouped).map(([userId, tasks]) => (
            <div key={userId}>
              <div className="px-4 py-1.5 bg-slate-800/30 border-b border-slate-800/40">
                <span className="text-[9px] text-slate-500 font-mono">👤 {userId}</span>
              </div>
              {tasks.map(tk => (
                <button key={tk.key}
                  onClick={() => setSelected({ user_id: tk.user_id, workspace: tk.workspace })}
                  className={`w-full text-left px-4 py-2.5 border-b border-slate-800/30 hover:bg-slate-800/50 transition-colors ${
                    selected?.key === tk.key || (selected?.user_id === tk.user_id && selected?.workspace === tk.workspace)
                      ? 'bg-amber-500/10 border-l-2 border-l-amber-400' : ''
                  }`}>
                  <p className="text-xs text-slate-200 truncate">📦 {tk.workspace}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[9px] text-slate-500">{tk.total_lines} 行</span>
                    <span className="text-[9px] text-slate-600">{formatAgo(tk.last_active)}</span>
                  </div>
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Right: log viewer */}
      <div className="flex-1 flex flex-col">
        {/* Toolbar */}
        <div className="px-4 py-2 border-b border-slate-800/40 flex items-center gap-3">
          {selected ? (
            <>
              <span className="text-xs text-slate-300 font-medium">
                👤 {selected.user_id} / 📦 {selected.workspace}
              </span>
              <span className={`text-[10px] font-mono ml-3 ${isStreaming ? 'text-emerald-400' : 'text-slate-600'}`}>
                {isStreaming ? '● LIVE' : '○ 已断开'}
              </span>
            </>
          ) : (
            <span className="text-xs text-slate-600">← 选择左侧任务查看日志</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {selected && (
              <>
                <button onClick={() => setAutoScroll(!autoScroll)}
                  className={`text-[10px] px-2 py-0.5 rounded font-mono ${autoScroll ? 'bg-amber-500/20 text-amber-300' : 'text-slate-500 hover:text-slate-300'}`}>
                  自动滚动
                </button>
                <button onClick={clearLogs} className="text-[10px] px-2 py-0.5 rounded text-red-400/60 hover:text-red-400 font-mono">
                  🗑 清除
                </button>
              </>
            )}
          </div>
        </div>

        {/* Log output */}
        <div className="flex-1 overflow-y-auto bg-[#0a0e14] font-mono text-[11px] leading-relaxed p-3">
          {!selected ? (
            <div className="h-full flex items-center justify-center text-slate-700">
              <div className="text-center">
                <p className="text-2xl mb-2">📋</p>
                <p>选择左侧任务查看实时进度日志</p>
                <p className="text-[9px] text-slate-800 mt-1">摄入 · 织网 · 填补黑洞 — 所有操作进度在此追踪</p>
              </div>
            </div>
          ) : logs.length === 0 ? (
            <div className="text-slate-700 text-center py-8">等待日志...</div>
          ) : logs.map((log, i) => (
            <div key={i} className={`py-0.5 hover:bg-slate-800/30 px-1 flex gap-2 ${getColor(log.level)}`}>
              <span className="text-slate-700 select-none shrink-0 w-16">{log.time}</span>
              <span className="shrink-0 w-3">{getIcon(log.level)}</span>
              <span className="flex-1">{log.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>

        {/* Footer */}
        <div className="px-4 py-1.5 border-t border-slate-800/40 flex items-center justify-between bg-slate-900/50">
          <span className="text-[9px] text-slate-600 font-mono">{logs.length} 行</span>
          {selected && <span className="text-[9px] text-slate-700 font-mono">{selected.user_id} : {selected.workspace}</span>}
        </div>
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════
   Console Tab — System journal
   ═══════════════════════════════════════════ */
function ConsoleTab({ apiFetch }) {
  const [logs, setLogs] = useState([])
  const [status, setStatus] = useState(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState('')
  const logEndRef = useRef(null)
  const esRef = useRef(null)

  useEffect(() => { fetchStatus(); startStream(); return () => stopStream() }, [])
  useEffect(() => { if (autoScroll && logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' }) }, [logs])

  const fetchStatus = async () => {
    try { const r = await apiFetch('/api/admin/server-status'); setStatus(await r.json()) } catch {}
  }

  const startStream = () => {
    if (esRef.current) return
    setIsStreaming(true)
    const token = sessionStorage.getItem('wiki_token')
    const es = new EventSource(`/api/admin/logs?token=${encodeURIComponent(token)}`)
    esRef.current = es
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'log') setLogs(prev => {
          const next = [...prev, { time: new Date().toLocaleTimeString('zh-CN'), text: data.content }]
          return next.length > 500 ? next.slice(-400) : next
        })
      } catch {}
    }
    es.onerror = () => {
      setIsStreaming(false); es.close(); esRef.current = null
      setTimeout(() => { if (!esRef.current) startStream() }, 3000)
    }
  }

  const stopStream = () => { if (esRef.current) { esRef.current.close(); esRef.current = null }; setIsStreaming(false) }

  const filteredLogs = filter ? logs.filter(l => l.text.toLowerCase().includes(filter.toLowerCase())) : logs
  const getColor = (text) => {
    if (text.includes('ERROR') || text.includes('❌') || text.includes('Exception')) return 'text-red-400'
    if (text.includes('WARNING') || text.includes('⚠️')) return 'text-amber-400'
    if (text.includes('✅') || text.includes('成功')) return 'text-emerald-400'
    if (text.includes('🚀') || text.includes('启动') || text.includes('Started')) return 'text-cyan-400'
    return 'text-slate-500'
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2.5 border-b border-slate-700/30 flex items-center gap-6 bg-slate-900/50">
        {status ? (
          <>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${status.service === 'active' ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
              <span className="text-[10px] text-slate-400 font-mono">{status.service === 'active' ? '运行中' : '异常'}</span>
            </div>
            <div className="text-[10px] text-slate-500 font-mono" title={status.uptime}>📊 {status.uptime?.split('up ')?.[1]?.split(',')[0] || '—'}</div>
            <div className="text-[10px] text-slate-500 font-mono">💾 {status.disk?.split(/\s+/)?.[3] || '—'} 可用</div>
            <div className="text-[10px] text-slate-500 font-mono">🧠 {status.memory?.split(/\s+/)?.[3] || '—'} 可用内存</div>
          </>
        ) : <span className="text-[10px] text-slate-600 font-mono">加载状态中...</span>}
        <button onClick={fetchStatus} className="text-[10px] text-slate-500 hover:text-slate-300 ml-auto">🔄 刷新</button>
      </div>

      <div className="px-4 py-2 border-b border-slate-800/40 flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1">
          <span className="text-[10px] text-slate-600 font-mono">🔍</span>
          <input type="text" placeholder="过滤日志..." value={filter} onChange={e => setFilter(e.target.value)}
            className="flex-1 bg-slate-800/50 border border-slate-700/30 rounded px-2 py-1 text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-cyan-500/30 font-mono" />
        </div>
        <span className={`text-[10px] font-mono ${isStreaming ? 'text-emerald-400' : 'text-red-400'}`}>{isStreaming ? '● LIVE' : '○ 断开'}</span>
        <button onClick={() => setAutoScroll(!autoScroll)} className={`text-[10px] px-2 py-0.5 rounded font-mono ${autoScroll ? 'bg-cyan-500/20 text-cyan-300' : 'text-slate-500 hover:text-slate-300'}`}>自动滚动</button>
        <button onClick={() => setLogs([])} className="text-[10px] px-2 py-0.5 rounded text-slate-500 hover:text-slate-300 font-mono">清空</button>
      </div>

      <div className="flex-1 overflow-y-auto bg-[#0a0e14] font-mono text-[11px] leading-relaxed p-3">
        {filteredLogs.length === 0 ? <div className="text-slate-700 text-center py-8">等待日志...</div>
          : filteredLogs.map((log, i) => (
            <div key={i} className={`py-0.5 hover:bg-slate-800/30 px-1 ${getColor(log.text)}`}>
              <span className="text-slate-700 mr-2 select-none">{log.time}</span>{log.text}
            </div>
          ))}
        <div ref={logEndRef} />
      </div>

      <div className="px-4 py-1.5 border-t border-slate-800/40 flex items-center justify-between bg-slate-900/50">
        <span className="text-[9px] text-slate-600 font-mono">{filteredLogs.length} 行 {filter ? `(过滤: "${filter}")` : ''}</span>
        <span className="text-[9px] text-slate-700 font-mono">journalctl -u llm-wiki</span>
      </div>
    </div>
  )
}
