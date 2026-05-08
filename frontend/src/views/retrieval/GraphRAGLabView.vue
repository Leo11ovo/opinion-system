<template>
  <div class="min-h-screen pb-20">
    <!-- Top accent bar -->
    <div class="h-1 w-full bg-gradient-to-r from-brand-300 via-accent-400 to-accent-500"></div>

    <main class="mx-auto max-w-6xl px-6 pt-8">
      <!-- Header -->
      <header class="mb-8 overflow-hidden rounded-2xl border border-soft bg-surface shadow-sm">
        <div class="flex flex-col gap-5 px-6 py-6 lg:flex-row lg:items-start lg:justify-between">
          <div class="max-w-3xl">
            <div class="flex items-center gap-2">
              <div class="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-100">
                <svg class="h-4 w-4 text-brand-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <p class="panel-kicker">GraphRAG Console</p>
            </div>
            <h1 class="mt-3 text-3xl font-semibold tracking-tight text-primary">图谱检索实验室</h1>
            <p class="mt-2 text-sm leading-6 text-secondary">
              确认 Neo4j 图谱可用后，直接执行基于 Finding 的语义检索，支持证据追溯与回答摘要生成。
            </p>
          </div>

          <div class="grid shrink-0 gap-3 sm:grid-cols-3 lg:min-w-[400px]">
            <div class="metric-tile">
              <span class="metric-tile__icon">
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                </svg>
              </span>
              <span class="metric-tile__label">数据库</span>
              <strong class="metric-tile__value">{{ graphStatus.database || '默认库' }}</strong>
            </div>
            <div class="metric-tile">
              <span class="metric-tile__icon">
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </span>
              <span class="metric-tile__label">图谱状态</span>
              <strong class="metric-tile__value">{{ graphStatusLabel }}</strong>
            </div>
            <div class="metric-tile metric-tile--accent">
              <span class="metric-tile__icon">
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
              </span>
              <span class="metric-tile__label">Finding 命中</span>
              <strong class="metric-tile__value">{{ graphragFindingCount }}</strong>
            </div>
          </div>
        </div>
      </header>

      <section class="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside class="space-y-5">
          <!-- Neo4j Status Card -->
          <article class="card-surface overflow-hidden">
            <div class="border-b border-soft px-5 py-4">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <p class="panel-kicker">Status</p>
                  <h2 class="text-base font-semibold text-primary">图谱状态</h2>
                </div>
                <div class="flex items-center gap-1.5">
                  <span class="status-dot state-chip" :class="graphStateClass"></span>
                  <span class="state-chip text-xs" :class="graphStateClass">{{ graphStatusBadge }}</span>
                </div>
              </div>
            </div>

            <div class="space-y-2 px-5 py-4">
              <div class="info-row">
                <span class="info-row__label">连接</span>
                <span class="info-row__value">{{ graphConnectionLabel }}</span>
              </div>
              <div class="info-row">
                <span class="info-row__label">检索模式</span>
                <span class="info-row__value">{{ capabilityModeLabel }}</span>
              </div>
              <div class="info-row">
                <span class="info-row__label">Finding 节点</span>
                <span class="info-row__value">{{ graphStatus.has_findings ? '已存在' : '未发现' }}</span>
              </div>
              <div class="info-row">
                <span class="info-row__label">向量索引</span>
                <span class="info-row__value">{{ graphStatus.has_vector_indexes ? '已就绪' : '未创建' }}</span>
              </div>
            </div>

            <div class="px-5 pb-4">
              <div class="rounded-xl border border-soft bg-base-soft px-4 py-3">
                <p class="text-xs font-semibold uppercase tracking-[0.18em] text-muted mb-1">说明</p>
                <p class="text-sm leading-5 text-secondary">{{ graphStatusSummary }}</p>
              </div>
            </div>

            <div class="flex border-t border-soft px-5 py-3">
              <button
                type="button"
                class="btn-outline w-full justify-center text-sm"
                @click="loadGraphStatus"
                :disabled="graphStatusLoading"
              >
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {{ graphStatusLoading ? '刷新中...' : '刷新状态' }}
              </button>
            </div>
          </article>

          <!-- Build Panel -->
          <article v-if="showBuildPanel" class="card-surface overflow-hidden">
            <div class="border-b border-soft px-5 py-4">
              <div class="flex items-center gap-2">
                <p class="panel-kicker">Recovery</p>
                <h2 class="text-base font-semibold text-primary">导入 / 重建图谱</h2>
              </div>
            </div>

            <div class="space-y-3 px-5 py-4">
              <label class="field-block">
                <span class="field-label">专题名</span>
                <input v-model="buildForm.topic" class="input" placeholder="report_graph" />
              </label>

              <label class="field-block">
                <span class="field-label">报告目录</span>
                <input v-model="buildForm.local_source_dir" class="input" placeholder="backend/data/report_data" />
              </label>

              <label class="field-checkbox">
                <input v-model="buildForm.enable_llm_extraction" type="checkbox" class="field-checkbox__box" />
                <span class="field-checkbox__text">
                  <strong class="text-primary">启用 LLM 抽取</strong>
                  <span class="text-xs text-secondary">补建完整语义层，速度较慢</span>
                </span>
              </label>

              <button
                @click="buildGraphFromReports"
                :disabled="buildLoading"
                class="btn-primary w-full justify-center text-sm"
              >
                <svg v-if="buildLoading" class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                {{ buildLoading ? '执行中...' : '导入并构建图谱' }}
              </button>

              <div v-if="buildMsg" class="rounded-xl border border-brand-soft bg-brand-soft/40 px-4 py-3 text-sm text-secondary">
                {{ buildMsg }}
              </div>
            </div>
          </article>

          <!-- Query Panel -->
          <article class="card-surface overflow-hidden">
            <div class="border-b border-soft px-5 py-4">
              <div class="flex items-center gap-2">
                <p class="panel-kicker">Query</p>
                <h2 class="text-base font-semibold text-primary">检索参数</h2>
              </div>
            </div>

            <div class="space-y-3 px-5 py-4">
              <label class="field-block">
                <span class="field-label">专题</span>
                <select v-model="form.topic" class="input">
                  <option value="">全部专题</option>
                  <option v-for="topic in topicOptions" :key="topic.name" :value="topic.name">{{ topic.label }}</option>
                </select>
              </label>

              <label class="field-block">
                <span class="field-label">问题类型</span>
                <select v-model="form.question_type" class="input">
                  <option value="fact">fact — 事实型</option>
                  <option value="explain">explain — 解释型</option>
                  <option value="compare">compare — 对比型</option>
                  <option value="decision">decision — 决策型</option>
                  <option value="explore">explore — 探索型</option>
                </select>
              </label>

              <label class="field-block">
                <span class="field-label">问题描述</span>
                <textarea
                  v-model="form.query"
                  rows="4"
                  class="input min-h-[100px] resize-y"
                  placeholder="输入待检索的问题，例如：这份报告里最关键的风险判断是什么？"
                />
              </label>

              <div class="rounded-xl border border-soft bg-base-soft px-4 py-3">
                <div class="flex items-center gap-2 mb-1">
                  <svg class="h-3.5 w-3.5 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <p class="text-xs font-semibold text-primary">Neo4j Only</p>
                </div>
                <p class="text-xs text-secondary">纯图谱检索，不依赖 RouterRAG 本地向量。</p>
              </div>

              <button
                @click="runTest"
                :disabled="loading || !graphStatus.ready_for_query"
                class="btn-primary w-full justify-center text-sm"
              >
                <svg v-if="loading" class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                {{ loading ? '检索中...' : graphStatus.ready_for_query ? '运行检索' : '当前无可用图谱' }}
              </button>

              <p v-if="errorMsg" class="rounded-xl border border-danger-soft bg-danger-soft/50 px-4 py-3 text-sm text-danger">
                {{ errorMsg }}
              </p>
            </div>
          </article>
        </aside>

        <section class="space-y-5">
          <!-- Result Overview -->
          <article class="card-surface overflow-hidden">
            <div class="border-b border-soft px-5 py-4">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <p class="panel-kicker">Result</p>
                  <h2 class="text-base font-semibold text-primary">检索结果</h2>
                </div>
                <div class="flex items-center gap-2">
                  <span class="badge-muted text-xs">Neo4j</span>
                  <span class="badge-muted text-xs">{{ presetLabel }}</span>
                </div>
              </div>
            </div>

            <div class="px-5 py-4">
              <!-- Stats row -->
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div class="stat-pill">
                  <span class="stat-pill__num">{{ graphragFindingCount }}</span>
                  <span class="stat-pill__label">Findings</span>
                </div>
                <div class="stat-pill">
                  <span class="stat-pill__num">{{ graphragEvidenceCount }}</span>
                  <span class="stat-pill__label">证据项</span>
                </div>
                <div class="stat-pill">
                  <span class="stat-pill__num text-xs">{{ result.question_type || '—' }}</span>
                  <span class="stat-pill__label">问题类型</span>
                </div>
                <div class="stat-pill">
                  <span class="stat-pill__num text-xs truncate max-w-[80px]">{{ result.topic || form.topic || '全部' }}</span>
                  <span class="stat-pill__label">专题</span>
                </div>
              </div>

              <!-- Summary block -->
              <div class="relative mt-4 overflow-hidden rounded-xl border border-soft bg-base-soft">
                <div class="accent-bar"></div>
                <div class="px-5 py-4">
                  <div class="flex items-center gap-2 mb-2">
                    <svg class="h-4 w-4 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <h3 class="text-sm font-semibold text-primary">回答摘要</h3>
                  </div>
                  <p class="whitespace-pre-wrap text-sm leading-6 text-secondary">
                    {{ result.summary || '尚未生成回答摘要。运行检索后将自动生成。' }}
                  </p>
                </div>
              </div>
            </div>
          </article>

          <!-- Findings -->
          <article class="card-surface overflow-hidden">
            <div class="border-b border-soft px-5 py-4">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <p class="panel-kicker">Finding</p>
                  <h2 class="text-base font-semibold text-primary">关键 Finding</h2>
                </div>
                <span class="text-xs text-muted">前 {{ topFindings.length }} 条命中</span>
              </div>
            </div>

            <div class="px-5 py-4">
              <div v-if="topFindings.length" class="space-y-4">
                <article
                  v-for="(item, index) in topFindings"
                  :key="item.finding_id || `${index}-${item.finding_title}`"
                  class="finding-card"
                >
                  <!-- Header row -->
                  <div class="flex items-start gap-3">
                    <div class="finding-rank">{{ index + 1 }}</div>
                    <div class="min-w-0 flex-1">
                      <h3 class="text-sm font-semibold text-primary leading-snug">
                        {{ item.finding_title || item.finding_id || '未命名 Finding' }}
                      </h3>
                      <p class="mt-1.5 text-xs leading-5 text-secondary">
                        {{ item.finding_statement || '暂无 statement 内容。' }}
                      </p>
                    </div>
                    <!-- Score bar -->
                    <div class="shrink-0 w-14 text-right">
                      <div class="score-bar-track">
                        <div class="score-bar-fill" :style="{ width: Math.round(Number(item.score || 0) * 100) + '%' }"></div>
                      </div>
                      <span class="mt-1 block text-xs font-mono font-semibold text-primary">{{ formatScore(item.score) }}</span>
                    </div>
                  </div>

                  <!-- Sub scores row -->
                  <div class="mt-3 flex items-center gap-4">
                    <div class="sub-score">
                      <span class="sub-score__label">graph</span>
                      <span class="sub-score__val">{{ formatScore(item.graph_score) }}</span>
                    </div>
                    <div class="sub-score">
                      <span class="sub-score__label">evidence</span>
                      <span class="sub-score__val">{{ formatScore(item.evidence_score) }}</span>
                    </div>
                    <div class="ml-auto flex flex-wrap gap-1">
                      <span v-for="t in (item.topics || []).slice(0,2)" :key="'t-'+t" class="tag-chip">{{ t }}</span>
                      <span v-for="e in (item.events || []).slice(0,2)" :key="'e-'+e" class="tag-chip tag-chip--accent">{{ e }}</span>
                    </div>
                  </div>

                  <!-- Evidence detail (collapsed by default) -->
                  <details class="mt-3 group/section">
                    <summary class="cursor-pointer text-xs text-muted hover:text-secondary list-none flex items-center gap-1">
                      <svg class="h-3 w-3 transition-transform group-hover/section:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                      证据详情
                    </summary>
                    <div class="mt-2 grid gap-2 sm:grid-cols-2">
                      <div class="evidence-box">
                        <p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mb-1">主题 / 事件 / 平台</p>
                        <p class="text-xs text-secondary"><strong class="text-primary">主题：</strong>{{ joinOrFallback(item.topics) }}</p>
                        <p class="text-xs text-secondary"><strong class="text-primary">事件：</strong>{{ joinOrFallback(item.events) }}</p>
                        <p class="text-xs text-secondary"><strong class="text-primary">平台：</strong>{{ joinOrFallback(item.platforms) }}</p>
                      </div>
                      <div class="evidence-box">
                        <p class="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted mb-1">建议 / Claim / 帖子</p>
                        <p class="text-xs text-secondary"><strong class="text-primary">建议：</strong>{{ joinOrFallback(item.recommendations) }}</p>
                        <p class="text-xs text-secondary"><strong class="text-primary">Claim：</strong>{{ joinOrFallback(item.claims) }}</p>
                        <p class="text-xs text-secondary"><strong class="text-primary">帖子：</strong>{{ joinOrFallback(item.post_titles) }}</p>
                      </div>
                    </div>
                  </details>
                </article>
              </div>

              <!-- Empty state -->
              <div v-else class="flex flex-col items-center justify-center rounded-xl border border-soft bg-base-soft py-10 text-center">
                <svg class="h-10 w-10 text-border-soft mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                <h3 class="text-sm font-semibold text-primary">暂无可展示的 Finding</h3>
                <p class="mt-1.5 text-xs leading-5 text-secondary max-w-xs">
                  当前问题没有命中 Finding，或图谱尚未形成足够的语义层。请先确认图谱状态，再决定是否导入或重建。
                </p>
              </div>
            </div>
          </article>

          <!-- Diagnostics -->
          <article class="card-surface overflow-hidden">
            <div class="border-b border-soft px-5 py-4">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <p class="panel-kicker">Diagnostics</p>
                  <h2 class="text-base font-semibold text-primary">诊断信息</h2>
                </div>
                <span class="text-xs text-muted">调试用</span>
              </div>
            </div>

            <div class="px-5 py-4 space-y-2">
              <details class="debug-block">
                <summary>图谱状态回包</summary>
                <pre>{{ graphStatusJson }}</pre>
              </details>
              <details class="debug-block">
                <summary>构图结果</summary>
                <pre>{{ buildCountsJson }}</pre>
              </details>
              <details class="debug-block">
                <summary>原始召回结果</summary>
                <pre>{{ retrievalJson }}</pre>
              </details>
            </div>
          </article>
        </section>
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
const graphStatusLoading = ref(false)
const errorMsg = ref('')
const buildMsg = ref('')
const buildStatus = ref(null)
const topicOptions = ref([])

