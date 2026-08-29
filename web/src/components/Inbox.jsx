import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function Inbox({ selectedSandbox }) {
  const { apiFetch } = useAuth()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [editingFile, setEditingFile] = useState(null)
  const [isSaving, setIsSaving] = useState(false)

  const fetchInbox = () => {
    if (!selectedSandbox) return
    setLoading(true)
    apiFetch(`/api/inbox?workspace=${selectedSandbox}`)
      .then(res => res.json())
      .then(data => setItems(data))
      .catch(err => console.error("Inbox 扫描失败", err))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchInbox()
    const handleKbUpdate = () => fetchInbox()
    window.addEventListener('KB_PHYSICAL_UPDATE', handleKbUpdate)
    return () => window.removeEventListener('KB_PHYSICAL_UPDATE', handleKbUpdate)
  }, [selectedSandbox])

  const handleApprove = (fileId) => {
    apiFetch(`/api/inbox/approve?workspace=${selectedSandbox}&file_id=${fileId}`, { method: 'POST' })
      .then(res => res.json())
      .then(() => {
        window.dispatchEvent(new CustomEvent('KB_PHYSICAL_UPDATE')) // 鸣枪刷新
      })
  }

  const handleDelete = (fileId) => {
    apiFetch(`/api/inbox/file?workspace=${selectedSandbox}&file_id=${fileId}`, { method: 'DELETE' })
      .then(res => res.json())
      .then(() => {
        window.dispatchEvent(new CustomEvent('KB_PHYSICAL_UPDATE')) // 鸣枪刷新
      })
  }

  const handleEditClick = (fileId) => {
    apiFetch(`/api/inbox/file?workspace=${selectedSandbox}&file_id=${fileId}`)
      .then(res => res.json())
      .then(data => setEditingFile({ id: fileId, content: data.content }))
  }

  const handleSaveEdit = () => {
    if (!editingFile) return
    setIsSaving(true)
    apiFetch(`/api/inbox/file`, {
      method: 'PUT',
      body: JSON.stringify({
        workspace: selectedSandbox,
        file_id: editingFile.id,
        content: editingFile.content
      })
    })
      .then(res => res.json())
      .then(() => {
        setEditingFile(null)
        window.dispatchEvent(new CustomEvent('KB_PHYSICAL_UPDATE')) // 鸣枪刷新
      })
      .finally(() => setIsSaving(false))
  }

  if (!selectedSandbox) return <div className="text-xs text-slate-600 font-mono italic p-2">INBOX OFFLINE.</div>

  if (editingFile) {
    return (
      <div className="p-2 space-y-2 flex flex-col h-full">
        <div className="flex justify-between items-center text-xs font-mono text-amber-400">
          <span>📝 正在干预: {editingFile.id}</span>
          <button onClick={() => setEditingFile(null)} className="text-slate-500 hover:text-slate-300">[返回]</button>
        </div>
        <textarea
          className="flex-1 w-full bg-slate-900/50 border border-slate-700 rounded p-2 text-xs text-slate-300 font-mono resize-none focus:outline-none focus:border-amber-500/50"
          value={editingFile.content}
          onChange={(e) => setEditingFile({ ...editingFile, content: e.target.value })}
        />
        <button
          onClick={handleSaveEdit}
          disabled={isSaving}
          className="w-full py-1.5 bg-amber-500/20 text-amber-400 border border-amber-500/50 hover:bg-amber-500/30 rounded text-xs font-mono disabled:opacity-50"
        >
          {isSaving ? 'SAVING...' : '💾 保存修改并放行'}
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-2 p-1">
      <div className="flex justify-between items-center px-1">
        <span className="text-[10px] text-slate-500 font-mono">{items.length} pending</span>
        <button onClick={fetchInbox} className="text-[10px] text-slate-500 hover:text-amber-400 font-mono">[🔄 refresh]</button>
      </div>
      {loading && items.length === 0 ? (
        <div className="text-xs text-amber-500/50 font-mono animate-pulse p-2">SCANNING INBOX...</div>
      ) : items.length === 0 ? (
        <div className="p-2"><div className="text-xs text-slate-400 font-mono">📥 隔离区当前为空</div></div>
      ) : (
        items.map((item, idx) => (
          <div key={idx} className="p-2 border border-slate-700/50 rounded bg-slate-800/20 group hover:border-amber-500/30 transition-colors">
            <div className="flex justify-between items-start mb-1">
              <span className="text-xs font-mono text-amber-400 font-bold">{item.title}</span>
              <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => handleEditClick(item.id)} className="text-[10px] text-blue-400 hover:text-blue-300">[✏️]</button>
                <button onClick={() => handleApprove(item.id)} className="text-[10px] text-emerald-400 hover:text-emerald-300">[✓]</button>
                <button onClick={() => handleDelete(item.id)} className="text-[10px] text-red-400 hover:text-red-300">[✕]</button>
              </div>
            </div>
            <div className="text-[10px] text-slate-400 line-clamp-2 leading-relaxed">{item.excerpt}</div>
          </div>
        ))
      )}
    </div>
  )
}
