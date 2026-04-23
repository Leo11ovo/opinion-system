import { reactive, ref, computed, watch } from 'vue'
import { useApiBase } from './useApiBase'
import { useActiveProject } from './useActiveProject'

const { callApi } = useApiBase()
const { activeProjectName, setActiveProject } = useActiveProject()

// RAG Topics State (mirrors useBasicAnalysis topicsState)
const ragTopicsState = reactive({
  loading: false,
  error: '',
  options: [],  // union of all topics
  tagrag: [],
  router: []
})

const ragTopicOptions = computed(() => ragTopicsState.options)
const tagragTopicOptions = computed(() => ragTopicsState.tagrag)
const routerTopicOptions = computed(() => ragTopicsState.router)

const remoteTopicsState = reactive({
  loading: false,
  error: '',
  options: []
})

const remoteTopicOptions = computed(() => remoteTopicsState.options)
const localTopicsState = reactive({
  loading: false,
  error: '',
  options: []
})
const localTopicOptions = computed(() => localTopicsState.options)

// Search form (mirrors analyzeForm)
const ragSearchForm = reactive({
  topic: '',
  query: '',
  rag_type: 'routerrag',  // Add rag_type field
  top_k: 10,
  threshold: 0.0
})

// Retrieval State
const ragRetrievalState = reactive({
  loading: false,
  error: '',
  results: [],
  total: 0,
  raw_total: 0,
  summary: ''
})

const ragBuildState = reactive({
  loading: false,
  error: '',
  status: '',
  percent: 0,
  message: ''
})

const ragImportState = reactive({
  loading: false,
  error: '',
  result: null
})

const ragRlhfForm = reactive({
  topic: '',
  experiment_tag: '',
  limit: 1000
})

const ragRlhfStatsState = reactive({
  loading: false,
  error: '',
  data: null
})

const ragRlhfTuneState = reactive({
  loading: false,
  error: '',
  result: null
})

const ragFeedbackState = reactive({
  loading: false,
  error: '',
  success: ''
})

const ragBuildForm = reactive({
  source_type: 'remote',
  remote_topic: '',
  local_topic: '',
  build_topic: '',
  local_source_dir: 'backend/data/report_data',
  sample_ratio: 1.0,
  chunk_mode: 'sentence',
  chunk_size: 220,
  chunk_overlap: 40,
  force_rebuild: false
})

const ragCacheState = reactive({
  visible: false,
  running: false,
  percent: 0,
  message: '',
  topic: '',
  type: ''
})

let ragCacheTimer = null
let ragCacheHideTimer = null
let ragCacheRefreshQueued = false

const buildAutoProjectName = () => {
  const now = new Date()
  const pad = (num) => String(num).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  return `rag-lab-${stamp}`
}

const ensureActiveProject = async () => {
  const current = String(activeProjectName.value || '').trim()
  if (current) return current

  const autoName = buildAutoProjectName()
  const response = await callApi('/api/projects', {
    method: 'POST',
    body: JSON.stringify({
      name: autoName,
      description: 'Auto-created by RAG import workflow',
      metadata: { source: 'rag-topics-auto-create' }
    })
  })
  const project = response?.project || { name: autoName }
  setActiveProject(project)
  return String(project?.name || autoName)
}

const stopRagCachePolling = () => {
  if (ragCacheTimer) {
    clearInterval(ragCacheTimer)
    ragCacheTimer = null
  }
}

const scheduleHideCacheToast = () => {
  if (ragCacheHideTimer) {
    clearTimeout(ragCacheHideTimer)
  }
  ragCacheHideTimer = setTimeout(() => {
    ragCacheState.visible = false
  }, 4000)
}

const updateCacheState = (payload = {}) => {
  ragCacheState.percent = Number(payload.percent || payload.percentage || 0)
  ragCacheState.message = payload.message || ''
  ragCacheState.running = payload.status === 'running'
  if (payload.topic) ragCacheState.topic = payload.topic
  if (payload.type) ragCacheState.type = payload.type

  if (ragCacheState.running) {
    ragCacheState.visible = true
    if (ragCacheHideTimer) clearTimeout(ragCacheHideTimer)
  } else if (payload.status === 'done' || payload.status === 'error') {
    ragCacheState.visible = true
    scheduleHideCacheToast()
  }
}

