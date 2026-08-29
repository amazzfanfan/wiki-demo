import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { useAuth } from '../contexts/AuthContext'

// react-markdown 插件列表
const remarkPlugins = [remarkGfm, remarkMath]
const rehypePlugins = [rehypeKatex]

// 自定义渲染组件
const mdComponents = {
  a: ({ href, children, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  ),
  img: ({ src, alt, ...props }) => (
    <img
      src={src}
      alt={alt || ''}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="max-w-full h-auto rounded-lg my-2 border border-slate-700/50 shadow-sm"
      {...props}
    />
  ),
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-3">
      <table className="min-w-full text-sm border-collapse" {...props}>{children}</table>
    </div>
  ),
  th: ({ children, ...props }) => (
    <th className="border border-slate-600 bg-slate-800/60 px-3 py-1.5 text-left text-slate-300 font-semibold" {...props}>{children}</th>
  ),
  td: ({ children, ...props }) => (
    <td className="border border-slate-700/50 px-3 py-1.5 text-slate-300" {...props}>{children}</td>
  ),
  code: ({ className, children, ...props }) => {
    const isBlock = className?.startsWith('language-')
    if (isBlock) {
      return (
        <pre className="bg-slate-900 border border-slate-700 rounded-lg p-3 overflow-x-auto my-2">
          <code className={className} {...props}>{children}</code>
        </pre>
      )
    }
    return (
      <code className="bg-slate-700/40 px-1.5 py-0.5 rounded text-emerald-300 text-xs" {...props}>{children}</code>
    )
  }
}

