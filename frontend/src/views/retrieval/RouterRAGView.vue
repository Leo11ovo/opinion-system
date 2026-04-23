<template>
  <div class="min-h-screen pb-20">
    <main class="mx-auto max-w-4xl px-6 pt-8">
      <div class="mb-6 flex justify-end">
        <button @click="showManageModal = true"
          class="group flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:border-brand-300 hover:text-brand-600 active:bg-gray-50">
          <svg class="h-4 w-4 text-gray-400 transition group-hover:text-brand-500" fill="none" viewBox="0 0 24 24"
            stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span>库管理</span>
        </button>
      </div>

      <!-- 1. 搜索核心区 -->
      <section class="mb-10 text-center">
        <h2 class="mb-5 text-2xl font-extrabold text-gray-900 sm:text-3xl">
          你想查找什么内容？
        </h2>

        <form @submit.prevent="handleSearch" class="relative mx-auto max-w-2xl">
          <div
            class="group relative flex items-center overflow-hidden rounded-2xl bg-base-soft/90 p-2 ring-1 ring-brand-100/50 transition focus-within:ring-2 focus-within:ring-brand-500/20">
            <div class="relative flex items-center border-r border-gray-100 pr-2">
              <AppSelect
                :options="searchTopicSelectOptions"
                :value="ragSearchForm.topic"
                @change="ragSearchForm.topic = $event"
              />
            </div>

            <input v-model="ragSearchForm.query" type="text"
              class="flex-1 border-none bg-transparent px-4 py-3 text-lg text-primary placeholder:text-muted/70 focus:outline-none focus:ring-0"
              placeholder="输入关键词，例如：'数据安全规范'..." required />

            <button type="submit" :disabled="ragRetrievalState.loading || !ragSearchForm.query || !ragSearchForm.topic"
              class="ml-2 rounded-xl bg-brand-600 px-6 py-3 font-semibold text-white shadow-md transition hover:bg-brand-700 hover:shadow-lg disabled:cursor-not-allowed disabled:bg-gray-300 disabled:shadow-none">
              <svg v-if="ragRetrievalState.loading" class="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z">
                </path>
              </svg>
              <span v-else>搜索</span>
            </button>
          </div>

          <div class="mt-4 flex flex-wrap items-center justify-center gap-6 text-sm text-gray-500">
            <label class="flex items-center gap-2">
              <span class="text-xs font-medium">相似度阈值: {{ ragSearchForm.threshold }}</span>
              <input v-model.number="ragSearchForm.threshold" type="range" min="0" max="1" step="0.05"
                class="h-1.5 w-24 cursor-pointer appearance-none rounded-lg bg-gray-200 accent-brand-600" />
            </label>
            <label class="flex items-center gap-2">
              <span class="text-xs font-medium">Top-K:</span>
              <input v-model.number="ragSearchForm.top_k" type="number" min="1" max="20"
                class="input w-16 px-2 py-1.5 text-center text-xs" />
            </label>
          </div>

          <div class="mt-4 flex flex-wrap items-center justify-center gap-2">
            <button v-for="mode in retrievalModes" :key="mode.value" type="button"
              @click="ragSearchForm.rag_type = mode.value" :class="[
                'rounded-full px-3 py-1 text-xs font-medium transition',
                ragSearchForm.rag_type === mode.value
                  ? 'bg-brand-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              ]">
              {{ mode.label }}
            </button>
          </div>

          <div class="mt-3 flex items-center justify-center gap-3 text-xs">
            <span class="font-medium text-gray-500">检索策略：</span>
            <button type="button" @click="pureMode = true" :class="[
              'rounded-full px-3 py-1 font-medium transition',
              pureMode ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            ]">
              纯净检索（推荐做评测）
            </button>
            <button type="button" @click="pureMode = false" :class="[
              'rounded-full px-3 py-1 font-medium transition',
              !pureMode ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            ]">
              增强检索（默认）
            </button>
          </div>
        </form>

        <div v-if="ragRetrievalState.error" class="mx-auto mt-4 max-w-lg rounded-lg bg-red-50 p-3 text-sm text-red-600">
          {{ ragRetrievalState.error }}
        </div>
      </section>

      <section class="mb-8 rounded-2xl border border-indigo-100 bg-indigo-50/40 p-5">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-base font-bold text-gray-900">RLHF 自动调参</h3>
          <span class="text-xs text-indigo-700">基于反馈数据自动给出检索参数建议</span>
        </div>

        <div class="grid gap-3 sm:grid-cols-4">
          <label class="text-xs text-gray-600">
            专题
            <input v-model.trim="ragRlhfForm.topic" type="text" placeholder="默认使用当前检索专题"
              class="mt-1 w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
          </label>
          <label class="text-xs text-gray-600">
            实验标签
            <input v-model.trim="ragRlhfForm.experiment_tag" type="text" placeholder="可留空"
              class="mt-1 w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
          </label>
          <label class="text-xs text-gray-600">
            反馈样本上限
            <input v-model.number="ragRlhfForm.limit" type="number" min="10" max="5000"
              class="mt-1 w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
          </label>
          <div class="flex items-end gap-2">
            <button @click="handleLoadRlhfStats" :disabled="ragRlhfStatsState.loading"
              class="rounded-md bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
              {{ ragRlhfStatsState.loading ? '统计中...' : '拉取统计' }}
            </button>
            <button @click="handleRlhfSuggest" :disabled="ragRlhfTuneState.loading"
              class="rounded-md bg-slate-700 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
              {{ ragRlhfTuneState.loading ? '计算中...' : '生成建议' }}
            </button>
            <button @click="handleRlhfApply" :disabled="ragRlhfTuneState.loading || !canApplyRlhf"
              class="rounded-md bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">
              {{ ragRlhfTuneState.loading ? '应用中...' : '应用建议' }}
            </button>
          </div>
        </div>

        <p v-if="ragRlhfStatsState.error" class="mt-2 text-xs text-red-600">{{ ragRlhfStatsState.error }}</p>
        <p v-if="ragRlhfTuneState.error" class="mt-1 text-xs text-red-600">{{ ragRlhfTuneState.error }}</p>

        <div v-if="ragRlhfStatsState.data" class="mt-3 rounded-lg border border-indigo-100 bg-white p-3 text-xs text-gray-700">
          <div class="flex flex-wrap gap-4">
            <span>反馈数: <b>{{ ragRlhfStatsState.data.total_feedback || 0 }}</b></span>
            <span>平均奖励: <b>{{ ragRlhfStatsState.data.avg_reward ?? 0 }}</b></span>
            <span>专题: <b>{{ ragRlhfStatsState.data.topic || '-' }}</b></span>
          </div>
          <p v-if="(ragRlhfStatsState.data.total_feedback || 0) < 8" class="mt-1 text-amber-700">
            当前反馈样本不足 8 条，仅能出建议，不会写入配置。
          </p>
        </div>

        <div v-if="ragRlhfTuneState.result?.suggested_retrieval" class="mt-3 rounded-lg border border-emerald-100 bg-white p-3">
          <p class="mb-1 text-xs font-semibold text-emerald-700">建议参数</p>
          <pre class="overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700">{{ JSON.stringify(ragRlhfTuneState.result.suggested_retrieval, null, 2) }}</pre>
          <p class="mt-2 text-xs text-gray-600">原因：{{ (ragRlhfTuneState.result.reasons || []).join('；') || '无' }}</p>
          <p v-if="ragRlhfTuneState.result.applied" class="mt-1 text-xs font-medium text-emerald-700">已写入后端 RAG 配置。</p>
          <p v-else-if="ragRlhfTuneState.result.blocked_reason" class="mt-1 text-xs font-medium text-amber-700">
            {{ ragRlhfTuneState.result.blocked_reason }}
          </p>
        </div>

        <div class="mt-4 rounded-lg border border-slate-200 bg-white p-3">
          <p class="mb-2 text-xs font-semibold text-slate-700">快速反馈（先积累样本再调参）</p>
          <div class="grid gap-2 sm:grid-cols-4">
            <label class="text-xs text-gray-600">
              相关性(1-5)
              <input v-model.number="feedbackForm.relevance" type="number" min="1" max="5"
                class="mt-1 w-full rounded border-gray-300 text-xs focus:border-indigo-500 focus:ring-indigo-500" />
            </label>
            <label class="text-xs text-gray-600">
              完整性(1-5)
              <input v-model.number="feedbackForm.completeness" type="number" min="1" max="5"
                class="mt-1 w-full rounded border-gray-300 text-xs focus:border-indigo-500 focus:ring-indigo-500" />
            </label>
            <label class="text-xs text-gray-600 sm:col-span-2">
              问题说明（可选）
              <input v-model.trim="feedbackForm.bad_reason" type="text" placeholder="例如：召回偏题/不完整"
                class="mt-1 w-full rounded border-gray-300 text-xs focus:border-indigo-500 focus:ring-indigo-500" />
            </label>
          </div>
          <div class="mt-2 flex items-center gap-2">
            <button @click="handleSubmitFeedback" :disabled="ragFeedbackState.loading"
              class="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
              {{ ragFeedbackState.loading ? '提交中...' : '提交反馈' }}
            </button>
            <span v-if="ragFeedbackState.success" class="text-xs text-emerald-700">{{ ragFeedbackState.success }}</span>
            <span v-if="ragFeedbackState.error" class="text-xs text-red-600">{{ ragFeedbackState.error }}</span>
          </div>
        </div>
      </section>

      <!-- 2. 结果展示区 -->
      <section v-if="ragRetrievalState.results.length > 0 || ragRetrievalState.summary" class="animate-fade-in-up space-y-6">
        <div class="flex items-end justify-between border-b border-gray-200 pb-2">
          <div>
            <h3 class="text-lg font-bold text-gray-900">检索结果</h3>
            <p class="text-sm text-gray-500">
              找到 {{ ragRetrievalState.total }} 条相关片段
              <span v-if="ragRetrievalState.raw_total > ragRetrievalState.total">
                （原始召回 {{ ragRetrievalState.raw_total }} 条）
              </span>
            </p>
          </div>
          <button @click="exportResults"
            class="text-sm font-medium text-brand-600 hover:text-brand-800 hover:underline">
            导出 CSV
          </button>
        </div>
        <!-- LLM Summary Section -->
        <div v-if="ragRetrievalState.summary"
          class="animate-fade-in-up mb-6 overflow-hidden rounded-2xl border border-brand-100 bg-brand-50/30 p-6 shadow-sm">
          <div class="mb-4 flex items-center gap-2">
            <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white shadow-md">
              <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <h3 class="text-lg font-bold text-gray-900">AI 智能总结</h3>
          </div>
          <div class="prose prose-brand max-w-none text-gray-800 leading-relaxed">
            <p class="whitespace-pre-wrap">{{ ragRetrievalState.summary }}</p>
          </div>
          <div class="mt-4 flex items-center justify-between border-t border-brand-100 pt-3">
            <span class="text-xs text-brand-500 font-medium italic">由 AI 基于下方参考资料生成</span>
            <button @click="copyText(ragRetrievalState.summary)"
              class="flex items-center gap-1 text-xs text-brand-600 hover:text-brand-800 font-medium">
              <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              复制总结
            </button>
          </div>
        </div>

        <div class="grid gap-4">
          <div v-for="(result, index) in ragRetrievalState.results" :key="index"
            class="relative overflow-hidden rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
            <div class="absolute left-0 top-0 h-full w-1" :class="getScoreColorClass(result.score)"></div>

            <div class="mb-3 flex items-start justify-between">
              <div class="flex items-center gap-2">
                <span
                  class="flex h-6 w-6 items-center justify-center rounded bg-gray-100 text-xs font-bold text-gray-500">#{{
                    index + 1 }}</span>
                <span class="rounded-full px-2 py-0.5 text-xs font-bold" :class="getScoreBadgeClass(result.score)">
                  匹配度: {{ (result.score * 100).toFixed(1) }}%
                </span>
              </div>

              <button @click="copyText(result.text)"
                class="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700" title="复制内容">
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
            </div>

            <div class="prose prose-sm max-w-none text-gray-700">
              <p class="leading-relaxed">{{ result.text }}</p>
            </div>

            <div v-if="result.metadata && Object.keys(result.metadata).length"
              class="mt-4 border-t border-gray-50 pt-3">
              <details class="group/meta">
                <summary
                  class="flex cursor-pointer items-center gap-1 text-xs font-medium text-gray-400 hover:text-gray-600">
                  <svg class="h-3 w-3 transition group-open/meta:rotate-90" fill="none" viewBox="0 0 24 24"
                    stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                  </svg>
                  显示元数据来源
                </summary>
                <div class="mt-2 grid grid-cols-2 gap-2 rounded bg-gray-50 p-2 text-xs text-gray-500">
                  <div v-for="(val, key) in result.metadata" :key="key" class="truncate">
                    <span class="font-semibold text-gray-400">{{ key }}:</span> {{ val }}
                  </div>
                </div>
              </details>
            </div>
          </div>
        </div>
      </section>

      <!-- 空状态 -->
      <div v-else-if="hasSearched && !ragRetrievalState.loading"
        class="mt-12 flex flex-col items-center justify-center text-center">
        <div class="flex h-20 w-20 items-center justify-center rounded-full bg-gray-50">
          <svg class="h-10 w-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h3 class="mt-4 text-lg font-medium text-gray-900">未找到相关内容</h3>
        <p class="mt-2 max-w-sm text-sm text-gray-500">建议尝试降低相似度阈值，或更换更通用的关键词重新检索。</p>
      </div>
    </main>

    <!-- 3. 模态框：库管理 -->
    <div v-if="showManageModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div class="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div class="flex items-center justify-between border-b border-gray-100 bg-gray-50/50 px-6 py-4">
          <h3 class="text-lg font-semibold text-gray-900">检索库管理</h3>
          <button @click="showManageModal = false" class="text-gray-400 hover:text-gray-600">
            <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="space-y-6 p-6">
          <div>
            <label class="mb-2 block text-sm font-medium text-gray-700">现有专题库状态</label>
            <div class="flex items-center justify-between rounded-lg border border-gray-200 p-3">
              <span class="text-sm text-gray-600">
                RouterRAG 可用专题: <span class="font-bold text-gray-900">{{ routerTopicOptions.length }}</span> 个
              </span>
              <button @click="loadTopics" :disabled="ragTopicsState.loading"
                class="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
                <ArrowPathIcon class="h-3 w-3" :class="{ 'animate-spin': ragTopicsState.loading }" />
                {{ ragTopicsState.loading ? '同步中' : '同步列表' }}
              </button>
            </div>
          </div>

          <div>
            <div class="mb-2 flex items-center justify-between">
              <label class="block text-sm font-medium text-gray-700">构建新库</label>
              <button @click="refreshRemoteTopics" :disabled="remoteTopicsState.loading"
                class="text-xs text-brand-600 hover:underline">
                {{ remoteTopicsState.loading ? '加载源数据...' : '刷新源数据' }}
              </button>
            </div>

            <div class="space-y-3 rounded-xl border border-blue-100 bg-blue-50/50 p-4">
              <AppSelect
                :options="remoteTopicSelectOptions"
                :value="ragBuildForm.topic"
                :disabled="remoteTopicsState.loading"
                @change="ragBuildForm.topic = $event"
              />

              <button @click="handleBuild" :disabled="ragBuildState.loading || !ragBuildForm.topic"
                class="w-full rounded-lg bg-brand-600 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-50">
                {{ ragBuildState.loading ? '正在构建索引 (耗时较长)...' : '开始构建索引' }}
              </button>

              <div class="rounded-lg border border-gray-200 bg-white p-3">
                <p class="mb-2 text-xs font-semibold text-gray-600">A/B 构建参数</p>
                <div class="grid grid-cols-2 gap-2">
                  <label class="text-xs text-gray-500">
                    采样比例
                    <input v-model.number="ragBuildForm.sample_ratio" type="number" min="0.01" max="1" step="0.01"
                      class="mt-1 w-full rounded border-gray-300 text-xs focus:border-brand-500 focus:ring-brand-500" />
                  </label>
                  <label class="text-xs text-gray-500">
                    分块模式
                    <select v-model="ragBuildForm.chunk_mode"
                      class="mt-1 w-full rounded border-gray-300 text-xs focus:border-brand-500 focus:ring-brand-500">
                      <option value="sentence">sentence</option>
                      <option value="window">window</option>
                    </select>
                  </label>
                  <label class="text-xs text-gray-500">
                    chunk_size
                    <input v-model.number="ragBuildForm.chunk_size" type="number" min="80" max="1000" step="10"
                      class="mt-1 w-full rounded border-gray-300 text-xs focus:border-brand-500 focus:ring-brand-500" />
                  </label>
                  <label class="text-xs text-gray-500">
                    chunk_overlap
                    <input v-model.number="ragBuildForm.chunk_overlap" type="number" min="0" max="500" step="10"
                      class="mt-1 w-full rounded border-gray-300 text-xs focus:border-brand-500 focus:ring-brand-500" />
                  </label>
                </div>
                <label class="mt-2 flex items-center gap-2 text-xs text-gray-600">
                  <input v-model="ragBuildForm.force_rebuild" type="checkbox"
                    class="rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                  强制重建（删除该专题旧索引后重跑）
                </label>
              </div>
            </div>

            <p v-if="ragBuildState.error" class="mt-2 text-xs text-red-600">{{ ragBuildState.error }}</p>
            <p class="mt-2 text-xs text-gray-400">注意：构建索引可能需要几分钟时间，构建完成后需刷新列表。</p>
          </div>

          <div>
            <label class="mb-2 block text-sm font-medium text-gray-700">手动导入已有索引（高级）</label>
            <div class="space-y-3 rounded-xl border border-amber-100 bg-amber-50/40 p-4">
              <input v-model.trim="manualImport.topic" type="text" placeholder="目标专题名（例如：test）"
                class="w-full rounded-lg border-gray-300 text-sm focus:border-brand-500 focus:ring-brand-500" />
              <input v-model.trim="manualImport.source_path" type="text"
                placeholder="索引路径（.lance / vector_db / 含vector_db的专题目录）"
                class="w-full rounded-lg border-gray-300 text-sm focus:border-brand-500 focus:ring-brand-500" />
              <button @click="handleManualImport"
                :disabled="ragImportState.loading || !manualImport.topic || !manualImport.source_path"
                class="w-full rounded-lg bg-amber-600 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-amber-700 disabled:opacity-50">
                {{ ragImportState.loading ? '导入中...' : '导入已有索引' }}
              </button>
            </div>
            <p v-if="ragImportState.error" class="mt-2 text-xs text-red-600">{{ ragImportState.error }}</p>
            <p v-else-if="ragImportState.result" class="mt-2 text-xs text-emerald-700">
              导入完成：{{ ragImportState.result.imported_count || 0 }} 项，表：{{ (ragImportState.result.tables || []).join(', ') || '无' }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <RagCacheToast :state="ragCacheState" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowPathIcon } from '@heroicons/vue/24/outline'
