import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function Settings({ onClose }) {
  const { apiFetch } = useAuth()
  const [providers, setProviders] = useState([])
  const [selectedProvider, setSelectedProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelId, setModelId] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => { fetchProviders() }, [])

  const fetchProviders = async () => {
    try {
      const res = await apiFetch('/api/settings/providers')
      const data = await res.json()
      setProviders(data)
    } catch (err) {
      console.error('fetch providers error:', err)
    }
  }

  const handleSelectProvider = (p) => {
    setSelectedProvider(p.id)
    setBaseUrl(p.base_url || '')
    setModelId(p.default_model || '')
    setApiKey('')
    setMessage('')
    if (p.user_config) {
      setBaseUrl(p.user_config.base_url || p.base_url || '')
      setModelId(p.user_config.model_id || p.default_model || '')
    }
  }

  const handleSave = async () => {
    if (!apiKey.trim()) { setMessage('please enter API Key'); return }
    setSaving(true)
    setMessage('')
    try {
      const res = await apiFetch('/api/settings/api-key', {
        method: 'POST',
        body: JSON.stringify({
          provider: selectedProvider,
          api_key: apiKey.trim(),
          base_url: baseUrl.trim(),
          model_id: modelId.trim(),
        }),
      })
      if (!res.ok) throw new Error('save failed')
      setMessage('saved!')
      setApiKey('')
      fetchProviders()
    } catch (err) {
      setMessage('error: ' + err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    if (!selectedProvider) return
    setSaving(true)
    setMessage('')
    try {
      const res = await apiFetch(`/api/settings/api-key/${selectedProvider}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error('clear failed')
      setMessage('cleared! using system default')
      setApiKey('')
      fetchProviders()
    } catch (err) {
      setMessage('error: ' + err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-slate-900/95 border border-slate-700/50 rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col shadow-2xl">
        <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            <span>⚙️</span> 系统设置
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors text-xl">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
            <span>🔑</span> 模型 API Key 管理
          </h3>

          <div className="grid grid-cols-2 gap-2 mb-6">
            {providers.map(p => (
              <button
                key={p.id}
                onClick={() => handleSelectProvider(p)}
                className={`text-left px-4 py-3 rounded-lg border transition-all ${
                  selectedProvider === p.id
                    ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                    : 'bg-slate-800/40 border-slate-700/30 text-slate-300 hover:border-slate-600/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{p.name}</span>
                  {p.configured && <span className="text-[10px] text-emerald-400">✅</span>}
                </div>
                {p.user_config && (
                  <p className="text-[10px] text-slate-500 mt-1 font-mono truncate">
                    {p.user_config.api_key_preview || '***'}
                  </p>
                )}
              </button>
            ))}
          </div>

          {selectedProvider && (
            <div className="space-y-3 bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
              <div>
                <label className="text-[10px] text-slate-400 uppercase tracking-wider font-mono mb-1 block">API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  placeholder="输入新的 API Key"
                  className="w-full bg-slate-800/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-slate-400 uppercase tracking-wider font-mono mb-1 block">Base URL</label>
                  <input
                    type="text"
                    value={baseUrl}
                    onChange={e => setBaseUrl(e.target.value)}
                    placeholder="https://..."
                    className="w-full bg-slate-800/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 text-sm"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-slate-400 uppercase tracking-wider font-mono mb-1 block">Model ID</label>
                  <input
                    type="text"
                    value={modelId}
                    onChange={e => setModelId(e.target.value)}
                    placeholder="model name"
                    className="w-full bg-slate-800/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 text-sm"
                  />
                </div>
              </div>
              {message && (
                <p className={`text-xs ${message.startsWith('saved') ? 'text-emerald-400' : 'text-red-400'}`}>{message}</p>
              )}
              <div className="flex gap-2">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-4 py-2 rounded-lg text-xs font-medium bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white transition-all disabled:opacity-50"
                >
                  {saving ? 'Saving...' : '💾 Save'}
                </button>
                {selectedProvider && providers.find(p => p.id === selectedProvider)?.configured && (
                  <button
                    onClick={handleClear}
                    disabled={saving}
                    className="px-4 py-2 rounded-lg text-xs font-medium bg-slate-700/60 hover:bg-red-600/30 text-slate-300 hover:text-red-300 border border-slate-600/40 hover:border-red-500/40 transition-all disabled:opacity-50"
                  >
                    🗑️ Clear
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
