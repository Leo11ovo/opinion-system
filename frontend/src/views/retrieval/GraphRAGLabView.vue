<template>
  <div class="min-h-screen pb-16">
    <main class="mx-auto max-w-6xl px-6 pt-8">
      <header class="mb-6">
        <h1 class="text-2xl font-bold text-gray-900">Neo4j GraphRAG 测试台</h1>
        <p class="mt-1 text-sm text-gray-500">只看三件事：查询、召回、生成。</p>
      </header>

      <section class="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <h2 class="mb-4 text-lg font-semibold text-gray-900">运行一次测试</h2>
        <div class="mb-4 rounded-xl border border-blue-100 bg-blue-50/40 p-4">
          <h3 class="text-sm font-semibold text-gray-900">先构建图谱（报告目录 -> Neo4j）</h3>
          <div class="mt-3 grid gap-3 md:grid-cols-3">
            <label class="text-sm md:col-span-1">
              <span class="mb-1 block text-gray-600">构建专题名</span>
              <input v-model="buildForm.topic" class="w-full rounded-lg border border-gray-300 px-3 py-2" placeholder="例如 report_graph" />
            </label>
            <label class="text-sm md:col-span-2">
              <span class="mb-1 block text-gray-600">报告目录</span>
              <input v-model="buildForm.local_source_dir" class="w-full rounded-lg border border-gray-300 px-3 py-2" placeholder="backend/data/report_data" />
            </label>
            <label class="flex items-center gap-2 text-sm text-gray-700 md:col-span-2">
              <input v-model="buildForm.enable_llm_extraction" type="checkbox" class="h-4 w-4 rounded border-gray-300" />
              开启 LLM 抽取（完整 GraphRAG，更细但更慢）
            </label>
            <div class="md:col-span-1">
              <button
                @click="buildGraphFromReports"
                :disabled="buildLoading"
                class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {{ buildLoading ? '构建中...' : '构建 Neo4j 图谱' }}
              </button>
            </div>
          </div>
          <p v-if="buildMsg" class="mt-2 text-xs text-gray-700">{{ buildMsg }}</p>
          <div v-if="buildStatus" class="mt-3 space-y-3 text-xs text-gray-700">
            <div class="rounded-lg border border-gray-200 bg-white p-3">
              <div><strong>构建模式：</strong>{{ buildStatus.graph_capability?.mode || '-' }}</div>
              <div><strong>状态说明：</strong>{{ buildStatus.graph_capability?.summary || '-' }}</div>
              <div><strong>抽取模式：</strong>{{ buildStatus.extraction?.mode || '-' }}</div>
              <div><strong>弱化模式：</strong>{{ String(Boolean(buildStatus.graph_capability?.is_degraded)) }}</div>
            </div>
            <div class="rounded-lg border border-gray-200 bg-white p-3">
              <div><strong>节点计数：</strong></div>
              <pre class="mt-2 max-h-40 overflow-auto rounded bg-gray-900 p-2 text-[11px] text-gray-100">{{ buildCountsJson }}</pre>
            </div>
            <div class="rounded-lg border border-gray-200 bg-white p-3">
              <div><strong>向量回填 / 索引：</strong></div>
              <pre class="mt-2 max-h-56 overflow-auto rounded bg-gray-900 p-2 text-[11px] text-gray-100">{{ buildVectorJson }}</pre>
            </div>
          </div>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="text-sm">
            <span class="mb-1 block text-gray-600">专题</span>
            <select v-model="form.topic" class="w-full rounded-lg border border-gray-300 px-3 py-2">
              <option value="" disabled>请选择专题</option>
              <option v-for="topic in topicOptions" :key="topic" :value="topic">{{ topic }}</option>
            </select>
          </label>

          <label class="text-sm">
            <span class="mb-1 block text-gray-600">或手填专题</span>
            <input v-model="form.topic" class="w-full rounded-lg border border-gray-300 px-3 py-2" placeholder="可直接输入专题名" />
          </label>

          <label class="text-sm">
            <span class="mb-1 block text-gray-600">模式</span>
            <select v-model="form.mode" class="w-full rounded-lg border border-gray-300 px-3 py-2">
              <option value="mixed">mixed（推荐）</option>
              <option value="graphrag">graphrag（Neo4j）</option>
              <option value="normalrag">normalrag</option>
              <option value="tagrag">tagrag</option>
            </select>
          </label>

          <label class="text-sm">
            <span class="mb-1 block text-gray-600">问题类型</span>
            <select v-model="form.question_type" class="w-full rounded-lg border border-gray-300 px-3 py-2">
              <option value="fact">fact</option>
              <option value="explain">explain</option>
              <option value="compare">compare</option>
              <option value="decision">decision</option>
              <option value="explore">explore</option>
            </select>
          </label>

          <label class="text-sm">
            <span class="mb-1 block text-gray-600">实验标签</span>
            <input v-model="form.experiment_tag" class="w-full rounded-lg border border-gray-300 px-3 py-2" />
          </label>

          <label class="text-sm md:col-span-2">
            <span class="mb-1 block text-gray-600">问题</span>
            <input v-model="form.query" class="w-full rounded-lg border border-gray-300 px-3 py-2" placeholder="输入你要测试的问题" />
          </label>

          <label class="flex items-center gap-2 text-sm text-gray-700 md:col-span-2">
            <input v-model="form.use_question_preset" type="checkbox" class="h-4 w-4 rounded border-gray-300" />
            使用问题类型预设参数
          </label>
        </div>

        <div class="mt-4 flex items-center gap-3">
          <button
            @click="runTest"
            :disabled="loading"
            class="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {{ loading ? '运行中...' : '运行测试' }}
          </button>
          <span v-if="result.trace_id" class="text-xs text-gray-500">trace_id: {{ result.trace_id }}</span>
        </div>
        <p v-if="errorMsg" class="mt-3 text-sm text-red-600">{{ errorMsg }}</p>
      </section>

      <section class="mt-6 grid gap-4 lg:grid-cols-3">
        <article class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 class="text-base font-semibold text-gray-900">1) 查询</h3>
          <div class="mt-3 space-y-2 text-sm text-gray-700">
            <div><strong>原始问题：</strong>{{ result.query_text || '-' }}</div>
            <div><strong>生效问题：</strong>{{ result.query_rewrite?.effective || result.expanded_query || '-' }}</div>
            <div><strong>问题类型：</strong>{{ result.question_type || '-' }}</div>
            <div><strong>预设已应用：</strong>{{ String(Boolean(result.preset_applied)) }}</div>
            <div><strong>时间过滤：</strong>{{ result.time_filter?.time_text || '无' }}</div>
          </div>
        </article>

        <article class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 class="text-base font-semibold text-gray-900">2) 召回</h3>
          <div class="mt-3 space-y-2 text-sm text-gray-700">
            <div><strong>normalrag：</strong>{{ (result.normalrag?.sentences || []).length }} 条</div>
            <div><strong>tagrag：</strong>{{ (result.tagrag?.text_blocks || []).length }} 条</div>
            <div><strong>GraphRAG Finding：</strong>{{ graphragFindingCount }} 条</div>
            <div><strong>GraphRAG 证据：</strong>{{ graphragEvidenceCount }} 项</div>
            <div><strong>GraphRAG 弱化模式：</strong>{{ String(Boolean(result.graphrag?.capability?.is_degraded)) }}</div>
          </div>
          <details class="mt-3">
            <summary class="cursor-pointer text-xs text-brand-600">查看召回明细</summary>
            <pre class="mt-2 max-h-56 overflow-auto rounded bg-gray-900 p-2 text-[11px] text-gray-100">{{ retrievalJson }}</pre>
          </details>
        </article>

        <article class="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 class="text-base font-semibold text-gray-900">3) 生成</h3>
          <div class="mt-3 rounded-lg bg-gray-50 p-3 text-sm text-gray-700 whitespace-pre-wrap min-h-[140px]">
            {{ result.summary || '暂无生成结果（检查是否启用了 LLM summary）' }}
          </div>
        </article>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useApiBase } from '../../composables/useApiBase'