import { useRAGTopics } from '../../composables/useRAGTopics'
import RagCacheToast from '../../components/rag/RagCacheToast.vue'
import AppSelect from '../../components/AppSelect.vue'

const {
  ragTopicsState,
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
  loadRAGTopics,
  loadRemoteTopics,
  loadLocalTopics,
  buildRagTopic,
  importRouterRAGArtifacts,
  retrieveRouterRAG,
  retrieveTagRAG,
  fetchRouterRlhfStats,
  tuneRouterRlhf,
  submitRouterRAGFeedback
} = useRAGTopics()

const hasSearched = computed(() => ragRetrievalState.error !== '' || ragRetrievalState.results.length > 0)
const showManageModal = ref(false)
const pureMode = ref(true)
const manualImport = ref({
  topic: '',
  source_path: ''
})
const feedbackForm = ref({
  relevance: 3,
  completeness: 3,
  bad_reason: ''
})

const selectableTopics = computed(() => {
  if (ragSearchForm.rag_type === 'tagrag') return tagragTopicOptions.value
  if (['routerrag', 'graphrag', 'normalrag'].includes(ragSearchForm.rag_type)) return routerTopicOptions.value
  return [...new Set([...tagragTopicOptions.value, ...routerTopicOptions.value])]
})

const searchTopicSelectOptions = computed(() => [
  { value: '', label: '选择专题' },
  ...selectableTopics.value.map(t => ({ value: t, label: t }))
])