const pollRagCacheStatus = async (type, topic) => {
  stopRagCachePolling()
  if (!activeProjectName.value || !topic) return

  const params = new URLSearchParams({
    project: activeProjectName.value,
    type,
    topic
  })

  const fetchStatus = async () => {
    const response = await callApi(`/api/rag/cache/status?${params.toString()}`, { method: 'GET' })
    const status = response?.data || {}
    if (status.status === 'idle') {
      stopRagCachePolling()
      ragCacheState.visible = false
      return
    }
    updateCacheState({ ...status, type, topic })
    if (status.status === 'done' || status.status === 'error') {
      stopRagCachePolling()
      if (status.status === 'done' && !ragCacheRefreshQueued) {
        ragCacheRefreshQueued = true
        setTimeout(async () => {
          await loadRAGTopics()
          ragCacheRefreshQueued = false
        }, 600)
      }
    }
  }

  await fetchStatus()
  ragCacheTimer = setInterval(fetchStatus, 2000)
}

// Functions
const loadRAGTopics = async () => {
  ragTopicsState.loading = true
  ragTopicsState.error = ''

  try {
    const params = new URLSearchParams()
    if (activeProjectName.value) {
      params.set('project', activeProjectName.value)
    }
    const url = params.toString() ? `/api/rag/topics?${params.toString()}` : '/api/rag/topics'
    const response = await callApi(url, { method: 'GET' })

    const tagragTopics = response?.data?.tagrag_topics || []
    const routerTopics = response?.data?.router_topics || []
    ragTopicsState.tagrag = tagragTopics
      .map((item) => String(item || '').trim())
      .filter((name, index, arr) => name && arr.indexOf(name) === index)
    ragTopicsState.router = routerTopics
      .map((item) => String(item || '').trim())
      .filter((name, index, arr) => name && arr.indexOf(name) === index)
    ragTopicsState.options = [...ragTopicsState.tagrag, ...ragTopicsState.router]
      .filter((name, index, arr) => name && arr.indexOf(name) === index)

    if (ragSearchForm.topic && !ragTopicsState.options.includes(ragSearchForm.topic)) {
      ragSearchForm.topic = ''
    }


    return response
  } catch (error) {
    ragTopicsState.error = error.message || '加载RAG专题列表失败'
    throw error
  } finally {
    ragTopicsState.loading = false
  }
}

const loadRemoteTopics = async () => {
  remoteTopicsState.loading = true
  remoteTopicsState.error = ''

  try {
    const response = await callApi('/api/query', {
      method: 'POST',
      body: JSON.stringify({ include_counts: false })
    })
    const databases = response?.data?.databases ?? []
    remoteTopicsState.options = databases
      .map((db) => String(db?.name || '').trim())
      .filter((name, index, arr) => name && arr.indexOf(name) === index)
    if (!remoteTopicsState.options.includes(ragBuildForm.remote_topic)) {
      ragBuildForm.remote_topic = remoteTopicsState.options[0] || ''
    }
    return response
  } catch (error) {
    remoteTopicsState.error = error.message || '加载远程专题失败'
    remoteTopicsState.options = []
    ragBuildForm.remote_topic = ''
    throw error
  } finally {
    remoteTopicsState.loading = false
  }
}

const loadLocalTopics = async () => {
  localTopicsState.loading = true
  localTopicsState.error = ''

  try {
    if (!activeProjectName.value) {
      localTopicsState.options = []
      ragBuildForm.local_topic = ''
      return null
    }
    const response = await callApi(`/api/projects/${encodeURIComponent(activeProjectName.value)}/datasets`, {
      method: 'GET'
    })
    const datasets = response?.datasets || response?.data?.datasets || []
    localTopicsState.options = datasets
      .map((ds) => {
        const display = String(ds?.display_name || '').trim()
        const id = String(ds?.id || '').trim()
        return display || id
      })
      .filter((name, index, arr) => name && arr.indexOf(name) === index)

    if (!localTopicsState.options.includes(ragBuildForm.local_topic)) {
      localTopicsState.options = [...localTopicsState.options]
      ragBuildForm.local_topic = localTopicsState.options[0] || ''
    }
    return response
  } catch (error) {
    localTopicsState.error = error.message || '加载本地数据源失败'
    localTopicsState.options = []
    ragBuildForm.local_topic = ''
    throw error
  } finally {
    localTopicsState.loading = false
  }
}