const graphStatus = reactive({
  status: 'idle',
  configured: false,
  connected: false,
  database: '',
  counts: {},
  graph_capability: {},
  ready_for_query: false,
  has_findings: false,
  has_vector_indexes: false,
  message: '',
})

const form = reactive({
  topic: '',
  query: '',
  question_type: 'explain',
})

const buildForm = reactive({
  topic: '',
  local_source_dir: 'backend/data/report_data',
  enable_llm_extraction: false,
})

const result = reactive({
  trace_id: '',
  query_text: '',
  topic: '',
  question_type: '',
  graphrag: { findings: [], capability: {}, evidence: {} },
  diagnostics: {},
  summary: '',
})

const graphragFindings = computed(() => result.graphrag?.findings || [])
const graphragFindingCount = computed(() => graphragFindings.value.length)
const topFindings = computed(() => graphragFindings.value.slice(0, 5))

const graphragEvidenceCount = computed(() =>
  graphragFindings.value.reduce((sum, item) => {
    return (
      sum +
      (item.claim_ids || []).length +
      (item.chunk_ids || []).length +
      (item.post_ids || []).length +
      (item.events || []).length +
      (item.topics || []).length
    )
  }, 0)
)

const graphStatusJson = computed(() => JSON.stringify(graphStatus, null, 2))
const retrievalJson = computed(() =>
  JSON.stringify(
      {
        topic: result.topic,
        question_type: result.question_type,
        graphrag: result.graphrag,
        diagnostics: result.diagnostics,
      },
      null,
      2
  )
)
const buildCountsJson = computed(() => JSON.stringify(buildStatus.value || {}, null, 2))