const remoteTopicSelectOptions = computed(() => [
  { value: '', label: '选择远程数据源...' },
  ...remoteTopicOptions.value.map(t => ({ value: t, label: t }))
])

const retrievalModes = [
  { value: 'routerrag', label: '语义检索 (Semantic)' },
  { value: 'graphrag', label: '图数据库检索 (Neo4j)' },
  { value: 'tagrag', label: '标签检索 (Tag)' },
  { value: 'hybrid', label: '混合模式' }
]

const loadTopics = async () => {
  await loadRAGTopics()
}

const refreshRemoteTopics = async () => {
  await loadRemoteTopics()
}

const handleBuild = async () => {
  try {
    const buildType = ragSearchForm.rag_type === 'tagrag' ? 'tagrag' : 'routerrag'
    await buildRagTopic({
      type: buildType,
      source_type: ragBuildForm.source_type,
      build_topic: ragBuildForm.build_topic,
      local_source_dir: ragBuildForm.local_source_dir
    })
  } catch (error) {
    // Error handled in composable
  }
}

const selectedBuildTopic = computed(() => {
  const manualTopic = String(ragBuildForm.build_topic || '').trim()
  if (manualTopic) return manualTopic
  if (ragBuildForm.source_type === 'local') return ragBuildForm.local_topic
  if (ragBuildForm.source_type === 'dir') return manualTopic
  return ragBuildForm.remote_topic
})
const canApplyRlhf = computed(() => {
  const total = Number(ragRlhfStatsState.data?.total_feedback || 0)
  return total >= 8
})

