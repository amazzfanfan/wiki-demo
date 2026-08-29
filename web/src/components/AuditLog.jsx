import { useEffect, useRef } from 'react'

export default function AuditLog({ logs }) {
  const logEndRef = useRef(null)

  // 自动平滑滚动到最新一条熔炉进度日志
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  if (!logs || logs.length === 0) {
    return <div className="text-slate-600 italic">暂无熔炉运行记录。</div>
  }

  return (
    <div className="space-y-1.5 flex flex-col h-full select-text">
      {logs.map((log, index) => {
        // 根据日志的前缀特征动态渲染有质感的赛博颜色
        let textColor = 'text-emerald-400'
        if (log.text.startsWith('❌') || log.text.startsWith('💥')) textColor = 'text-red-400 font-semibold'
        if (log.text.startsWith('⚠️') || log.text.startsWith('🚨')) textColor = 'text-amber-400'
        if (log.text.startsWith('🚀') || log.text.startsWith('🔥')) textColor = 'text-cyan-400 font-medium'
        if (log.text.startsWith('  ->')) textColor = 'text-slate-400 pl-2'

        return (
          <div key={index} className={`whitespace-pre-wrap leading-relaxed ${textColor}`}>
            {log.text}
          </div>
        )
      })}
      <div ref={logEndRef} />
    </div>
  )
}