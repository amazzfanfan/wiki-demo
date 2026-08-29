import { useRef, useEffect, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import ReactMarkdown from 'react-markdown'
import { useAuth } from '../contexts/AuthContext'

export default function ForceGraph({ selectedSandbox, onNodeClick, selectedNode }) {
  const { apiFetch } = useAuth()
  const fgRef = useRef()
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [aliases, setAliases] = useState({})  // wikilink简称 → 节点全名

  // 拓扑高亮状态
  const [highlightNodes, setHighlightNodes] = useState(new Set())
  const [highlightLinks, setHighlightLinks] = useState(new Set())

  // 沉浸式阅读窗状态
  const [modalOpen, setModalOpen] = useState(false)
  const [mdContent, setMdContent] = useState('')
  const [isLoadingMd, setIsLoadingMd] = useState(false)

  // 1. 拉取图谱网络数据（提取为函数，供初始化和事件刷新共用）
  const fetchGraph = useCallback(() => {
    if (!selectedSandbox) {
      setGraphData({ nodes: [], links: [] })
      setAliases({})
      return
    }

    apiFetch(`/api/graph?workspace=${selectedSandbox}`)
      .then(res => res.json())
      .then(data => {
        const validNodeIds = new Set(data.nodes.map(n => n.id))
        const safeLinks = data.links.filter(link =>
          validNodeIds.has(link.source) && validNodeIds.has(link.target)
        )
        setGraphData({ nodes: data.nodes, links: safeLinks })
        setAliases(data.aliases || {})
      })
      .catch(err => console.error("星图获取失败:", err))
  }, [selectedSandbox, apiFetch])

  // 初始化拉取
  useEffect(() => {
    fetchGraph()
  }, [fetchGraph])

  // 监听 KB_PHYSICAL_UPDATE（审批通过/拒绝/Ingest 完成等）→ 刷新星图
  useEffect(() => {
    const handleKbUpdate = () => fetchGraph()
    window.addEventListener('KB_PHYSICAL_UPDATE', handleKbUpdate)
    return () => window.removeEventListener('KB_PHYSICAL_UPDATE', handleKbUpdate)
  }, [fetchGraph])

  // 🚀 统一节点聚焦与文档调度中心
  const selectNode = useCallback((node, forceOpenModal = false) => {
    if (!node) return

    // 通知外部容器当前选中的节点 ID
    if (onNodeClick) onNodeClick(node.id)

    // 计算当前节点的引力场（邻居与连线高亮）
    const newHighlightNodes = new Set([node.id])
    const newHighlightLinks = new Set()

    graphData.links.forEach(link => {
      const sourceId = typeof link.source === 'object' ? link.source.id : link.source
      const targetId = typeof link.target === 'object' ? link.target.id : link.target

      if (sourceId === node.id || targetId === node.id) {
        newHighlightLinks.add(link)
        newHighlightNodes.add(sourceId)
        newHighlightNodes.add(targetId)
      }
    })

    setHighlightNodes(newHighlightNodes)
    setHighlightLinks(newHighlightLinks)

    // 黄金分割视口推移（确保节点有真实的物理坐标才执行动画）
    if (fgRef.current && node.x !== undefined && node.y !== undefined) {
      const targetZoom = 3.5
      const containerWidth = window.innerWidth - 260
      const xOffset = (containerWidth * 0.25) / targetZoom

      fgRef.current.centerAt(node.x + xOffset, node.y, 800)
      fgRef.current.zoom(targetZoom, 800)
    }

    // 核心体验：如果当前弹窗本来就是开着的，或者被强制要求打开（如点击双链）
    if (modalOpen || forceOpenModal) {
      setModalOpen(true)
      setIsLoadingMd(true)
      // 使用 encodeURIComponent 确保中文路径不乱码
      apiFetch(`/api/concept?workspace=${selectedSandbox}&name=${encodeURIComponent(node.id)}`)
        .then(res => res.json())
        .then(data => setMdContent(data.content))
        .catch(() => setMdContent('❌ 无法读取物理文件，可能遭遇断链。'))
        .finally(() => setIsLoadingMd(false))
    }
  }, [graphData, selectedSandbox, onNodeClick, modalOpen])

  // 2. 星图画布上的节点点击拦截器
  const handleNodeClick = useCallback((node) => {
    // 如果点击的是当前已经选中的点 -> 触发二次连击，强行撞开阅读窗
    if (selectedNode === node.id) {
      selectNode(node, true)
    } else {
      // 如果是点击全新的点 -> 执行常规聚焦（若窗口开着会自动在内部刷新文档）
      selectNode(node, false)
    }
  }, [selectedNode, selectNode])

  // 3. 点击画布空白处重置整个宇宙空间
  const handleBackgroundClick = useCallback(() => {
    if (onNodeClick) onNodeClick(null)
    setHighlightNodes(new Set())
    setHighlightLinks(new Set())
    setModalOpen(false)
  }, [onNodeClick])

  return (
    <div className="w-full h-full bg-[#020617] relative overflow-hidden">
      {graphData.nodes.length === 0 ? (
        <div className="absolute inset-0 flex items-center justify-center text-slate-500 font-mono text-sm">
          {!selectedSandbox ? "👈 请在左侧选择一个知识沙箱" : "🌌 正在扫描星图数据或沙箱为空..."}
        </div>
      ) : (
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeRelSize={5}

          // 核心控制：选中点高亮为绝对纯白，一度内邻居高亮为翠绿，其余暗沉
          nodeColor={(node) => {
            if (highlightNodes.size === 0) {
              if (node.id === selectedNode) return '#ffffff'
              return '#0ea5e9'
            }
            if (node.id === selectedNode) return '#ffffff'
            if (highlightNodes.has(node.id)) return '#34d399'
            return '#1e293b'
          }}

          linkColor={(link) => highlightLinks.has(link) ? 'rgba(52, 211, 153, 0.8)' : 'rgba(203, 213, 225, 0.05)'}
          linkWidth={(link) => highlightLinks.has(link) ? 1.5 : 0.5}
          linkDirectionalParticles={(link) => highlightLinks.has(link) ? 3 : 0}
          linkDirectionalParticleWidth={2}

          nodeCanvasObjectMode={() => 'after'}
          nodeCanvasObject={(node, ctx, globalScale) => {
            if (globalScale >= 2) {
              const label = node.id
              const fontSize = 12 / globalScale
              ctx.font = `${fontSize}px "Fira Code", monospace`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'middle'

              if (highlightNodes.size === 0 || highlightNodes.has(node.id)) {
                if (node.id === selectedNode) {
                  ctx.fillStyle = '#ffffff'
                } else if (highlightNodes.has(node.id)) {
                  ctx.fillStyle = '#34d399'
                } else {
                  ctx.fillStyle = '#cbd5e1'
                }
                ctx.fillText(label, node.x, node.y + 6 + fontSize)
              }
            }
          }}

          onNodeClick={handleNodeClick}
          onBackgroundClick={handleBackgroundClick}
          enableNodeDrag={true}
        />
      )}

      {/* 🔮 右侧沉浸式浮窗 */}
      {modalOpen && (
        <div className="absolute top-1/2 right-6 -translate-y-1/2 w-[500px] max-h-[85vh] bg-slate-900/95 border border-cyan-500/40 rounded-xl shadow-[-10px_0_40px_rgba(34,211,238,0.1)] flex flex-col overflow-hidden backdrop-blur-xl z-50 transition-all duration-300">
          <div className="px-4 py-3 border-b border-slate-700/60 bg-slate-800/60 flex justify-between items-center">
            <span className="text-sm font-mono text-cyan-400 font-bold flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
              {selectedNode}.md
            </span>
            <button
              onClick={() => setModalOpen(false)}
              className="text-slate-400 hover:text-red-400 font-mono text-xs border border-slate-700 hover:border-red-500/50 px-2 py-1 rounded transition-colors"
            >
              [CLOSE]
            </button>
          </div>

          <div className="p-5 overflow-y-auto font-mono text-[13px] text-slate-300 leading-relaxed custom-scrollbar">
            {isLoadingMd ? (
              <span className="text-cyan-500/60 animate-pulse">DECRYPTING PHYSICAL LAYER...</span>
            ) : (
              <ReactMarkdown
                // 💡 预处理：将文本中的双链 [[概念]] 转换为带有 #锚点 的安全伪协议
                children={mdContent.replace(/\[\[(.*?)\]\]/g, '[$1](<#wiki:$1>)')}

                // 💡 自定义赛博格式化排版
                components={{
                  h1: ({node, ...props}) => <h1 className="text-xl text-cyan-300 font-bold mb-4 border-b border-cyan-900/50 pb-2" {...props} />,
                  h2: ({node, ...props}) => <h2 className="text-lg text-emerald-400 font-bold mt-5 mb-3" {...props} />,
                  h3: ({node, ...props}) => <h3 className="text-base text-slate-200 font-bold mt-4 mb-2" {...props} />,
                  p: ({node, ...props}) => <p className="mb-3 text-slate-300 leading-relaxed" {...props} />,
                  ul: ({node, ...props}) => <ul className="list-disc list-inside mb-3 space-y-1 text-slate-400" {...props} />,
                  ol: ({node, ...props}) => <ol className="list-decimal list-inside mb-3 space-y-1 text-slate-400" {...props} />,
                  code: ({node, inline, ...props}) =>
                    inline
                      ? <code className="bg-slate-800 text-cyan-300 px-1.5 py-0.5 rounded text-xs" {...props} />
                      : <code className="block bg-slate-950 border border-slate-800 p-3 rounded-lg text-xs text-emerald-300 overflow-x-auto mb-3" {...props} />,
                  blockquote: ({node, ...props}) => <blockquote className="border-l-4 border-emerald-500/50 pl-3 italic text-slate-400 bg-slate-800/30 py-1 my-3" {...props} />,

                  // 🚀 核心双链点击拦截 🚀
                  // 🚀 核心双链点击拦截（加入黑洞视觉识别） 🚀
                  a: ({node, href, children, ...props}) => {
                    if (href && href.startsWith('#wiki:')) {
                      const rawConcept = decodeURIComponent(href.replace('#wiki:', ''))
                      // 用别名映射解析简称 → 全名
                      const targetConcept = aliases[rawConcept] || rawConcept

                      // 💡 渲染时就进行判定：去星图节点里找，看看它是不是真实的物理节点
                      const realNode = graphData.nodes.find(n => n.id === targetConcept && !n.is_blackhole)
                      const isBlackhole = !realNode // 如果找不到，或者被标记为黑洞，那它就是个空节点

                      return (
                        <button
                          onClick={(e) => {
                            e.preventDefault()
                            if (!isBlackhole) {
                              selectNode(realNode, true)
                            } else {
                              if (onNodeClick) onNodeClick(targetConcept)
                              setHighlightNodes(new Set([targetConcept]))
                              setHighlightLinks(new Set())
                              setMdContent('⚠️ 该概念仅作为图谱中的【黑洞引用】存在，尚未被大模型实例化生成物理文件。')
                            }
                          }}
                          // 💡 视觉分级：
                          // 真实节点：赛博发光蓝/绿，鼠标是指针，诱导点击
                          // 黑洞节点：暗沉的灰石板色，虚线也变暗，鼠标是求助问号 (cursor-help)
                          className={
                            isBlackhole
                              ? "text-slate-500 hover:text-slate-400 font-mono underline decoration-slate-700 decoration-dashed underline-offset-4 transition-colors cursor-help inline-flex items-center gap-0.5 group"
                              : "text-cyan-400 hover:text-emerald-300 font-bold underline decoration-cyan-500/40 decoration-dashed underline-offset-4 transition-colors cursor-pointer inline-flex items-center gap-0.5 group"
                          }
                        >
                          <span className={isBlackhole ? "text-slate-600/70" : "text-cyan-600 group-hover:text-emerald-500"}>[[</span>
                          {children}
                          <span className={isBlackhole ? "text-slate-600/70" : "text-cyan-600 group-hover:text-emerald-500"}>]]</span>
                        </button>
                      )
                    }
                    return <a href={href} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 underline" {...props}>{children}</a>
                  }
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