import { useActiveProject } from '../../composables/useActiveProject'

const { callApi } = useApiBase()
const { activeProjectName } = useActiveProject()

const loading = ref(false)
const buildLoading = ref(false)
const errorMsg = ref('')
const buildMsg = ref('')
const buildStatus = ref(null)
const topicOptions = ref([])

const form = reactive({
  topic: '',
  query: '',
  mode: 'mixed',
  question_type: 'explain',
  experiment_tag: 'baseline',
  use_question_preset: true
})

const buildForm = reactive({
  topic: '',
  local_source_dir: 'backend/data/report_data',
  enable_llm_extraction: false
})

const result = reactive({
  trace_id: '',
  query_text: '',
  expanded_query: '',
  query_rewrite: {},
  question_type: '',
  preset_applied: false,
  time_filter: {},
  normalrag: { sentences: [] },
  tagrag: { text_blocks: [] },
  graphrag: { findings: [], capability: {}, evidence: {} },
  summary: ''
})

const graphragFindingCount = computed(() => (result.graphrag?.findings || []).length)

const graphragEvidenceCount = computed(() => {
  const findings = result.graphrag?.findings || []
  return findings.reduce((sum, item) => {
    return sum + (item.claim_ids || []).length + (item.chunk_ids || []).length + (item.post_ids || []).length + (item.events || []).length + (item.topics || []).length
  }, 0)
})