const capabilityModeLabel = computed(() => {
  const mode = buildStatus.value?.graph_capability?.mode || graphStatus.graph_capability?.mode || result.graphrag?.capability?.mode || ''
  if (mode === 'full_graphrag') return '完整语义图'
  if (mode === 'structural_only') return '弱化图检索'
  if (mode === 'empty') return '空图谱'
  return '未识别'
})

const graphStatusLabel = computed(() => {
  if (!graphStatus.configured) return '未配置'
  if (!graphStatus.connected) return '未连通'
  if (!graphStatus.ready_for_query) return capabilityModeLabel.value
  return '可直接提问'
})

const graphStatusBadge = computed(() => {
  if (graphStatusLoading.value) return '检查中'
  if (!graphStatus.configured) return '未配置'
  if (!graphStatus.connected) return '连接失败'
  if (graphStatus.ready_for_query) return '可用'
  return '待导入'
})

const graphStateClass = computed(() => ({
  'state-chip--success': graphStatus.ready_for_query,
  'state-chip--warning': graphStatus.configured && graphStatus.connected && !graphStatus.ready_for_query,
  'state-chip--danger': graphStatus.configured && !graphStatus.connected,
  'state-chip--muted': !graphStatus.configured,
}))

const graphConnectionLabel = computed(() => {
  if (!graphStatus.configured) return 'Neo4j 未配置'
  if (!graphStatus.connected) return '连接失败'
  return '已连接'
})

