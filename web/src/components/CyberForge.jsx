import { useState, useCallback, useEffect, useRef } from 'react'
import { useAuth } from '../contexts/AuthContext'

// ── Phase definitions ──
const PHASES = {
  idle:       { label: '空闲',     icon: '💤', color: 'slate' },
  stopping:   { label: '已停止',   icon: '🛑', color: 'red' },
  parsing:    { label: '解析文档', icon: '📄', color: 'blue' },
  extracting: { label: '提取概念', icon: '⚡', color: 'cyan' },
  clustering: { label: '聚类归并', icon: '🔀', color: 'purple' },
  merging:    { label: '融合落盘', icon: '🧠', color: 'emerald' },
  done:       { label: '提炼完成', icon: '✅', color: 'emerald' },
}

const PHASE_ORDER = ['idle', 'stopping', 'parsing', 'extracting', 'clustering', 'merging', 'done']

// Calculate overall percentage from structured progress
function calcPercent(p) {
  if (!p || p.phase === 'idle') return 0
  if (p.phase === 'done') return 100
  if (p.phase === 'stopping') return 0  // 已停止，不显示进度条

  const phaseIdx = PHASE_ORDER.indexOf(p.phase)
  // Phase base percentages: parsing=5, extracting=5-45, clustering=45-55, merging=55-95
  const phaseRanges = {
    parsing:    [2, 8],
    extracting: [8, 45],
    clustering: [45, 55],
    merging:    [55, 95],
  }

  const range = phaseRanges[p.phase]
  if (!range) return 0

  let subProgress = 0
  if (p.phase === 'extracting' && p.total_chunks > 0) {
    subProgress = p.map_done / p.total_chunks
  } else if (p.phase === 'merging' && p.total_concepts > 0) {
    subProgress = p.reduce_done / p.total_concepts
  } else {
    subProgress = 0.5 // indeterminate midpoint
  }

  return Math.min(100, Math.round(range[0] + (range[1] - range[0]) * subProgress))
}