const buildRagTopic = async (params = {}) => {
  ragBuildState.loading = true
  ragBuildState.error = ''
  const sourceType = params.source_type || ragBuildForm.source_type || 'remote'
  const selectedRemote = params.remote_topic || ragBuildForm.remote_topic
  const selectedLocal = params.local_topic || ragBuildForm.local_topic
  const selectedManualTopic = String(params.build_topic || ragBuildForm.build_topic || '').trim()
  const selectedDir = String(params.local_source_dir || ragBuildForm.local_source_dir || '').trim()
  const buildTopic = params.topic || selectedManualTopic || (sourceType === 'local' ? selectedLocal : selectedRemote)
  const buildType = params.type || 'tagrag'

  if (!buildTopic) {
    ragBuildState.loading = false
    ragBuildState.error = '请选择要生成的专题'
    return null
  }
  if (sourceType === 'dir' && !selectedDir) {
    ragBuildState.loading = false
    ragBuildState.error = '请填写本地目录路径（例如 backend/data/report_data）'
    return null
  }
  if (!activeProjectName.value) {
    ragBuildState.loading = false
    ragBuildState.error = '请先在左侧选择项目'
    return null
  }

  try {
    const response = await callApi('/api/rag/build', {
      method: 'POST',
      body: JSON.stringify({
        topic: buildTopic,
        project: activeProjectName.value,
        type: buildType,
        source_type: sourceType,
        local_source_dir: sourceType === 'dir' ? selectedDir : undefined,
        sample_ratio: Number(ragBuildForm.sample_ratio || 1.0),
        chunk_mode: String(ragBuildForm.chunk_mode || 'sentence'),
        chunk_size: Number(ragBuildForm.chunk_size || 220),
        chunk_overlap: Number(ragBuildForm.chunk_overlap || 40),
        force_rebuild: Boolean(ragBuildForm.force_rebuild)
      })
    })
    const status = response?.data || {}
    ragBuildState.status = status.status || ''
    ragBuildState.percent = Number(status.percent || 0)
    ragBuildState.message = status.message || ''
    updateCacheState({ ...status, type: buildType, topic: buildTopic })
    await pollRagCacheStatus(buildType, buildTopic)
    return response
  } catch (error) {
    ragBuildState.error = error.message || '准备检索专题失败'
    throw error
  } finally {
    ragBuildState.loading = false
  }
}

const importRouterRAGArtifacts = async (params = {}) => {
  ragImportState.loading = true
  ragImportState.error = ''
  ragImportState.result = null

  const topic = String(params.topic || '').trim()
  const source_path = String(params.source_path || '').trim()
  if (!topic || !source_path) {
    ragImportState.loading = false
    ragImportState.error = '请填写导入专题名和索引路径'
    return null
  }

  try {
    const projectName = await ensureActiveProject()
    const response = await callApi('/api/rag/routerrag/import', {
      method: 'POST',
      body: JSON.stringify({
        project: projectName,
        topic,
        source_path
      })
    })
    ragImportState.result = response?.data || null
    await loadRAGTopics()
    return response
  } catch (error) {
    ragImportState.error = error.message || '导入RouterRAG索引失败'
    throw error
  } finally {
    ragImportState.loading = false
  }
}

const retrieveTagRAG = async (params = {}) => {
  ragRetrievalState.loading = true
  ragRetrievalState.error = ''
  ragRetrievalState.results = []
  ragRetrievalState.total = 0
  ragRetrievalState.raw_total = 0

  try {
    const response = await callApi('/api/rag/tagrag/retrieve', {
      method: 'POST',
      body: JSON.stringify({
        query: params.query || ragSearchForm.query,
        topic: params.topic || ragSearchForm.topic,
        project: params.project || activeProjectName.value || undefined,
        top_k: params.top_k || ragSearchForm.top_k,
        threshold: params.threshold || ragSearchForm.threshold
      })
    })

    ragRetrievalState.results = response?.data?.results || []
    ragRetrievalState.total = response?.data?.total || 0
    ragRetrievalState.raw_total = response?.data?.raw_total ?? ragRetrievalState.total
    ragRetrievalState.summary = response?.data?.summary || ''

    if (response?.status === 'building') {
      ragRetrievalState.error = response?.message || '正在准备检索资料，请稍后再试'
      updateCacheState({ ...response.data, type: 'tagrag', topic: params.topic || ragSearchForm.topic })
      await pollRagCacheStatus('tagrag', params.topic || ragSearchForm.topic)
    }

    return response
  } catch (error) {
    ragRetrievalState.error = error.message || 'TagRAG检索失败'
    throw error
  } finally {
    ragRetrievalState.loading = false
  }
}