const graphStatusSummary = computed(() => {
  if (!graphStatus.configured) return '未发现可用的 Neo4j 配置，请先检查 neo4j.yaml 或相关环境变量。'
  if (!graphStatus.connected) return graphStatus.message || '当前无法连接或读取 Neo4j 数据库。'
  return graphStatus.graph_capability?.summary || '图谱状态已读取，但没有更多说明。'
})

const graphActionHint = computed(() => {
  if (!graphStatus.configured) return '先修复 Neo4j 配置；只有配置和连接正常后，页面才能判断是否可直接检索。'
  if (!graphStatus.connected) return '先确认 Neo4j 服务是否在线，以及 database 配置是否可访问。'
  if (graphStatus.ready_for_query) return '当前数据库中已经有可用图谱，建议直接提问，不需要先执行重建。'
  return '当前数据库中没有足够的可检索图谱内容；如果你有报告目录，再执行一次导入或重建。'
})

const showBuildPanel = computed(() => !graphStatus.ready_for_query)
const presetLabel = computed(() => '纯 Neo4j GraphRAG')

const loadTopics = async () => {
  try {
    const resp = await callApi('/api/graph/topics', { method: 'GET' })
    const items = resp?.data?.topic_items || []
    const options = items.map((item) => {
      const counts = item?.counts || {}
      const size = Number(item?.size_hint || 0)
      const findingCount = Number(counts.findings || 0)
      const postCount = Number(counts.posts || 0)
      const reportCount = Number(counts.reports || 0)
      const detailParts = []
      if (findingCount) detailParts.push(`Finding ${findingCount}`)
      if (postCount) detailParts.push(`Post ${postCount}`)
      if (reportCount) detailParts.push(`Report ${reportCount}`)
      return {
        name: item.name,
        label: detailParts.length ? `${item.name} (${detailParts.join(' / ')})` : `${item.name} (${size})`,
        counts,
        sizeHint: size,
      }
    })
    topicOptions.value = options
  } catch (e) {
    topicOptions.value = []
    if (!errorMsg.value) {
      errorMsg.value = e.message || '图谱专题读取失败'
    }
  }
}

