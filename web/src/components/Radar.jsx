import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function Radar({ selectedSandbox }) {
  const { apiFetch } = useAuth()
  const [blackholes, setBlackholes] = useState([])
  const [loading, setLoading] = useState(false)

  const fetchRadar = () => {
    if (!selectedSandbox) return
    setLoading(true)
    apiFetch(`/api/radar?workspace=${selectedSandbox}`)
      .then(res => res.json())
      .then(data => setBlackholes(data))
      .catch(err => console.error("Radar 扫描失败", err))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchRadar()
    const handleKbUpdate = () => fetchRadar()
    window.addEventListener('KB_PHYSICAL_UPDATE', handleKbUpdate)
    return () => window.removeEventListener('KB_PHYSICAL_UPDATE', handleKbUpdate)
  }, [selectedSandbox])

  if (!selectedSandbox) {
    return <div className="text-xs text-slate-600 font-mono italic p-2">RADAR OFFLINE. ANCHOR REQUIRED.</div>
  }

  return (
    <div className="space-y-3 p-1">
      {loading && blackholes.length === 0 ? (
        <div className="text-xs text-emerald-500/50 font-mono animate-pulse p-2">SWEEPING TOPOLOGY GRAPH...</div>
      ) : blackholes.length === 0 ? (
        <div className="p-2 space-y-1">
          <div className="text-xs text-emerald-400 font-mono">✅ 拓扑结构极度健康</div>
          <div className="text-[10px] text-slate-500">当前沙箱未探测到高频断链，无需填补黑洞。</div>
        </div>
      ) : (
        <>
          {blackholes.map((hole, idx) => {
            const isCritical = hole.urgency >= 60;
            return (
              <div key={idx} className="space-y-1.5 group">
                <div className="flex justify-between items-end">
                  <span className={`text-[11px] font-mono font-medium transition-colors ${
                    isCritical ? 'text-red-400 group-hover:text-red-300' : 'text-slate-300 group-hover:text-emerald-300'
                  }`}>
                    {hole.concept}
                    {isCritical && <span className="ml-2 text-[9px] text-red-500 animate-pulse">⚠️ 亟待填补</span>}
                  </span>
                  <span className="text-[9px] font-mono text-slate-500">
                    引力: <span className={isCritical ? "text-red-500 font-bold" : "text-emerald-400"}>{hole.mentions}</span>
                  </span>
                </div>
                <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ease-out relative overflow-hidden bg-gradient-to-r ${
                      isCritical ? 'from-red-600 to-red-400' : 'from-emerald-600 to-emerald-400'
                    }`}
                    style={{ width: `${hole.urgency}%` }}
                  >
                    <div className="absolute top-0 bottom-0 left-0 right-0 bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full animate-[shimmer_2s_infinite]" />
                  </div>
                </div>
              </div>
            );
          })}
          <div className="pt-2 text-[9px] text-slate-500 font-mono border-t border-slate-800/60 flex justify-between">
            <span>* 点击控制台 [填补黑洞] 即可进行实例化</span>
          </div>
        </>
      )}
    </div>
  )
}