const handleSearch = async () => {
  if (!ragSearchForm.query || !ragSearchForm.topic) {
    ragRetrievalState.error = '请选择专题并输入查询内容'
    return
  }
  try {
    if (ragSearchForm.rag_type === 'tagrag') {
      await retrieveTagRAG()
    } else {
      await retrieveRouterRAG({
        use_question_preset: !pureMode.value,
        enable_expert_overlay: !pureMode.value,
        enable_expert_rewrite: !pureMode.value,
        enable_expert_hints: !pureMode.value,
        enable_expert_answer_structure: !pureMode.value,
        experiment_tag: pureMode.value ? 'pure' : 'enhanced'
      })
    }
  } catch (error) {
    // Error handled
  }
}

const handleManualImport = async () => {
  try {
    await importRouterRAGArtifacts({
      topic: manualImport.value.topic,
      source_path: manualImport.value.source_path
    })
  } catch (error) {
    // Error handled in composable
  }
}

const handleLoadRlhfStats = async () => {
  try {
    await fetchRouterRlhfStats({
      topic: ragRlhfForm.topic || ragSearchForm.topic,
      experiment_tag: ragRlhfForm.experiment_tag,
      limit: ragRlhfForm.limit
    })
  } catch (error) {
    // handled in composable
  }
}