const loadGraphStatus = async () => {
  graphStatusLoading.value = true
  try {
    const resp = await callApi('/api/graph/status', { method: 'GET' })
    const data = resp?.data || resp || {}
    graphStatus.status = data.status || 'idle'
    graphStatus.configured = Boolean(data.configured)
    graphStatus.connected = Boolean(data.connected)
    graphStatus.database = data.database || ''
    graphStatus.counts = data.counts || {}
    graphStatus.graph_capability = data.graph_capability || {}
    graphStatus.ready_for_query = Boolean(data.ready_for_query)
    graphStatus.has_findings = Boolean(data.has_findings)
    graphStatus.has_vector_indexes = Boolean(data.has_vector_indexes)
    graphStatus.message = data.message || ''
  } catch (e) {
    graphStatus.status = 'error'
    graphStatus.configured = false
    graphStatus.connected = false
    graphStatus.database = ''
    graphStatus.counts = {}
    graphStatus.graph_capability = {}
    graphStatus.ready_for_query = false
    graphStatus.has_findings = false
    graphStatus.has_vector_indexes = false
    graphStatus.message = e.message || '图谱状态读取失败'
  } finally {
    graphStatusLoading.value = false
  }
}

const buildGraphFromReports = async () => {
  buildMsg.value = ''
  errorMsg.value = ''
  buildStatus.value = null
  const topic = (buildForm.topic || form.topic || '').trim()
  const localSourceDir = (buildForm.local_source_dir || '').trim()
  if (!topic || !localSourceDir) {
    buildMsg.value = '请先填写专题名和报告目录。'
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
      enable_llm_extraction: Boolean(buildForm.enable_llm_extraction),
    }
    const resp = await callApi('/api/graph/build', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    const data = resp?.data || resp || {}
    buildMsg.value = String(data?.graph_capability?.summary || data?.message || '图谱构建任务已提交')
    buildStatus.value = data
    form.topic = topic
    await Promise.all([loadGraphStatus(), loadTopics()])
  } catch (e) {
    buildMsg.value = e.message || '图谱构建失败'
  } finally {
    buildLoading.value = false
  }
}