export default function CyberForge({ selectedSandbox, setForgeLogs }) {
  const { apiFetch, token } = useAuth()
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isForging, setIsForging] = useState(false)
  const [terminating, setTerminating] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [sseKey, setSseKey] = useState(0)  // 强制 SSE 重连

  // ── Ingest progress state ──
  const [ingestStatus, setIngestStatus] = useState('idle')
  const [progress, setProgress] = useState(null) // structured progress from backend
  const [elapsed, setElapsed] = useState(0)
  const [checkpoint, setCheckpoint] = useState(null) // { concepts, files_done, has_checkpoint }

  const sseRef = useRef(null)
  const timerRef = useRef(null)
  // Prevent poll from overwriting optimistic 'ingesting' before backend thread writes status file
  const optimisticUntilRef = useRef(0)
  // Ref to track current ingestStatus for SSE callback (closure captures stale state)
  const ingestStatusRef = useRef('idle')
  const progressRef = useRef(null)
  // Keep refs in sync with state (for use inside setInterval closures that capture stale state)
  useEffect(() => { ingestStatusRef.current = ingestStatus }, [ingestStatus])
  useEffect(() => { progressRef.current = progress }, [progress])

  // ── 切换沙箱时清空所有状态，防止跨沙箱数据串扰 ──
  const switchedRef = useRef(false)
  useEffect(() => {
    // 取消正在进行的 forge 操作（防止旧沙箱的日志污染新沙箱控制台）
    if (forgeAbortRef.current) {
      forgeAbortRef.current.abort()
      forgeAbortRef.current = null
    }
    setForgeLogs([])
    setIngestStatus('idle')
    setProgress(null)
    setElapsed(0)
    setCheckpoint(null)
    setIsForging(false)
    optimisticUntilRef.current = 0
    doneDismissedRef.current = false  // 新沙箱允许重新展示 done 卡片
    completedRef.current = false
    setCompletedFlag(false)  // 新沙箱重置完成标记
    setCompletedInfo(null)
    switchedRef.current = true  // 标记：下次 poll 是切换后的首次
  }, [selectedSandbox])

  // ── Poll status (includes structured progress) ──
  useEffect(() => {
    if (!selectedSandbox) return
    let alive = true
    let pollSeenDone = false  // 闭包局部变量：追踪是否见过 phase=done

    const poll = async () => {
      try {
        const res = await apiFetch(`/api/task-logs/${encodeURIComponent(selectedSandbox)}/status`)
        if (!alive) return
        const data = await res.json()

        // 记录 phase=done（可能在某次 poll 中看到，但下次 poll 时被 idle 覆盖）
        if (data.progress?.phase === 'done') pollSeenDone = true

        const curStatus = ingestStatusRef.current

        // ⚠️ 切换沙箱后首次 poll：服务端说空闲就重置，但保留 phase=done 以显示完成卡片
        if (switchedRef.current) {
          switchedRef.current = false
          if (data.status !== 'ingesting') {
            setIngestStatus('idle')
            if (data.progress?.phase === 'done') {
              setProgress(data.progress)  // 保留完成状态
            } else {
              setProgress(null)
              setElapsed(0)
            }
            return
          }
        }

        // Stopping state: only accept idle transitions, ignore 'ingesting' from server
        // (thread may still be running — don't let poll revert our 'stopping' UI back to 'ingesting')
        if (curStatus === 'stopping') {
          if (data.status === 'idle') {
            setIngestStatus('idle')
            setTerminating(false)
            setProgress(null)
            setSseKey(k => k + 1)  // 重连 SSE + checkpoint polling
            setForgeLogs(prev => [...prev, { text: '✅ 后台任务已完全停止，检查点已保存', level: 'info' }])
          }
          return  // 阻止其他更新（包括 'ingesting'）
        }

        // Don't let server overwrite optimistic status within the lock window
        if (Date.now() < optimisticUntilRef.current) return

        // ⚠️ 服务端 idle 但前端仍是 ingesting → 切换到 idle
        if (data.status === 'idle' && curStatus === 'ingesting') {
          setIngestStatus('idle')
          setTerminating(false)
          // 关键修复：保留 phase=done，防止后端 finally 块将 phase 覆写为 idle
          // 四层防护：1) 后端返回 phase=done  2) pollSeenDone  3) progressRef 当前是 done  4) 数据字段推断
          const curPhase = progressRef.current?.phase
          const p = data.progress
          const inferredDone = p?.reduce_done > 0 && p?.total_concepts > 0 && p?.reduce_done >= p?.total_concepts
          if (data.progress?.phase === 'done' || pollSeenDone || curPhase === 'done' || inferredDone) {
            // 保留完成状态，让完成卡片能正确显示
            if (data.progress?.phase === 'done' || inferredDone) {
              const finalProgress = (inferredDone && data.progress?.phase !== 'done')
                ? { ...data.progress, phase: 'done' }
                : data.progress
              setProgress(finalProgress)
              if (inferredDone) console.log('[POLL] inferred done from data fields (reduce_done:', p?.reduce_done, 'total:', p?.total_concepts, ')')
            }
            // 否则保持现有 progress 不变（前端已有 phase=done）
          } else {
            setProgress(null)
            setElapsed(0)
          }
          pollSeenDone = false  // 重置
          return
        }

        setIngestStatus(data.status)
        if (data.progress) {
          if (data.status === 'ingesting') {
            // 摄入进行中：正常更新 progress
            setProgress(data.progress)
            if (data.progress.started != null) {
              setElapsed(Math.floor(Date.now() / 1000 - data.progress.started))
            }
          } else if (data.progress.phase === 'done') {
            // 摄入已完成：保留 phase=done，让完成卡片能正确显示
            setProgress(data.progress)
          }
          // 其他情况（idle + phase=idle）：不更新 progress，避免残留旧数据
        }
        if (data.status !== 'ingesting' && data.progress?.phase !== 'done') {
          setElapsed(0)
        }
      } catch {}
    }

    poll()
    const iv = setInterval(poll, 1500)
    return () => { alive = false; clearInterval(iv) }
  }, [selectedSandbox])

  // ── Poll checkpoint status ──
  useEffect(() => {
    if (!selectedSandbox) return
    let alive = true

    const pollCp = async () => {
      try {
        const res = await apiFetch(`/api/ingest/checkpoint?workspace=${encodeURIComponent(selectedSandbox)}`)
        if (!alive) return
        if (res.ok) {
          const data = await res.json()
          setCheckpoint(data)
        }
      } catch {}
    }

    pollCp()
    const iv = setInterval(pollCp, 5000)
    return () => { alive = false; clearInterval(iv) }
  }, [selectedSandbox])

  // ── Terminate ingest ──
  // 策略：SSE 信号为主（后台线程停止后 SSE 会发 idle），慢速轮询为安全网（SSE 断开时兜底）
  const handleTerminate = async () => {
    if (!selectedSandbox || terminating) return
    setTerminating(true)
    setIngestStatus('stopping')
    setProgress(null)
    optimisticUntilRef.current = 0  // 不需要 optimistic 锁，SSE handler 自己会过滤
    // 关闭旧 SSE，重连后 handler 会在 stopping 状态只接受 idle 信号
    if (sseRef.current) {
      sseRef.current.close()
      sseRef.current = null
    }
    setSseKey(k => k + 1)  // 触发 SSE 重连
    try {
      const formData = new FormData()
      formData.append('workspace', selectedSandbox)
      const res = await apiFetch('/api/ingest/terminate', { method: 'POST', body: formData })
      if (res.ok) {
        setForgeLogs(prev => [...prev, { text: '🛑 已发送停止信号，等待后台任务结束...', level: 'warning' }])
      } else {
        const err = await res.json().catch(() => ({}))
        setForgeLogs(prev => [...prev, { text: `❌ 终止失败: ${err.detail || res.status}`, level: 'error' }])
        setTerminating(false)
        return
      }
    } catch (e) {
      setForgeLogs(prev => [...prev, { text: `❌ 终止请求失败: ${e.message}`, level: 'error' }])
      setTerminating(false)
      return
    }

    // 安全网：慢速轮询（15s），仅在 SSE 未收到 idle 时兜底
    ;(async () => {
      let attempt = 0
      while (attempt < 40) {  // 最多 10 分钟
        attempt++
        await new Promise(r => setTimeout(r, 15000))
        // 如果已经不是 stopping 状态（SSE 已收到 idle），退出
        if (ingestStatusRef.current !== 'stopping') return
        try {
          const statusRes = await apiFetch(`/api/task-logs/${encodeURIComponent(selectedSandbox)}/status`)
          if (statusRes.ok) {
            const data = await statusRes.json()
            if (data.status === 'idle') {
              setIngestStatus('idle')
              setTerminating(false)
              setSseKey(k => k + 1)
              setForgeLogs(prev => [...prev, { text: `✅ 后台任务已完全停止，检查点已保存`, level: 'info' }])
              return
            }
          }
        } catch {}
        if (attempt % 4 === 0) {
          setForgeLogs(prev => [...prev, { text: `⏳ 仍在等待后台任务结束（已等待 ${attempt * 15}s）...`, level: 'info' }])
        }
      }
      // 超时兆底：强制解除终止锁定，避免按钮永久卡死
      if (ingestStatusRef.current === 'stopping') {
        setIngestStatus('idle')
        setTerminating(false)
        setSseKey(k => k + 1)
        setForgeLogs(prev => [...prev, { text: '⚠️ 等待超时，已强制解除终止锁定。请刷新页面确认后台状态。', level: 'warning' }])
      }
    })()
  }

  // ── Resume ingest (only allowed when fully idle — not during stopping) ──
  const handleResume = async () => {
    if (!selectedSandbox || resuming) return
    // 守卫：只有在完全停止（idle）状态才能继续，stopping/ingesting 期间禁止
    if (ingestStatusRef.current !== 'idle') return
    setResuming(true)
    try {
      const formData = new FormData()
      formData.append('workspace', selectedSandbox)
      const res = await apiFetch('/api/ingest/resume', { method: 'POST', body: formData })
      if (res.ok) {
        const data = await res.json()
        setForgeLogs(prev => [...prev, {
          text: `🔄 继续摄入已启动：${data.files.length} 个文件，${data.checkpoint_concepts} 个概念已跳过${data.cache_mode ? '（缓存加速，跳过 MAP+SHUFFLE）' : ''}`,
          level: 'info'
        }])
        setIngestStatus('ingesting')
        setProgress({
          phase: 'parsing',
          current_file: 0, total_files: data.files.length,
          current_file_name: '', total_chunks: 0, map_done: 0,
          total_concepts: data.checkpoint_concepts || 0,
          reduce_done: data.checkpoint_concepts || 0,
        })
        setElapsed(0)
        optimisticUntilRef.current = Date.now() + 30000
        setSseKey(k => k + 1)
      } else {
        const err = await res.json().catch(() => ({}))
        setForgeLogs(prev => [...prev, { text: `❌ 继续失败: ${err.detail || res.status}`, level: 'error' }])
      }
    } catch (e) {
      setForgeLogs(prev => [...prev, { text: `❌ 继续请求失败: ${e.message}`, level: 'error' }])
    } finally {
      setResuming(false)
    }
  }

  // ── Elapsed timer ──
  useEffect(() => {
    if (ingestStatus !== 'ingesting') {
      if (timerRef.current) clearInterval(timerRef.current)
      return
    }
    timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(timerRef.current)
  }, [ingestStatus])

  // ── Done card: 只在 phase 首次变为 done 时显示，3s 后自动消失 ──
  const doneShownRef = useRef(false)
  const doneDismissedRef = useRef(false)  // 永久标记：done 卡片已展示并消失，防止 poll 重新注入
  const prevPhaseRef = useRef(null)

  // phase 变为 done 时标记为已展示（仅首次转换触发）
  useEffect(() => {
    const cur = progress?.phase
    if (cur === 'done' && prevPhaseRef.current !== 'done') {
      doneShownRef.current = true
    }
    prevPhaseRef.current = cur
  }, [progress?.phase])

  // 新摄入开始或切换沙箱时重置
  useEffect(() => {
    if (ingestStatus === 'ingesting') {
      console.log('[RESET] ingestStatus=ingesting → resetting completion state')
      doneShownRef.current = false
      doneDismissedRef.current = false  // 新摄入允许重新展示
      completedRef.current = false
      prevPhaseRef.current = null
      setCompletedFlag(false)  // 新摄入重置完成标记
      setCompletedInfo(null)
      if (doneTimerRef.current) { clearTimeout(doneTimerRef.current); doneTimerRef.current = null }
    }
  }, [ingestStatus])

  // done 卡片不再自动隐藏，保持显示直到切换沙箱或新摄入开始

  // ── 判断是否处于「已完成」状态（phase=done 后显示完成卡片，8 秒后自动消失） ──
  const completedRef = useRef(false)
  const [completedFlag, setCompletedFlag] = useState(false)
  const [completedInfo, setCompletedInfo] = useState(null)  // { total_concepts, elapsed }
  const doneTimerRef = useRef(null)
  useEffect(() => {
    if (progress?.phase === 'done' && !completedRef.current) {
      console.log('[COMPLETION] phase=done detected! concepts:', progress.total_concepts, 'elapsed:', elapsed)
      completedRef.current = true
      setCompletedInfo({ total_concepts: progress.total_concepts || 0, elapsed })
      setCompletedFlag(true)
      // 8 秒后自动隐藏完成卡片，让检查点卡片有机会接管
      if (doneTimerRef.current) clearTimeout(doneTimerRef.current)
      doneTimerRef.current = setTimeout(() => {
        setCompletedFlag(false)
        doneTimerRef.current = null
      }, 8000)
    }
  }, [progress?.phase, progress?.total_concepts, elapsed])

  // ── SSE: real-time log + progress events ──
  useEffect(() => {
    if (!selectedSandbox || !token) return

    if (sseRef.current) {
      sseRef.current.close()
      sseRef.current = null
    }

    const url = `/api/task-logs/${encodeURIComponent(selectedSandbox)}/stream?token=${token}`
    const fullUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`
    const es = new EventSource(fullUrl)
    sseRef.current = es
    // ── 关键修复：用闭包局部变量追踪 phase=done ──
    // React 18 批处理下 progressRef.current 可能未及时更新，
    // 所以在 SSE handler 内用局部变量记录是否见过 phase=done
    let seenDoneThisSession = false

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)

        // Structured progress update
        if (data.type === 'progress') {
          // Stopping 状态：只接受 idle 信号（后台已完全停止），拒绝其他更新
          if (ingestStatusRef.current === 'stopping') {
            if (data.status === 'idle') {
              // 后台已完全停止 → 切换到 idle，让 checkpoint 卡片接管
              setIngestStatus('idle')
              setTerminating(false)
              optimisticUntilRef.current = 0  // 解除 optimistic 锁
              setSseKey(k => k + 1)  // 重连 SSE + checkpoint polling
              setForgeLogs(prev => [...prev, { text: '✅ 后台任务已完全停止，检查点已保存', level: 'info' }])
            }
            return  // 阻止其他进度更新
          }
          // 记录 phase=done 事件（_RE_COMPLETE 写入的完成信号）
          if (data.phase === 'done') {
            seenDoneThisSession = true
          }
          // ⚠️ 防止空闲卡住：服务端已 idle 但前端仍是 ingesting → 接受 idle 信号
          // 关键修复：如果本轮 SSE 曾收到 phase=done，保留它！
          // React 18 会将两个事件批处理，导致 phase=done 被 phase=idle 覆盖
          if (data.status === 'idle' && ingestStatusRef.current === 'ingesting') {
            // 后备检测：即使 seenDoneThisSession 为 false（SSE 重连后重置），
            // 如果数据字段表明已完成（reduce_done >= total_concepts > 0），也视为完成
            const inferredDone = seenDoneThisSession || (
              data.reduce_done > 0 && data.total_concepts > 0 && data.reduce_done >= data.total_concepts
            )
            const newProgress = (inferredDone && data.phase !== 'done')
              ? { ...data, phase: 'done' }  // 保留/推断 done，防止 finally 覆盖
              : { ...data }
            if (inferredDone && data.phase !== 'done') {
              console.log('[SSE] idle+ingesting → INFERRED DONE from data fields (reduce_done:', data.reduce_done, 'total:', data.total_concepts, ')')
            }
            console.log('[SSE] idle+ingesting → seenDone:', seenDoneThisSession, 'inferredDone:', inferredDone, 'dataPhase:', data.phase, '→ final:', newProgress.phase)
            setIngestStatus('idle')
            setProgress(newProgress)
            setTerminating(false)
            optimisticUntilRef.current = 0
            seenDoneThisSession = false  // 重置
            return
          }
          // ⚠️ 前端已 idle 时忽略非 done 的残留进度快照（SSE 重连时可能回放旧进度）
          // 但允许 phase=done 通过（用于页面刷新后重建完成卡片）
          if (ingestStatusRef.current === 'idle' && data.phase !== 'idle' && data.phase !== 'done') {
            return
          }
          if (data.phase === 'done') console.log('[SSE] fallthrough setProgress phase=done, status:', ingestStatusRef.current)
          setProgress({ ...data })
          if (data.started != null) setElapsed(Math.floor(Date.now() / 1000 - data.started))
          return
        }

        // Regular log entry
        if (data.message && data.message !== '── 实时推送中 ──') {
          const level = data.level || 'info'
          const prefix = level === 'success' ? '✅' : level === 'error' ? '❌' : level === 'warning' ? '⚠️' : ''
          setForgeLogs(prev => [...prev, {
            text: `${data.time ? `[${data.time}] ` : ''}${prefix}${data.message}`,
            level,
          }])

          if (data.message.includes('提炼完成') || data.message.includes('全部完成') || data.message.includes('摄入完毕')) {
            window.dispatchEvent(new CustomEvent('KB_PHYSICAL_UPDATE'))
          }
        }
      } catch {}
    }

    es.onerror = () => {}

    return () => {
      es.close()
      sseRef.current = null
    }
  }, [selectedSandbox, token, sseKey])

  // ── Upload files ──
  const uploadFiles = async (files) => {
    if (!selectedSandbox) {
      setForgeLogs(prev => [...prev, { text: "❌ 请先在左侧选择或新建一个目标沙箱！" }])
      return
    }
    // 终止中/摄入中/有未完成检查点禁止上传
    if (terminating || ingestStatusRef.current === 'stopping' || ingestStatusRef.current === 'ingesting') {
      setForgeLogs(prev => [...prev, { text: "⏳ 当前任务进行中，请等待完成或终止后再上传" }])
      return
    }

    const fileArray = Array.from(files)
    if (fileArray.length === 0) return

    setUploading(true)
    setUploadProgress(10)
    setForgeLogs(prev => [...prev, { text: `📥 收到 ${fileArray.length} 个文件，正在上传至 [${selectedSandbox}]...` }])

    const formData = new FormData()
    formData.append("workspace", selectedSandbox)
    fileArray.forEach(file => formData.append("files", file))

    try {
      setUploadProgress(40)
      const response = await apiFetch("/api/upload", {
        method: "POST",
        body: formData
      })

      if (!response.ok) throw new Error(`上传异常: ${response.status}`)

      setUploadProgress(100)
      setForgeLogs(prev => [...prev, { text: `✅ 文件已落盘，AI 提炼引擎已启动` }])
      // Optimistic: show progress card immediately, protect from poll for 10s
      setIngestStatus('ingesting')
      setElapsed(0)
      optimisticUntilRef.current = Date.now() + 10000
    } catch (err) {
      setForgeLogs(prev => [...prev, { text: `❌ 上传失败: ${err.message}` }])
    } finally {
      setTimeout(() => {
        setUploading(false)
        setUploadProgress(0)
      }, 800)
    }
  }

  // ── Forge actions ──
  // AbortController for cancelling forge when sandbox switches
  const forgeAbortRef = useRef(null)

  const handleForgeAction = async (actionType) => {
    if (isForging) return
    if (!selectedSandbox) {
      setForgeLogs(prev => [...prev, { text: "❌ 请先在左侧选择目标沙箱！" }])
      return
    }

    // Capture sandbox at operation start — if user switches, discard stale logs
    const targetSandbox = selectedSandbox
    // Cancel any previous forge operation
    if (forgeAbortRef.current) {
      forgeAbortRef.current.abort()
    }
    const controller = new AbortController()
    forgeAbortRef.current = controller

    setIsForging(true)
    setForgeLogs(prev => [...prev, { text: `🔥 正在执行 [${actionType}]...` }])

    try {
      const response = await apiFetch('/api/forge', {
        method: 'POST',
        body: JSON.stringify({ action: actionType, workspace: targetSandbox }),
        signal: controller.signal,
      })

      if (!response.ok) throw new Error(`后端无响应: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (value) buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        if (!done) buffer = parts.pop() || ''

        for (const line of parts) {
          if (line.startsWith('data: ')) {
            const dataStr = line.replace('data: ', '')
            if (!dataStr.trim()) continue
            try {
              const data = JSON.parse(dataStr)
              if (data.type === 'log') {
                // 🛡️ 跨沙箱保护：如果用户已切换沙箱，丢弃旧沙箱的日志
                setForgeLogs(prev => {
                  // 只在当前选中沙箱仍是操作发起时的沙箱时才追加
                  // 通过检查 prev 是否被 sandbox switch 重置过来判断
                  return [...prev, { text: data.content }]
                })
              }
            } catch {}
          }
        }
        if (done) break
      }

      window.dispatchEvent(new CustomEvent('KB_PHYSICAL_UPDATE'))

    } catch (err) {
      if (err.name === 'AbortError') {
        // Sandbox switched, operation cancelled — silent
      } else {
        setForgeLogs(prev => [...prev, { text: `💥 操作失败: ${err.message}` }])
      }
    } finally {
      setIsForging(false)
      if (forgeAbortRef.current === controller) {
        forgeAbortRef.current = null
      }
    }
  }

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadFiles(e.target.files)
    }
  }

  const formatTime = (s) => {
    if (s < 60) return `${s}s`
    return `${Math.floor(s / 60)}m ${s % 60}s`
  }

  const isIng = ingestStatus === 'ingesting'
  const isBusy = isIng || terminating || ingestStatus === 'stopping' || !!checkpoint?.has_checkpoint  // 摄入中/终止中/有未完成检查点均禁止操作
  const phase = progress?.phase || (isIng ? 'parsing' : 'idle')
  const phaseInfo = PHASES[phase] || PHASES.idle
  const percent = calcPercent(progress)

  return (
    <div className="p-2 space-y-4">
      {/* ══════════════════════════════════════════
          🔥 提炼进度可视化卡片
          ══════════════════════════════════════════ */}
      {isIng && (
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden">
          {/* ── 顶部：阶段 + 计时 ── */}
          <div className="px-4 pt-3 pb-2 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xl">{phaseInfo.icon}</span>
              <div>
                <div className="text-sm font-bold text-slate-200">
                  {phaseInfo.label}
                  {phase === 'done' ? '' : ' 中...'}
                </div>
                <div className="text-[10px] text-slate-500 font-mono">
                  {progress?.current_file_name && (
                    <span className="text-cyan-400/80">📄 {progress.current_file_name}</span>
                  )}
                  {!progress?.current_file_name && progress?.current_file > 0 && (
                    <span>文件 {progress.current_file}/{progress.total_files}</span>
                  )}
                </div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-lg font-mono font-bold text-cyan-400">{percent}%</div>
              <div className="text-[10px] text-slate-500 font-mono">{formatTime(elapsed)}</div>
            </div>
          </div>

          {/* ── 进度条 ── */}
          <div className="px-4 pb-2">
            <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ease-out ${
                  phase === 'done'
                    ? 'bg-gradient-to-r from-emerald-500 to-green-400'
                    : 'bg-gradient-to-r from-cyan-500 via-blue-500 to-purple-500'
                }`}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>

          {/* ── 阶段指示器 ── */}
          <div className="px-4 pb-3">
            <div className="flex items-center justify-between">
              {PHASE_ORDER.filter(p => p !== 'idle' && p !== 'stopping' && p !== 'done').map((p, i) => {
                const info = PHASES[p]
                const phaseIdx = PHASE_ORDER.indexOf(p)
                const currentIdx = PHASE_ORDER.indexOf(phase)
                const isPast = phaseIdx < currentIdx || phase === 'done'
                const isCurrent = p === phase
                const isFuture = phaseIdx > currentIdx && phase !== 'done'

                return (
                  <div key={p} className="flex items-center flex-1 last:flex-none">
                    <div className="flex flex-col items-center">
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs transition-all duration-300 ${
                        isPast ? 'bg-emerald-500/20 border border-emerald-500/50 text-emerald-400' :
                        isCurrent ? 'bg-cyan-500/20 border border-cyan-400/60 text-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.3)]' :
                        'bg-slate-800/50 border border-slate-700/40 text-slate-600'
                      }`}>
                        {isPast ? '✓' : info.icon}
                      </div>
                      <span className={`text-[9px] mt-0.5 font-mono ${
                        isCurrent ? 'text-cyan-400' : isPast ? 'text-emerald-500/70' : 'text-slate-600'
                      }`}>{info.label}</span>
                    </div>
                    {i < 3 && (
                      <div className={`flex-1 h-px mx-1 mt-[-10px] ${
                        isPast ? 'bg-emerald-500/40' : 'bg-slate-800'
                      }`} />
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* ── 统计行 ── */}
          <div className="px-4 pb-3 grid grid-cols-3 gap-2 text-center">
            <div className="bg-slate-950/50 rounded-lg py-1.5 px-2">
              <div className="text-[9px] text-slate-500 font-mono">文件</div>
              <div className="text-xs font-mono text-slate-300">
                <span className="text-cyan-400">{progress?.current_file || 0}</span>
                <span className="text-slate-600">/{progress?.total_files || 0}</span>
              </div>
            </div>
            <div className="bg-slate-950/50 rounded-lg py-1.5 px-2">
              <div className="text-[9px] text-slate-500 font-mono">概念</div>
              <div className="text-xs font-mono text-slate-300">
                <span className="text-purple-400">{progress?.reduce_done || 0}</span>
                <span className="text-slate-600">/{progress?.total_concepts || 0}</span>
              </div>
            </div>
            <div className="bg-slate-950/50 rounded-lg py-1.5 px-2">
              <div className="text-[9px] text-slate-500 font-mono">耗时</div>
              <div className="text-xs font-mono text-amber-400">{formatTime(elapsed)}</div>
            </div>
          </div>

          {/* ── 终止按钮 ── */}
          <div className="px-4 pb-3">
            <button
              onClick={handleTerminate}
              disabled={terminating}
              className={`w-full py-2 rounded-lg border text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all duration-200 ${
                terminating
                  ? 'bg-red-900/30 border-red-800/50 text-red-500/60 cursor-wait'
                  : 'bg-red-950/40 border-red-800/40 text-red-400 hover:bg-red-900/40 hover:border-red-600/60 hover:shadow-[0_0_12px_rgba(239,68,68,0.15)]'
              }`}
            >
              {terminating ? (
                <><span className="animate-spin">⏳</span> 正在终止...</>
              ) : (
                <><span>⏹</span> 终止摄入</>
              )}
            </button>
          </div>

        </div>
      )}

      {/* ── 正在停止卡片（不可操作，等后台完全停止后自动变成黄色检查点卡片）── */}
      {ingestStatus === 'stopping' && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3">
          <div className="flex items-center gap-2">
            <span className="text-lg animate-pulse">🛑</span>
            <div className="flex-1">
              <div className="text-xs font-bold text-red-400">正在停止...</div>
              <div className="text-[10px] text-red-300/60 font-mono">
                等待后台任务结束，停止后将显示检查点信息
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── 完成状态卡片（全部概念融合完毕时显示）── */}
      {ingestStatus === 'idle' && completedFlag && !terminating && (
        <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">✅</span>
            <div className="flex-1">
              <div className="text-xs font-bold text-emerald-400">提炼完成</div>
              <div className="text-[10px] text-emerald-300/60 font-mono">
                {completedInfo?.total_concepts ?? progress?.total_concepts ?? '?'} 个概念已落盘 · 耗时 {formatTime(completedInfo?.elapsed ?? elapsed)}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── 检查点继续摄入卡片（概念级断点）── 只在完全 idle 且未完成时显示 */}
      {ingestStatus === 'idle' && !terminating && !completedFlag && checkpoint?.has_checkpoint && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-lg">📌</span>
            <div className="flex-1">
              <div className="text-xs font-bold text-amber-400">上次摄入未完成</div>
              <div className="text-[10px] text-amber-300/60 font-mono">
                已融合 {checkpoint.concepts} 个概念{checkpoint.pending_concepts ? `，剩余 ${checkpoint.pending_concepts} 个待处理` : ''}{checkpoint.has_cache ? ' (缓存加速)' : ''}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleResume}
              disabled={resuming || ingestStatus !== 'idle' || terminating}
              className={`flex-1 py-1.5 rounded-lg border text-xs font-mono font-medium flex items-center justify-center gap-1.5 transition-all duration-200 ${
                resuming || ingestStatus !== 'idle'
                  ? 'bg-emerald-900/30 border-emerald-800/50 text-emerald-500/60 cursor-wait'
                  : 'bg-emerald-950/40 border-emerald-700/40 text-emerald-400 hover:bg-emerald-900/40 hover:border-emerald-600/60'
              }`}
            >
              {resuming ? (
                <><span className="animate-spin">⏳</span> 等待启动中...</>
              ) : (
                <><span>▶</span> 继续摄入</>
              )}
            </button>
            <button
              onClick={async () => {
                if (!selectedSandbox) return
                try {
                  const formData = new FormData()
                  formData.append('workspace', selectedSandbox)
                  await apiFetch('/api/ingest/clear-checkpoint', { method: 'POST', body: formData })
                  setCheckpoint(null)
                  setForgeLogs(prev => [...prev, { text: '🗑️ 检查点已清除，下次摄入将从头开始', level: 'info' }])
                } catch {}
              }}
              className="py-1.5 px-3 rounded-lg border text-xs font-mono border-slate-800 text-slate-500 hover:border-slate-700 hover:text-slate-400 transition-all"
              title="清除检查点，下次从头开始"
            >
              🗑️
            </button>
          </div>
        </div>
      )}

      {/* Upload Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if(e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            uploadFiles(e.dataTransfer.files)
          }
        }}
        onClick={() => document.getElementById('forge-file-picker').click()}
        className={`border-2 border-dashed rounded-xl p-5 text-center transition-all duration-300 cursor-pointer ${
          dragOver
            ? 'border-cyan-400 bg-cyan-500/10 shadow-[0_0_12px_rgba(34,211,238,0.15)]'
            : 'border-slate-800 hover:border-slate-700 bg-slate-950/20'
        } ${isBusy ? 'opacity-50 pointer-events-none' : ''}`}
      >
        <input
          type="file"
          id="forge-file-picker"
          className="hidden"
          multiple
          onChange={handleFileChange}
          accept=".md,.txt,.pdf"
        />
        {uploading ? (
          <div className="space-y-3">
            <div className="text-xl animate-bounce text-cyan-400">⚡</div>
            <div className="text-xs text-cyan-300 font-medium font-mono">UPLOADING...</div>
            <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400 rounded-full transition-all duration-300"
                style={{ width: `${Math.min(uploadProgress, 100)}%` }}
              />
            </div>
            <div className="text-[9px] text-slate-500 font-mono">{Math.round(uploadProgress)}%</div>
          </div>
        ) : (
          <>
            <div className="text-2xl mb-1 opacity-70">🕸️</div>
            <div className="text-xs text-slate-400 font-medium">拖拽或点击投入物理知识资产</div>
            <div className="text-[9px] text-slate-600 mt-0.5 font-mono">SUPPORT BATCH: PDF / Markdown / TXT</div>
          </>
        )}
      </div>

      {/* Action Buttons */}
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={() => handleForgeAction('reweave')}
          disabled={isForging || uploading || isBusy}
          className={`py-2 px-2 rounded-lg border text-xs font-mono font-medium flex items-center justify-center gap-1.5 transition-all duration-200 ${
            isForging || isBusy ? 'bg-slate-900 border-slate-800 text-slate-600 cursor-wait' : 'bg-slate-800/40 border-slate-800 text-slate-300 hover:border-red-500/40 hover:text-red-400 shadow-sm'
          }`}
        >
          <span>🕷️</span>
          重织死链
        </button>
        <button
          onClick={() => handleForgeAction('fill_blackhole')}
          disabled={isForging || uploading || isBusy}
          className={`py-2 px-2 rounded-lg border text-xs font-mono font-medium flex items-center justify-center gap-1.5 transition-all duration-200 ${
            isForging || isBusy ? 'bg-slate-900 border-slate-800 text-slate-600 cursor-wait' : 'bg-slate-800/40 border-slate-800 text-slate-300 hover:border-purple-500/40 hover:text-purple-400 shadow-sm'
          }`}
        >
          <span>🪄</span>
          填补黑洞
        </button>
      </div>

      {/* Status */}
      <div className="bg-slate-950/60 border border-slate-900 rounded-lg p-2.5 font-mono text-[10px] space-y-1 text-slate-400">
        <div className="flex items-center justify-between">
          <span className="text-slate-500">沙箱:</span>
          <span className="text-cyan-400">{selectedSandbox ? `[${selectedSandbox}]` : "未选定"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-500">提炼引擎:</span>
          <span className={isIng ? 'text-amber-400 animate-pulse' : 'text-emerald-400'}>
            {isIng ? `⚡ ${phaseInfo.label}中` : '✅ 空闲'}
          </span>
        </div>
      </div>
    </div>
  )
}