export default function QueryMode({ selectedSandbox, sessionId }) {
  const { apiFetch } = useAuth()
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [isTyping, setIsTyping] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [webSearchEnabled, setWebSearchEnabled] = useState(null) // null=自动, true=强制联网, false=仅本地
  const messagesEndRef = useRef(null)
  const prevSessionIdRef = useRef(null)

  // 💡 核心会话隔离：切换沙箱时重置对话（但跳过因加载历史会话触发的重渲染）
  useEffect(() => {
    // 如果正在加载历史，不要清空消息
    if (isLoadingHistory) return
    // 如果 sessionId 刚变化（正在切换会话），也不要清空
    if (prevSessionIdRef.current !== sessionId) return
    setMessages([])
    setInput('')
  }, [selectedSandbox])

  // 📥 加载历史会话消息
  useEffect(() => {
    if (!sessionId) {
      prevSessionIdRef.current = null
      return
    }
    // 同一个 sessionId 不重复加载
    if (prevSessionIdRef.current === sessionId) return
    prevSessionIdRef.current = sessionId

    let cancelled = false
    setIsLoadingHistory(true)

    const loadHistory = async () => {
      try {
        const res = await apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`)
        if (cancelled) return
        if (!res.ok) {
          setMessages([])
          return
        }
        const data = await res.json()
        if (cancelled) return
        const loaded = (data.messages || []).map(m => ({
          role: m.role,
          content: m.content,
          logs: []
        }))
        setMessages(loaded)
      } catch (e) {
        if (!cancelled) {
          console.error('load session history error:', e)
          setMessages([])
        }
      } finally {
        if (!cancelled) setIsLoadingHistory(false)
      }
    }
    loadHistory()
    return () => { cancelled = true }
  }, [sessionId])

  // 自动平滑滚动到最新消息
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const handleSend = async () => {
    if (!input.trim() || isTyping) return

    const currentInput = input.trim()
    const userMsg = { role: 'user', content: currentInput }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setIsTyping(true)

    // 初始化 AI 气泡与思维轨迹日志数组
    const assistantMsg = { role: 'assistant', content: '', logs: [] }
    setMessages(prev => [...prev, assistantMsg])

    // 💡 记忆提纯：在发送前提取当前的有效聊天记录，过滤掉报错和空信息
    const chatHistory = messages
      .filter(m => m.role && m.content && !m.content.includes('❌'))
      .map(m => ({ role: m.role, content: m.content }))

    try {
      // 🚀 双端连接：将问题、当前隔离区沙箱标识、历史上下文捆绑发往后端
      const response = await apiFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          query: currentInput,
          workspace: selectedSandbox || "",
          history: chatHistory,
          web_search_enabled: webSearchEnabled
        })
      })

      if (!response.ok) throw new Error(`HTTP 错误! 状态码: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      // 💡 工业级防线：声明数据流缓冲区，完美解决网络碎片折断 JSON 的问题
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()

        if (value) {
          buffer += decoder.decode(value, { stream: true })
        }

        const parts = buffer.split('\n\n')

        // 如果流未结束，最后一个包可能不完整，弹出并留到下一轮循环拼接
        if (!done) {
          buffer = parts.pop() || ''
        }

        for (const line of parts) {
          if (line.startsWith('data: ')) {
            const dataStr = line.replace('data: ', '')
            if (!dataStr.trim()) continue

            try {
              const data = JSON.parse(dataStr)

              if (data.type === 'log') {
                setMessages(prev => {
                  const newMsgs = [...prev]
                  const lastIdx = newMsgs.length - 1
                  newMsgs[lastIdx] = {
                    ...newMsgs[lastIdx],
                    logs: [...(newMsgs[lastIdx].logs || []), { text: data.content }]
                  }
                  return newMsgs
                })
              } else if (data.type === 'text') {
                setMessages(prev => {
                  const newMsgs = [...prev]
                  const lastIdx = newMsgs.length - 1
                  newMsgs[lastIdx] = {
                    ...newMsgs[lastIdx],
                    content: newMsgs[lastIdx].content + data.content
                  }
                  return newMsgs
                })
              } else if (data.type === 'error') {
                setMessages(prev => {
                  const newMsgs = [...prev]
                  const lastIdx = newMsgs.length - 1
                  newMsgs[lastIdx] = {
                    ...newMsgs[lastIdx],
                    content: data.content,
                    isError: true
                  }
                  return newMsgs
                })
              }
            } catch (err) {
              console.warn("解析 SSE 数据包失败:", dataStr, err)
            }
          }
        }

        if (done) break
      }
    } catch (e) {
      console.error("流式通信断开:", e)
      setMessages(prev => {
        const newMsgs = [...prev]
        const lastIdx = newMsgs.length - 1
        newMsgs[lastIdx] = {
          ...newMsgs[lastIdx],
          content: "❌ 链路发生严重故障，无法获取本地知识引擎响应，请检查后端网关状态。"
        }
        return newMsgs
      })
    } finally {
      setIsTyping(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-slate-900 relative">
      {/* 沙箱隔离雷达指示器 */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 px-4 py-1.5 rounded-full bg-slate-800/90 border border-slate-700/60 backdrop-blur-sm flex items-center gap-2 shadow-lg">
        <div className={`w-2 h-2 rounded-full ${selectedSandbox ? 'bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.6)]' : 'bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.6)]'}`}></div>
        <span className="text-xs font-mono text-slate-300">
          {selectedSandbox ? `[隔离区激活] 正在定向检索: ${selectedSandbox}` : '[全局漫游] 广域知识检索'}
        </span>
      </div>

      {/* 消息历史画布 */}
      <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 scrollbar-thin pt-16">
        {isLoadingHistory ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 font-mono space-y-3">
            <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-400 rounded-full animate-spin" />
            <p className="text-sm animate-pulse">正在加载会话记录...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 font-mono space-y-2">
            <span className="text-3xl animate-bounce">🗣️</span>
            <p className="text-sm">知识库探求中心已就绪，请输入你的提问...</p>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div key={idx} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              {msg.role === 'user' ? (
                <div className="max-w-[80%] bg-slate-800 border border-slate-700/60 rounded-2xl px-4 py-3 text-slate-200 text-sm shadow-md">
                  {msg.content}
                </div>
              ) : (
                <div className="max-w-[85%] w-full space-y-3">
                  {/* 物理思维轨迹 (Terminal 日志推流) */}
                  {msg.logs && msg.logs.length > 0 && (
                    <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-3 font-mono text-[11px] text-slate-400 max-h-[160px] overflow-y-auto space-y-1 shadow-inner">
                      <p className="text-[10px] text-cyan-500/80 border-b border-slate-800/60 pb-1 mb-1 font-semibold uppercase tracking-wider">⚡ Thinking Process & Action Stream</p>
                      {msg.logs.map((log, lIdx) => (
                        <div key={lIdx} className="text-emerald-400/90 whitespace-pre-wrap">{log.text}</div>
                      ))}
                    </div>
                  )}

                  {/* 回答正文气泡 */}
                  {msg.content && (
                    <div className={`rounded-2xl px-5 py-4 text-sm shadow-sm leading-relaxed ${
                      msg.isError
                        ? 'bg-red-500/10 border border-red-500/30 text-red-200'
                        : 'bg-slate-800/40 border border-slate-800/60 text-slate-200'
                    }`}>
                      <div className="prose prose-invert max-w-none prose-sm prose-a:text-cyan-400 hover:prose-a:text-cyan-300">
                        <ReactMarkdown
                          remarkPlugins={remarkPlugins}
                          rehypePlugins={rehypePlugins}
                          components={mdComponents}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {/* 打字机加载状态 */}
        {isTyping && messages[messages.length - 1]?.content === '' && (
          <div className="flex items-center gap-1.5 px-4 text-xs text-slate-500 font-mono">
            <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-bounce [animation-delay:-0.3s]"></span>
            <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-bounce [animation-delay:-0.15s]"></span>
            <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-bounce"></span>
            <span className="ml-1">本地知识引擎正在提取并解析文件实体...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 底部指令输入台 */}
      <div className="p-4 bg-slate-950/40 border-t border-slate-800/80 backdrop-blur-md">
        {/* 联网搜索开关 */}
        <div className="max-w-4xl mx-auto flex items-center gap-3 mb-2 px-1">
          <span className="text-xs text-slate-500 font-mono">🌐 联网搜索</span>
          <button
            onClick={() => setWebSearchEnabled(prev => prev === null ? true : prev === true ? false : null)}
            className={`px-3 py-1 rounded-md text-xs font-mono font-semibold transition-all duration-200 border ${
              webSearchEnabled === true
                ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300 shadow-[0_0_6px_rgba(34,211,238,0.15)]'
                : webSearchEnabled === false
                ? 'bg-slate-800/60 border-slate-700/50 text-slate-500'
                : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
            }`}
          >
            {webSearchEnabled === true ? '强制联网' :
             webSearchEnabled === false ? '仅本地' :
             '自动决策'}
          </button>
        </div>
        <div className="max-w-4xl mx-auto flex gap-2 bg-slate-900 border border-slate-700/50 rounded-xl p-1.5 focus-within:border-cyan-500/50 transition-all duration-200 shadow-lg">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder={selectedSandbox ? `在 [${selectedSandbox}] 隔离区中发起深度探求...` : "向所有知识库广域探求..."}
            className="flex-1 bg-transparent text-slate-200 text-sm px-3 focus:outline-none placeholder-slate-500"
            disabled={isTyping}
          />
          <button
            onClick={handleSend}
            disabled={isTyping || !input.trim()}
            className={`px-4 py-2 rounded-lg text-xs font-mono font-semibold transition-all duration-200 ${
              isTyping || !input.trim()
                ? 'bg-slate-800 text-slate-600 cursor-not-allowed'
                : 'bg-gradient-to-r from-emerald-500 to-cyan-500 text-slate-950 shadow-[0_0_10px_rgba(34,211,238,0.2)] hover:opacity-90'
            }`}
          >
            {isTyping ? "RUNNING" : "EXECUTE"}
          </button>
        </div>
      </div>
    </div>
  )
}
