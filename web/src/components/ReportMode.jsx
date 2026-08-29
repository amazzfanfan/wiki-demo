import { useState, useRef, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export default function ReportMode({ selectedSandbox, onBack }) {
  const { apiFetch } = useAuth()
  const [topic, setTopic] = useState('')
  const [outline, setOutline] = useState('')
  const [report, setReport] = useState('')
  const [logs, setLogs] = useState([])
  const [generating, setGenerating] = useState(false)
  const abortRef = useRef(null)
  const reportEndRef = useRef(null)

  useEffect(() => {
    reportEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [report, logs])

  const handleGenerate = async () => {
    if (!topic.trim()) return alert('请输入报告主题')
    if (!selectedSandbox) return alert('请先选择工作区')

    setReport('')
    setLogs([])
    setGenerating(true)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const res = await apiFetch('/api/report', {
        method: 'POST',
        body: JSON.stringify({
          topic: topic.trim(),
          workspace: selectedSandbox,
          outline: outline.trim(),
        }),
        signal: ctrl.signal,
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'text') {
              setReport(prev => prev + data.content)
            } else if (data.type === 'log') {
              setLogs(prev => [...prev.slice(-30), data.content])
            } else if (data.type === 'done') {
              setGenerating(false)
            }
          } catch {}
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setLogs(prev => [...prev, `❌ ${err.message}`])
      }
    } finally {
      setGenerating(false)
    }
  }

  const handleStop = () => {
    abortRef.current?.abort()
    setGenerating(false)
  }

  const handleExport = () => {
    if (!report) return
    const blob = new Blob([`# ${topic}\n\n${report}`], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${topic.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_')}_report.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="h-full flex flex-col bg-slate-900">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-slate-500 hover:text-slate-300 transition-colors">
            ← 返回
          </button>
          <h2 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            <span>📊</span> 深度报告生成
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {report && !generating && (
            <button
              onClick={handleExport}
              className="px-3 py-1.5 rounded-lg text-xs bg-slate-700/50 text-slate-300 hover:bg-slate-600/50 transition-colors"
            >
              📥 导出 Markdown
            </button>
          )}
        </div>
      </div>

      {/* Control Panel */}
      <div className="px-6 py-4 border-b border-slate-700/30 bg-slate-800/30">
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-[10px] text-slate-400 uppercase tracking-wider font-mono mb-1 block">报告主题</label>
            <input
              type="text"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="输入你要深入研究的主题..."
              className="w-full bg-slate-800/60 border border-slate-600/40 rounded-lg px-4 py-2.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 text-sm"
              disabled={generating}
            />
          </div>
          {generating ? (
            <button
              onClick={handleStop}
              className="px-5 py-2.5 rounded-lg text-sm font-medium bg-red-600/20 text-red-400 border border-red-500/30 hover:bg-red-600/30 transition-all"
            >
              ⏹️ 停止
            </button>
          ) : (
            <button
              onClick={handleGenerate}
              disabled={!topic.trim()}
              className="px-5 py-2.5 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white transition-all disabled:opacity-40 shadow-lg shadow-emerald-500/10"
            >
              🚀 生成报告
            </button>
          )}
        </div>

        {/* Optional Outline */}
        <details className="mt-3">
          <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-400 transition-colors">
            📋 自定义大纲 (可选)
          </summary>
          <textarea
            value={outline}
            onChange={e => setOutline(e.target.value)}
            placeholder="输入自定义大纲，每行一个章节名..."
            className="mt-2 w-full h-20 bg-slate-800/40 border border-slate-700/30 rounded-lg px-3 py-2 text-slate-300 placeholder-slate-600 focus:outline-none focus:border-emerald-500/30 text-xs resize-none"
            disabled={generating}
          />
        </details>
      </div>

      {/* Content Area: 70% report / 30% logs */}
      <div className="flex-1 flex overflow-hidden">
        {/* Report */}
        <div className="flex-1 overflow-y-auto px-8 py-6 prose prose-invert prose-sm max-w-none">
          {report ? (
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
              {report}
            </ReactMarkdown>
          ) : generating ? (
            <div className="text-center text-slate-500 py-12">
              <div className="text-4xl mb-3 animate-bounce">📝</div>
              <p className="text-sm">正在生成报告...</p>
            </div>
          ) : (
            <div className="text-center text-slate-600 py-12">
              <div className="text-5xl mb-4">📊</div>
              <p className="text-sm">输入主题，一键生成深度研究报告</p>
              <p className="text-xs text-slate-700 mt-2">自动检索本地知识 + 联网资料，逐章节合成</p>
            </div>
          )}
          <div ref={reportEndRef} />
        </div>

        {/* Logs */}
        {logs.length > 0 && (
          <div className="w-72 border-l border-slate-700/30 bg-slate-950/50 overflow-y-auto p-3">
            <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2 font-semibold">合成日志</p>
            <div className="space-y-1">
              {logs.map((log, i) => (
                <p key={i} className="text-[10px] text-slate-500 font-mono leading-relaxed">
                  {log}
                </p>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