const runTest = async () => {
  errorMsg.value = ''
  if (!form.query) {
    errorMsg.value = '请先填写问题。'
    return
  }
  loading.value = true
  try {
    const payload = {
      topic: form.topic,
      query: form.query,
      question_type: form.question_type,
      top_k: 5,
    }
    const resp = await callApi('/api/graph/retrieve', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    const data = resp?.data || {}
    result.trace_id = ''
    result.query_text = data.query_text || form.query
    result.topic = data.topic || form.topic
    result.question_type = form.question_type
    result.graphrag = data.graphrag || { findings: [], capability: {}, evidence: {} }
    result.diagnostics = data.diagnostics || {}
    result.summary = data.summary || data.graphrag?.capability?.summary || ''
  } catch (e) {
    errorMsg.value = e.message || '检索失败'
  } finally {
    loading.value = false
  }
}

const joinOrFallback = (items) => {
  if (!Array.isArray(items) || !items.length) return '暂无'
  return items.filter(Boolean).join('，') || '暂无'
}

const formatScore = (value) => {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(2) : '--'
}

onMounted(async () => {
  await Promise.allSettled([loadTopics(), loadGraphStatus()])
})
</script>

<style scoped>
/* ── Panel kicker ── */
.panel-kicker {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3em;
  color: var(--color-text-muted);
}

/* ── Metric tiles (header) ── */
.metric-tile {
  border: 1px solid var(--color-border-soft);
  border-radius: 1rem;
  background-color: var(--color-bg-base-soft);
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.metric-tile:hover {
  box-shadow: 0 2px 8px rgb(15 23 42 / 0.06);
  border-color: rgb(var(--color-brand-200) / 0.8);
}
.metric-tile--accent {
  background-color: rgb(var(--color-brand-50) / 0.6);
  border-color: rgb(var(--color-brand-200) / 0.6);
}
.metric-tile__icon {
  color: rgb(var(--color-brand-500) / 1);
  margin-bottom: 0.1rem;
}
.metric-tile__label {
  display: block;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.22em;
  color: var(--color-text-muted);
}
.metric-tile__value {
  display: block;
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Info rows (status card) ── */
.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid rgb(var(--color-border-soft) / 0.5);
}
.info-row:last-child {
  border-bottom: none;
}
.info-row__label {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
.info-row__value {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

/* ── State chip & dot ── */
.state-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 0.2rem 0.6rem;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.state-chip--success,
.state-chip--success.state-chip {
  background-color: rgb(var(--color-success-100) / 1);
  color: rgb(var(--color-success-700) / 1);
}
.state-chip--warning,
.state-chip--warning.state-chip {
  background-color: rgb(var(--color-warning-100) / 1);
  color: rgb(var(--color-warning-700) / 1);
}
.state-chip--danger,
.state-chip--danger.state-chip {
  background-color: rgb(var(--color-danger-100) / 1);
  color: rgb(var(--color-danger-700) / 1);
}
.state-chip--muted,
.state-chip--muted.state-chip {
  background-color: rgb(var(--color-brand-100) / 1);
  color: var(--color-text-secondary);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background-color: var(--color-border-soft) !important;
}
.status-dot.state-chip--success {
  background-color: rgb(var(--color-success-500) / 1) !important;
}
.status-dot.state-chip--warning {
  background-color: rgb(var(--color-warning-500) / 1) !important;
}
.status-dot.state-chip--danger {
  background-color: rgb(var(--color-danger-500) / 1) !important;
}
.status-dot.state-chip--muted {
  background-color: var(--color-border-soft) !important;
}

/* ── Field helpers ── */
.field-block {
  display: block;
}
.field-label {
  display: block;
  margin-bottom: 0.375rem;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--color-text-secondary);
}
.field-checkbox {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  cursor: pointer;
}
.field-checkbox__box {
  margin-top: 0.1rem;
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  border-radius: 0.25rem;
  border: 1px solid var(--color-border-soft);
  accent-color: var(--color-brand-700-hex);
  cursor: pointer;
}
.field-checkbox__text {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.field-checkbox__text strong {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-primary);
}
.field-checkbox__text span {
  font-size: 0.75rem;
  line-height: 1.4;
}

/* ── Buttons ── */
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border-radius: 9999px;
  border: none;
  padding: 0.5rem 1.25rem;
  font-weight: 600;
  font-size: 0.875rem;
  background-color: var(--color-brand-700-hex);
  color: #ffffff;
  cursor: pointer;
  transition: background-color 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}
.btn-primary:hover:not(:disabled) {
  background-color: var(--color-brand-500-hex);
  box-shadow: 0 3px 10px rgb(15 23 42 / 0.15);
}
.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-outline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border-radius: 9999px;
  border: 1px solid var(--color-border-soft);
  padding: 0.4rem 1rem;
  font-weight: 500;
  font-size: 0.875rem;
  background-color: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease, color 0.2s ease;
}
.btn-outline:hover:not(:disabled) {
  border-color: rgb(var(--color-brand-300) / 1);
  background-color: rgb(var(--color-brand-50) / 0.5);
  color: var(--color-text-primary);
}
.btn-outline:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ── Stat pills (result overview) ── */
.stat-pill {
  display: flex;
  flex-direction: column;
  align-items: center;
  border: 1px solid var(--color-border-soft);
  border-radius: 0.875rem;
  background-color: var(--color-bg-base-soft);
  padding: 0.625rem 0.5rem;
  gap: 0.15rem;
}
.stat-pill__num {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1;
}
.stat-pill__label {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--color-text-muted);
}

