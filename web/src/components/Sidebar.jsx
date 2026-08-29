import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function Sidebar({ mode, onModeChange, selectedSandbox, onSandboxSelect, onOpenSettings, onOpenSessions, onOpenAdmin }) {
  const { user, logout, apiFetch } = useAuth()
  const [sandboxes, setSandboxes] = useState([])

  const fetchWorkspaces = () => {
    apiFetch('/api/workspaces')
      .then(res => res.json())
      .then(data => {
        setSandboxes(data.map(name => ({ id: name, name: name, status: 'active' })))
      })
      .catch(err => console.error("fetch workspaces error:", err))
  }

  useEffect(() => { fetchWorkspaces() }, [])

  const handleCreateSandbox = async () => {
    const name = window.prompt("请输入新知识沙箱的名称：")
    if (!name || !name.trim()) return
    try {
      const response = await apiFetch("/api/workspaces/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() })
      })
      if (!response.ok) throw new Error("create failed")
      const newSandbox = { id: name.trim(), name: name.trim(), status: 'active' }
      setSandboxes(prev => [newSandbox, ...prev.filter(s => s.id !== name.trim())])
    } catch (err) {
      alert("创建失败: " + err.message)
    }
  }

  const handleDeleteSandbox = async (name, e) => {
    e.stopPropagation()
    // 检查沙箱是否正在运行摄入任务
    try {
      const progressRes = await apiFetch(`/api/task-logs/${encodeURIComponent(name)}/status`)
      if (progressRes.ok) {
        const data = await progressRes.json()
        const status = data?.status
        if (status === 'ingesting' || status === 'stopping') {
          alert(`沙箱「${name}」正在执行摄入任务，请先停止任务再删除。`)
          return
        }
      }
    } catch (_) {
      // 接口不可用时不阻塞删除
    }
    if (!window.confirm(`确定要永久删除沙箱「${name}」及其所有知识数据吗？\n\n此操作不可撤销！`)) return
    try {
      const response = await apiFetch(`/api/workspaces/${encodeURIComponent(name)}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('delete failed')
      if (name === selectedSandbox) onSandboxSelect(null)
      fetchWorkspaces()
    } catch (err) {
      alert("删除失败: " + err.message)
    }
  }

  return (
    <aside className="w-[260px] min-w-[260px] h-screen bg-slate-950/80 border-r border-slate-700/60 flex flex-col relative scanline overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-cyan-500/[0.02] to-transparent h-8 animate-scan" />

      <div className="px-5 py-5 border-b border-slate-700/60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🧠</span>
            <div>
              <h1 className="text-lg font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent tracking-wide">
                LLM-Wiki OS
              </h1>
              <p className="text-[10px] text-slate-500 font-mono tracking-widest uppercase">Knowledge Graph Engine</p>
            </div>
          </div>
          <button onClick={logout} className="text-slate-600 hover:text-red-400 transition-colors text-xs" title="退出登录">🚪</button>
        </div>
        {user && (
          <div className="mt-2 flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center text-[10px] font-bold text-white">
              {(user.username || '?')[0].toUpperCase()}
            </div>
            <span className="text-[11px] text-slate-400 truncate">{user.username}</span>
          </div>
        )}
      </div>

      <div className="px-4 py-4 border-b border-slate-700/60">
        <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2 font-semibold">运行模式</p>
        <div className="flex rounded-lg bg-slate-800/60 p-1 border border-slate-700/40 gap-1">
          <button
            onClick={() => onModeChange('query')}
            className={`flex-1 py-1.5 px-2 text-xs rounded-md transition-all duration-200 font-medium ${
              mode === 'query' ? 'bg-emerald-500/20 text-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.3)]' : 'text-slate-400 hover:text-slate-300'
            }`}
          >
            🗣️ 探求
          </button>
          <button
            onClick={() => onModeChange('forge')}
            className={`flex-1 py-1.5 px-2 text-xs rounded-md transition-all duration-200 font-medium ${
              mode === 'forge' ? 'bg-cyan-500/20 text-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.3)]' : 'text-slate-400 hover:text-slate-300'
            }`}
          >
            🕸️ 织网
          </button>
          <button
            onClick={() => onModeChange('report')}
            className={`flex-1 py-1.5 px-2 text-xs rounded-md transition-all duration-200 font-medium ${
              mode === 'report' ? 'bg-purple-500/20 text-purple-400 shadow-[0_0_8px_rgba(168,85,247,0.3)]' : 'text-slate-400 hover:text-slate-300'
            }`}
          >
            📊 报告
          </button>
        </div>
      </div>

      <div className="flex-1 px-4 py-4 overflow-hidden">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold flex items-center gap-2">
            工作区沙箱
            <button
              onClick={handleCreateSandbox}
              className="text-cyan-400 hover:text-cyan-300 bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5 rounded transition-colors text-[9px] border border-slate-600/50"
            >
              + 新建
            </button>
          </p>
          <span className="text-[9px] text-emerald-500/80 font-mono">{sandboxes.length} active</span>
        </div>
        <div className="space-y-1.5 overflow-y-auto max-h-full scrollbar-thin pb-10">
          {sandboxes.map((sb) => (
            <button
              key={sb.id}
              onClick={() => onSandboxSelect(sb.id === selectedSandbox ? null : sb.id)}
              className={`w-full text-left px-3 py-3 rounded-lg border transition-all duration-200 group ${
                sb.id === selectedSandbox
                  ? 'bg-slate-700/40 border-cyan-500/40 glow-cyan'
                  : 'bg-slate-800/30 border-slate-700/30 hover:border-slate-600/50 hover:bg-slate-800/50'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`text-xs font-mono font-medium truncate pr-2 ${
                  sb.id === selectedSandbox ? 'text-cyan-300' : 'text-slate-300'
                }`}>
                  {sb.name}
                </span>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    onClick={(e) => handleDeleteSandbox(sb.id, e)}
                    className="opacity-0 group-hover:opacity-100 text-[10px] text-red-500/60 hover:text-red-400 transition-all duration-200 p-0.5"
                    title="删除沙箱"
                  >
                    🗑️
                  </button>
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    sb.id === selectedSandbox ? 'bg-cyan-400 animate-pulse shadow-[0_0_5px_rgba(34,211,238,0.8)]' : 'bg-slate-500'
                  }`} />
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="px-4 py-3 border-t border-slate-700/60">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-[10px] text-slate-500 font-mono">v0.2.0 · Online</span>
        </div>
        <div className="mt-3 pt-3 border-t border-slate-800/60 flex items-center gap-3">
          {onOpenAdmin && (
            <button onClick={onOpenAdmin} className="flex items-center gap-2 text-amber-500/70 hover:text-amber-400 transition-colors text-xs">
              <span className="text-sm">🔍</span>
              <span className="font-mono tracking-wider uppercase">Monitor</span>
            </button>
          )}
          <button onClick={onOpenSettings} className="flex items-center gap-2 text-slate-500 hover:text-slate-300 transition-colors text-xs">
            <span className="text-sm hover:rotate-45 transition-transform duration-300">⚙️</span>
            <span className="font-mono tracking-wider uppercase">Settings</span>
          </button>
          {selectedSandbox && (
            <button onClick={onOpenSessions} className="flex items-center gap-2 text-slate-500 hover:text-slate-300 transition-colors text-xs">
              <span className="text-sm">📜</span>
              <span className="font-mono tracking-wider uppercase">History</span>
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}