const handleRlhfSuggest = async () => {
  try {
    await tuneRouterRlhf({
      topic: ragRlhfForm.topic || ragSearchForm.topic,
      experiment_tag: ragRlhfForm.experiment_tag,
      limit: ragRlhfForm.limit,
      apply: false
    })
  } catch (error) {
    // handled in composable
  }
}

const handleRlhfApply = async () => {
  try {
    await tuneRouterRlhf({
      topic: ragRlhfForm.topic || ragSearchForm.topic,
      experiment_tag: ragRlhfForm.experiment_tag,
      limit: ragRlhfForm.limit,
      apply: true
    })
  } catch (error) {
    // handled in composable
  }
}

const handleSubmitFeedback = async () => {
  try {
    await submitRouterRAGFeedback({
      topic: ragSearchForm.topic,
      question: ragSearchForm.query,
      experiment_tag: pureMode.value ? 'pure' : 'enhanced',
      scores: {
        relevance: Number(feedbackForm.value.relevance || 0),
        completeness: Number(feedbackForm.value.completeness || 0)
      },
      bad_reason: feedbackForm.value.bad_reason
    })
  } catch (error) {
    // handled in composable
  }
}

const getScoreColorClass = (score) => {
  if (score >= 0.8) return 'bg-emerald-500'
  if (score >= 0.6) return 'bg-blue-500'
  if (score >= 0.4) return 'bg-yellow-500'
  return 'bg-gray-300'
}

