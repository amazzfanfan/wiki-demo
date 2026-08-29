import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function SessionHistory({ workspace, isOpen, onClose, onLoadSession }) {
  const { apiFetch } = useAuth()
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isOpen && workspace) {
      fetchSessions()
    }
  }, [isOpen, workspace])

  const fetchSessions = async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/sessions?workspace=' + encodeURIComponent(workspace))
      const data = await res.json()
      setSessions(data)
    } catch (err) {
      console.error('fetch sessions error:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (sessionId, e) => {
    e.stopPropagation()
    if (!confirm('delete this session?')) return
    try {
      await apiFetch('/api/sessions/' + sessionId, { method: 'DELETE' })
      setSessions(s => s.filter(x => x.session_id !== sessionId))
    } catch (err) {
      console.error('delete error:', err)
    }
  }

  const formatTime = (ts) => {
    if (!ts) return '—'
    const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative ml-auto w-80 h-full bg-slate-900/95 border-l border-slate-700/50 overflow-hidden flex flex-col">
        <div className="px-5 py-4 border-b border-slate-700/50 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <span>📜</span> 会话历史
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors text-lg">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {loading ? (
            <div className="text-center text-slate-500 py-8 text-sm">Loading...</div>
          ) : sessions.length === 0 ? (
            <div className="text-center text-slate-500 py-8 text-sm">
              <div className="text-3xl mb-2">📭</div>
              暂无历史会话
            </div>
          ) : (
            sessions.map(s => (
              <button
                key={s.session_id}
                onClick={() => onLoadSession(s.session_id)}
                className="w-full text-left px-3 py-3 rounded-lg bg-slate-800/40 border border-slate-700/30 hover:border-cyan-500/30 hover:bg-slate-800/60 transition-all group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-300 truncate">
                      {s.name || ('session ' + (s.session_id.split(':').pop() || '').slice(0, 8))}
                    </p>
                    <p className="text-[10px] text-slate-500 mt-1 font-mono">{formatTime(s.updated_at)}</p>
                  </div>
                  <button
                    onClick={(e) => handleDelete(s.session_id, e)}
                    className="text-slate-600 hover:text-red-400 transition-colors ml-2 opacity-0 group-hover:opacity-100 text-xs"
                  >
                    🗑️
                  </button>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