const retrieveRouterRAG = async (params = {}) => {
  ragRetrievalState.loading = true
  ragRetrievalState.error = ''
  ragRetrievalState.results = []
  ragRetrievalState.total = 0
  ragRetrievalState.raw_total = 0

  try {
    const response = await callApi('/api/rag/routerrag/retrieve', {
      method: 'POST',
      body: JSON.stringify({
        query: params.query || ragSearchForm.query,
        topic: params.topic || ragSearchForm.topic,
        mode: params.mode || (() => {
          const type = ragSearchForm.rag_type
          if (type === 'routerrag') return 'normalrag'
          if (type === 'hybrid') return 'mixed'
          return type
        })(),
        project: params.project || activeProjectName.value || undefined,
        top_k: params.top_k || ragSearchForm.top_k,
        threshold: params.threshold || ragSearchForm.threshold,
        question_type: params.question_type || undefined,
        experiment_tag: params.experiment_tag || undefined,
        trace_id: params.trace_id || undefined,
        use_question_preset: params.use_question_preset,
        enable_expert_overlay: params.enable_expert_overlay,
        enable_expert_rewrite: params.enable_expert_rewrite,
        enable_expert_hints: params.enable_expert_hints,
        enable_expert_answer_structure: params.enable_expert_answer_structure
      })
    })

    ragRetrievalState.results = response?.data?.results || []
    ragRetrievalState.total = response?.data?.total || 0
    ragRetrievalState.raw_total = response?.data?.raw_total ?? ragRetrievalState.total
    ragRetrievalState.summary = response?.data?.summary || ''

    if (response?.status === 'building') {
      ragRetrievalState.error = response?.message || '正在准备检索资料，请稍后再试'
      updateCacheState({ ...response.data, type: 'routerrag', topic: params.topic || ragSearchForm.topic })
      await pollRagCacheStatus('routerrag', params.topic || ragSearchForm.topic)
    }

    return response
  } catch (error) {
    ragRetrievalState.error = error.message || 'RouterRAG检索失败'
    throw error
  } finally {
    ragRetrievalState.loading = false
  }
}

const retrieveUniversalRAG = async (params = {}) => {
  ragRetrievalState.loading = true
  ragRetrievalState.error = ''
  ragRetrievalState.results = []
  ragRetrievalState.total = 0
  ragRetrievalState.raw_total = 0

  try {
    const response = await callApi('/api/rag/universal/retrieve', {
      method: 'POST',
      body: JSON.stringify({
        query: params.query || ragSearchForm.query,
        topic: params.topic || ragSearchForm.topic,
        rag_type: params.rag_type || 'tagrag',
        project: params.project || activeProjectName.value || undefined,
        top_k: params.top_k || ragSearchForm.top_k,
        threshold: params.threshold || ragSearchForm.threshold
      })
    })

    ragRetrievalState.results = response?.data?.results || []
    ragRetrievalState.total = response?.data?.total || 0
    ragRetrievalState.raw_total = response?.data?.raw_total ?? ragRetrievalState.total
    ragRetrievalState.summary = response?.data?.summary || ''

    if (response?.status === 'building') {
      ragRetrievalState.error = response?.message || '正在准备检索资料，请稍后再试'
      const ragType = params.rag_type || 'tagrag'
      updateCacheState({ ...response.data, type: ragType, topic: params.topic || ragSearchForm.topic })
      await pollRagCacheStatus(ragType, params.topic || ragSearchForm.topic)
    }

    return response
  } catch (error) {
    ragRetrievalState.error = error.message || '检索失败'
    throw error
  } finally {
    ragRetrievalState.loading = false
  }
}