const getScoreBadgeClass = (score) => {
  if (score >= 0.8) return 'bg-emerald-100 text-emerald-700'
  if (score >= 0.6) return 'bg-blue-100 text-blue-700'
  if (score >= 0.4) return 'bg-yellow-100 text-yellow-700'
  return 'bg-gray-100 text-gray-600'
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
  } catch (error) {
    // ignore
  }
}

const exportResults = () => {
  const exportData = ragRetrievalState.results.map((result, index) => ({
    序号: index + 1,
    相似度: (result.score * 100).toFixed(2) + '%',
    内容: result.text,
    元数据: JSON.stringify(result.metadata)
  }))

  const csv = [
    Object.keys(exportData[0]).join(','),
    ...exportData.map(row => Object.values(row).map(v => `"${v}"`).join(','))
  ].join('\n')

  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `routerrag_results_${Date.now()}.csv`
  link.click()
}

onMounted(() => {
  loadTopics()
  loadRemoteTopics()
  loadLocalTopics()
})

const refreshLocalTopics = async () => {
  await loadLocalTopics()
}

watch(selectableTopics, (options) => {
  if (options.length > 0 && !options.includes(ragSearchForm.topic)) {
    ragSearchForm.topic = options[0]
  }
  if (!ragRlhfForm.topic && ragSearchForm.topic) {
    ragRlhfForm.topic = ragSearchForm.topic
  }
})
</script>

<style scoped>
.animate-fade-in-up {
  animation: fadeInUp 0.5s ease-out;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
