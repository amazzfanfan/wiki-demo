import { useState } from 'react'
import ForceGraph from './ForceGraph'
import CyberForge from './CyberForge'
import Inbox from './Inbox'
import Radar from './Radar'
import AuditLog from './AuditLog'

export default function ForgeMode({ selectedSandbox }) {
  const [selectedNode, setSelectedNode] = useState(null)
  const [forgeLogs, setForgeLogs] = useState([
    { text: "🟢 赛博织网系统控制台就绪。等候熔炉指令..." }
  ])

  // 💡 核心新增：星图核爆触发器。每次数字改变，左侧星图就会销毁重建！
  const [graphKey, setGraphKey] = useState(0)
  const triggerGraphRefresh = () => setGraphKey(prev => prev + 1)

  return (
    <div className="flex h-full bg-slate-900">
      {/* 左侧 70%: 星图画布 */}
      <div className="w-[70%] relative border-r border-slate-800">
        <ForceGraph
          key={`graph-${selectedSandbox}-${graphKey}`} // 💡 注入引爆器
          selectedSandbox={selectedSandbox}
          onNodeClick={setSelectedNode}
          selectedNode={selectedNode}
        />
        {selectedNode && (
          <div className="absolute top-4 left-4 glass rounded-xl px-4 py-2 animate-fade-in z-20 bg-slate-900/80 border border-slate-700/50 backdrop-blur-md">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              <span className="text-sm text-cyan-300 font-mono font-medium">{selectedNode}</span>
              <button onClick={() => setSelectedNode(null)} className="ml-2 text-slate-500 hover:text-slate-300 text-xs">✕</button>
            </div>
          </div>
        )}
      </div>

      {/* 右侧 30%: 控制台 */}
      <div className="w-[30%] h-full flex flex-col bg-slate-950/40 overflow-y-auto p-4 space-y-6 scrollbar-thin">

        {/* CyberForge 摄入流 */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 shadow-xl backdrop-blur-md">
          <div className="text-xs font-semibold text-cyan-400 uppercase tracking-wider mb-3 flex items-center gap-2 font-mono">
            <span>☁️</span> CYBER FORGE / INGEST STREAM
          </div>
          <CyberForge selectedSandbox={selectedSandbox} setForgeLogs={setForgeLogs} />
        </div>

        {/* 💡 Inbox 审批区 (传入引爆器) */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 shadow-xl backdrop-blur-md">
          <div className="text-xs font-semibold text-yellow-500 uppercase tracking-wider mb-3 flex items-center gap-2 font-mono">
            <span>✅</span> ISOLATION APPROVAL / INBOX
          </div>
          <Inbox selectedSandbox={selectedSandbox} onGraphRefresh={triggerGraphRefresh} />
        </div>

        {/* 💡 Radar 需求雷达 */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 shadow-xl backdrop-blur-md">
          <div className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-3 flex items-center gap-2 font-mono">
            <span>📡</span> REQUIREMENT RADAR / RADAR
          </div>
          <Radar selectedSandbox={selectedSandbox} />
        </div>

        {/* Audit Log 日志 */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 shadow-xl backdrop-blur-md flex-1 min-h-[280px] flex flex-col">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2 font-mono">
            <span>📜</span> WEAVING ARCHIVE / AUDIT LOG
          </div>
          <div className="flex-1 bg-slate-950/90 rounded-lg p-3 font-mono text-[11px] border border-slate-800 overflow-y-auto max-h-[350px]">
            <AuditLog logs={forgeLogs} />
          </div>
        </div>

      </div>
    </div>
  )
}