const fetchRouterRlhfStats = async (params = {}) => {
  ragRlhfStatsState.loading = true
  ragRlhfStatsState.error = ''
  ragRlhfStatsState.data = null
  try {
    const topic = String(params.topic || ragRlhfForm.topic || ragSearchForm.topic || '').trim()
    if (!topic) throw new Error('请先选择专题')

    const query = new URLSearchParams({
      topic,
      limit: String(Number(params.limit || ragRlhfForm.limit || 1000))
    })
    const expTag = String(params.experiment_tag ?? ragRlhfForm.experiment_tag ?? '').trim()
    if (expTag) query.set('experiment_tag', expTag)

    const response = await callApi(`/api/rag/routerrag/rlhf/stats?${query.toString()}`, { method: 'GET' })
    ragRlhfStatsState.data = response?.data || null
    ragRlhfForm.topic = topic
    return response
  } catch (error) {
    ragRlhfStatsState.error = error.message || '获取RLHF统计失败'
    throw error
  } finally {
    ragRlhfStatsState.loading = false
  }
}

const tuneRouterRlhf = async (params = {}) => {
  ragRlhfTuneState.loading = true
  ragRlhfTuneState.error = ''
  ragRlhfTuneState.result = null
  try {
    const topic = String(params.topic || ragRlhfForm.topic || ragSearchForm.topic || '').trim()
    if (!topic) throw new Error('请先选择专题')
    const response = await callApi('/api/rag/routerrag/rlhf/tune', {
      method: 'POST',
      body: JSON.stringify({
        topic,
        experiment_tag: String(params.experiment_tag ?? ragRlhfForm.experiment_tag ?? '').trim() || undefined,
        limit: Number(params.limit || ragRlhfForm.limit || 1000),
        apply: Boolean(params.apply),
        operator: params.operator || 'frontend'
      })
    })
    ragRlhfTuneState.result = response?.data || null
    ragRlhfForm.topic = topic
    if (ragRlhfTuneState.result?.stats) {
      ragRlhfStatsState.data = ragRlhfTuneState.result.stats
    }
    return response
  } catch (error) {
    ragRlhfTuneState.error = error.message || 'RLHF调参失败'
    throw error
  } finally {
    ragRlhfTuneState.loading = false
  }
}

const submitRouterRAGFeedback = async (params = {}) => {
  ragFeedbackState.loading = true
  ragFeedbackState.error = ''
  ragFeedbackState.success = ''
  try {
    const topic = String(params.topic || ragSearchForm.topic || '').trim()
    const question = String(params.question || ragSearchForm.query || '').trim()
    if (!topic) throw new Error('请先选择专题')
    if (!question) throw new Error('请先输入问题后再提交反馈')

    const response = await callApi('/api/rag/routerrag/feedback', {
      method: 'POST',
      body: JSON.stringify({
        topic,
        trace_id: params.trace_id || '',
        experiment_tag: String(params.experiment_tag || '').trim() || 'default',
        question,
        question_type: params.question_type || '',
        scores: params.scores || {},
        bad_reason: String(params.bad_reason || '').trim(),
        note: String(params.note || '').trim(),
        operator: params.operator || 'frontend'
      })
    })
    ragFeedbackState.success = '反馈已提交'
    return response
  } catch (error) {
    ragFeedbackState.error = error.message || '提交反馈失败'
    throw error
  } finally {
    ragFeedbackState.loading = false
  }
}

watch(activeProjectName, async (name) => {
  ragSearchForm.topic = ''
  ragTopicsState.options = []
  ragTopicsState.error = ''
  ragBuildForm.remote_topic = ''
  ragBuildForm.local_topic = ''
  ragBuildForm.build_topic = ''
  localTopicsState.options = []
  localTopicsState.error = ''
  if (name) {
    await loadRAGTopics()
    await loadRemoteTopics()
    await loadLocalTopics()
  }
})

export const useRAGTopics = () => {
  return {
    // States
    ragTopicsState,
    ragTopicOptions,
    tagragTopicOptions,
    routerTopicOptions,
    remoteTopicsState,
    remoteTopicOptions,
    localTopicsState,
    localTopicOptions,
    ragSearchForm,
    ragRetrievalState,
    ragCacheState,
    ragBuildState,
    ragBuildForm,
    ragImportState,
    ragRlhfForm,
    ragRlhfStatsState,
    ragRlhfTuneState,
    ragFeedbackState,

    // Methods
    loadRAGTopics,
    loadRemoteTopics,
    loadLocalTopics,
    buildRagTopic,
    importRouterRAGArtifacts,
    retrieveTagRAG,
    retrieveRouterRAG,
    retrieveUniversalRAG,
    fetchRouterRlhfStats,
    tuneRouterRlhf,
    submitRouterRAGFeedback
  }
}