const retrievalJson = computed(() =>
  JSON.stringify(
    {
      graphrag: result.graphrag,
      normalrag: result.normalrag,
      tagrag: result.tagrag
    },
    null,
    2
  )
)

const buildCountsJson = computed(() => JSON.stringify(buildStatus.value?.counts || {}, null, 2))
const buildVectorJson = computed(() => JSON.stringify(buildStatus.value?.vector_backfill || {}, null, 2))

const loadTopics = async () => {
  const params = new URLSearchParams()
  if (activeProjectName.value) {
    params.set('project', activeProjectName.value)
  }
  const path = params.toString() ? `/api/rag/topics?${params.toString()}` : '/api/rag/topics'
  const resp = await callApi(path, { method: 'GET' })
  const options = resp?.data?.router_topics || []
  topicOptions.value = options
  if (!form.topic && options.length > 0) {
    form.topic = options[0]
  }
}

const buildGraphFromReports = async () => {
  buildMsg.value = ''
  errorMsg.value = ''
  buildStatus.value = null
  const topic = (buildForm.topic || form.topic || '').trim()
  const localSourceDir = (buildForm.local_source_dir || '').trim()
  if (!topic || !localSourceDir) {
    buildMsg.value = '请先填写构建专题名和报告目录。'
    return
  }
  buildLoading.value = true
  try {
    const payload = {
      topic,
      project: activeProjectName.value || topic,
      date: 'report_data',
      local_source_dir: localSourceDir,
      init_schema_if_missing: true,
      enable_entity_extraction: true,
      enable_chunk_embedding: true,
      enable_llm_extraction: Boolean(buildForm.enable_llm_extraction)
    }
    const resp = await callApi('/api/graph/build', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
    const data = resp?.data || resp || {}
    const msg = data?.graph_capability?.summary || data?.message || '图谱构建任务已提交'
    buildMsg.value = String(msg)
    buildStatus.value = data
    form.topic = topic
    await loadTopics()
  } catch (e) {
    buildMsg.value = e.message || '图谱构建失败'
  } finally {
    buildLoading.value = false
  }
}

const runTest = async () => {
  errorMsg.value = ''
  if (!form.topic || !form.query) {
    errorMsg.value = '请先填写专题和问题。'
    return
  }
  loading.value = true
  try {
    const payload = {
      topic: form.topic,
      query: form.query,
      mode: form.mode,
      question_type: form.question_type,
      experiment_tag: form.experiment_tag,
      use_question_preset: form.use_question_preset
    }
    const resp = await callApi('/api/rag/routerrag/retrieve', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
    const data = resp?.data || {}
    result.trace_id = data.trace_id || ''
    result.query_text = data.query_text || form.query
    result.expanded_query = data.expanded_query || ''
    result.query_rewrite = data.query_rewrite || {}
    result.question_type = data.question_type || form.question_type
    result.preset_applied = Boolean(data.preset_applied)
    result.time_filter = data.time_filter || {}
    result.normalrag = data.normalrag || { sentences: [] }
    result.tagrag = data.tagrag || { text_blocks: [] }
    result.graphrag = data.graphrag || { findings: [], capability: {}, evidence: {} }
    result.summary = data.summary || ''
  } catch (e) {
    errorMsg.value = e.message || '运行失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadTopics)
</script>