/* ── Accent bar summary ── */
.accent-bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(to bottom, rgb(var(--color-brand-400) / 1), rgb(var(--color-accent-400) / 1));
  border-radius: 3px 0 0 3px;
}

/* ── Finding card ── */
.finding-card {
  border: 1px solid var(--color-border-soft);
  border-radius: 1rem;
  background-color: var(--color-surface);
  padding: 1rem;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.finding-card:hover {
  box-shadow: 0 4px 16px rgb(15 23 42 / 0.07);
  border-color: rgb(var(--color-brand-200) / 0.8);
}

.finding-rank {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: linear-gradient(135deg, rgb(var(--color-brand-500) / 1), rgb(var(--color-accent-400) / 1));
  color: #fff;
  font-size: 0.7rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.score-bar-track {
  height: 4px;
  border-radius: 9999px;
  background-color: var(--color-surface-muted);
  overflow: hidden;
}
.score-bar-fill {
  height: 100%;
  border-radius: 9999px;
  background: linear-gradient(to right, rgb(var(--color-brand-400) / 1), rgb(var(--color-accent-500) / 1));
  transition: width 0.4s ease;
}

.sub-score {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.sub-score__label {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--color-text-muted);
}
.sub-score__val {
  font-size: 0.75rem;
  font-weight: 600;
  font-family: ui-monospace, monospace;
  color: var(--color-text-secondary);
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 0.1rem 0.5rem;
  font-size: 0.65rem;
  font-weight: 500;
  background-color: rgb(var(--color-brand-100) / 0.8);
  color: rgb(var(--color-brand-700) / 1);
  border: 1px solid rgb(var(--color-brand-200) / 0.6);
}
.tag-chip--accent {
  background-color: rgb(var(--color-accent-100) / 0.8);
  color: rgb(var(--color-accent-700) / 1);
  border-color: rgb(var(--color-accent-200) / 0.6);
}

.evidence-box {
  border: 1px solid rgb(var(--color-border-soft) / 0.6);
  border-radius: 0.75rem;
  background-color: var(--color-bg-base-soft);
  padding: 0.6rem 0.75rem;
}

/* ── Debug blocks ── */
.debug-block {
  border: 1px solid var(--color-border-soft);
  border-radius: 0.875rem;
  background-color: var(--color-bg-base-soft);
  padding: 0.6rem 0.875rem;
}
.debug-block summary {
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--color-text-secondary);
  list-style: none;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.debug-block summary::before {
  content: '';
  display: inline-block;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 4px 0 4px 6px;
  border-color: transparent transparent transparent var(--color-text-muted);
  transition: transform 0.15s ease;
}
details[open] .debug-block summary::before {
  transform: rotate(90deg);
}
.debug-block pre {
  margin-top: 0.6rem;
  max-height: 14rem;
  overflow: auto;
  border-radius: 0.75rem;
  padding: 0.75rem;
  font-size: 0.7rem;
  line-height: 1.5rem;
  background: var(--color-text-primary);
  color: var(--color-surface);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* ── Misc shared ── */
.card-surface {
  border: 1px solid var(--color-border-soft);
  border-radius: 1.25rem;
  background-color: var(--color-surface);
  box-shadow: 0 1px 3px rgb(15 23 42 / 0.04);
}

.badge-muted {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.7rem;
  font-weight: 500;
  background-color: rgb(var(--color-accent-100) / 0.7);
  color: var(--color-text-secondary);
  border: 1px solid rgb(var(--color-accent-200) / 0.5);
}
</style>
