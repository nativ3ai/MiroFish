<template>
  <div class="simulation-panel">
    <div class="control-bar">
      <div class="status-group">
        <div class="platform-status twitter" :class="{ active: runStatus.twitter_running, completed: runStatus.twitter_completed }">
          <div class="platform-header">
            <span class="platform-name">INFO PLAZA</span>
            <span class="status-chip">{{ runStatus.twitter_completed ? 'DONE' : (runStatus.twitter_running ? 'LIVE' : 'IDLE') }}</span>
          </div>
          <div class="platform-stats">
            <span>ROUND {{ runStatus.twitter_current_round || 0 }}/{{ runStatus.total_rounds || maxRounds || '-' }}</span>
            <span>TIME {{ twitterElapsedTime }}</span>
            <span>ACTS {{ runStatus.twitter_actions_count || 0 }}</span>
          </div>
        </div>

        <div class="platform-status reddit" :class="{ active: runStatus.reddit_running, completed: runStatus.reddit_completed }">
          <div class="platform-header">
            <span class="platform-name">TOPIC COMMUNITY</span>
            <span class="status-chip">{{ runStatus.reddit_completed ? 'DONE' : (runStatus.reddit_running ? 'LIVE' : 'IDLE') }}</span>
          </div>
          <div class="platform-stats">
            <span>ROUND {{ runStatus.reddit_current_round || 0 }}/{{ runStatus.total_rounds || maxRounds || '-' }}</span>
            <span>TIME {{ redditElapsedTime }}</span>
            <span>ACTS {{ runStatus.reddit_actions_count || 0 }}</span>
          </div>
        </div>
      </div>

      <div class="action-controls">
        <button class="action-btn primary" :disabled="phase !== 2 || isGeneratingReport" @click="handleNextStep">
          <span v-if="isGeneratingReport" class="loading-spinner-small"></span>
          {{ isGeneratingReport ? 'REPORT LINKING...' : 'GENERATE REPORT' }}
        </button>
      </div>
    </div>

    <div class="main-content-area">
      <ButterflyEffectOverlay
        v-if="simulationConfig?.counterfactual"
        :simulation-id="simulationId"
        :simulation-config="simulationConfig"
        :branch-actions="allActions"
        :run-status="runStatus"
      />

      <div class="intel-layout">
        <section class="timeline-shell full">
          <div class="timeline-header" v-if="allActions.length > 0">
            <div class="timeline-statline">
              <span>[ TOTAL {{ allActions.length }} ]</span>
              <span>[ TW {{ twitterActionsCount }} ]</span>
              <span>[ RD {{ redditActionsCount }} ]</span>
              <span>[ STATUS {{ runStatus.runner_status || 'running' }} ]</span>
              <span v-if="focusRound !== null && focusRound !== undefined">[ ROUND FOCUS {{ focusRound }} ]</span>
            </div>
          </div>

          <div ref="timelineFeed" class="timeline-feed">
            <div class="timeline-axis"></div>
            <TransitionGroup name="timeline-item">
              <article
                v-for="action in chronologicalActions"
                :key="action._uniqueId || action.id || `${action.timestamp}-${action.agent_id}`"
                class="timeline-item"
                :class="[
                  action.platform,
                  {
                    focused: isFocusedRound(action),
                    muted: focusRound !== null && focusRound !== undefined && !isFocusedRound(action)
                  }
                ]"
                :data-round="getActionRound(action)"
              >
                <div class="timeline-marker">
                  <div class="marker-core"></div>
                </div>

                <div class="timeline-card">
                  <div class="card-header">
                    <div>
                      <div class="agent-name">{{ action.agent_name || 'Unknown agent' }}</div>
                      <div class="agent-meta">{{ action.platform || 'stream' }} :: {{ getActionTypeLabel(action.action_type) }}</div>
                    </div>
                    <div class="round-pill">R{{ action.round_num || action.round || 0 }}</div>
                  </div>

                  <div class="card-body">
                    <div v-if="getPrimaryContent(action)" class="content-text main-text">
                      {{ getPrimaryContent(action) }}
                    </div>
                    <div v-if="getSecondaryContent(action)" class="support-block">
                      {{ getSecondaryContent(action) }}
                    </div>
                    <div v-if="getContextLabel(action)" class="context-line">
                      {{ getContextLabel(action) }}
                    </div>
                  </div>

                  <div class="card-footer">
                    <span>{{ formatActionTime(action.timestamp) }}</span>
                    <span>{{ getPlatformLabel(action.platform) }}</span>
                  </div>
                </div>
              </article>
            </TransitionGroup>

            <div v-if="allActions.length === 0" class="waiting-state">
              <div class="waiting-title">[ AGENT SOCIETIES BOOTING ]</div>
              <div class="waiting-copy">Awaiting first live actions from the simulation bus.</div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <div class="system-logs">
      <div class="log-header">
        <span>SIMULATION MONITOR</span>
        <span>{{ simulationId || 'NO_SIMULATION' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div v-for="(log, idx) in systemLogs" :key="idx" class="log-line">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ButterflyEffectOverlay from './ButterflyEffectOverlay.vue'
import { generateReport } from '../api/report'
import { getRunStatus, getRunStatusDetail, startSimulation, stopSimulation } from '../api/simulation'

const props = defineProps({
  simulationId: String,
  maxRounds: Number,
  minutesPerRound: {
    type: Number,
    default: 30
  },
  readOnly: {
    type: Boolean,
    default: false
  },
  focusRound: {
    type: Number,
    default: null
  },
  simulationConfig: Object,
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const router = useRouter()
const isGeneratingReport = ref(false)
const phase = ref(0)
const isStarting = ref(false)
const runStatus = ref({})
const allActions = ref([])
const actionIds = ref(new Set())
const prevTwitterRound = ref(0)
const prevRedditRound = ref(0)
const logContent = ref(null)
const timelineFeed = ref(null)
let statusTimer = null
let detailTimer = null

const chronologicalActions = computed(() => {
  return [...allActions.value].sort((a, b) => {
    const first = new Date(a.timestamp || 0).getTime()
    const second = new Date(b.timestamp || 0).getTime()
    return first - second
  })
})

const twitterActionsCount = computed(() => allActions.value.filter(action => action.platform === 'twitter').length)
const redditActionsCount = computed(() => allActions.value.filter(action => action.platform === 'reddit').length)

function addLog(message) {
  emit('add-log', message)
}

function formatElapsedTime(currentRound) {
  if (!currentRound || currentRound <= 0) return '0h 0m'
  const totalMinutes = currentRound * props.minutesPerRound
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours}h ${minutes}m`
}

const twitterElapsedTime = computed(() => formatElapsedTime(runStatus.value.twitter_current_round || 0))
const redditElapsedTime = computed(() => formatElapsedTime(runStatus.value.reddit_current_round || 0))

function resetAllState() {
  phase.value = 0
  runStatus.value = {}
  allActions.value = []
  actionIds.value = new Set()
  prevTwitterRound.value = 0
  prevRedditRound.value = 0
  stopPolling()
}

async function doStartSimulation() {
  if (!props.simulationId) {
    addLog('错误：缺少 simulationId')
    return
  }

  resetAllState()
  isStarting.value = true
  addLog('Initializing dual-platform simulation workbench...')
  emit('update-status', 'processing')

  try {
    const params = {
      simulation_id: props.simulationId,
      platform: 'parallel',
      force: true,
      enable_graph_memory_update: true
    }

    if (props.maxRounds) {
      params.max_rounds = props.maxRounds
      addLog(`Max rounds pinned to ${props.maxRounds}`)
    }

    const response = await startSimulation(params)
    if (response.success && response.data) {
      addLog('Simulation engine online')
      phase.value = 1
      runStatus.value = response.data
      startStatusPolling()
      startDetailPolling()
    } else {
      addLog(`启动失败: ${response.error || '未知错误'}`)
      emit('update-status', 'error')
    }
  } catch (error) {
    addLog(`启动异常: ${error.message}`)
    emit('update-status', 'error')
  } finally {
    isStarting.value = false
  }
}

async function loadArchivedSimulation() {
  if (!props.simulationId) {
    addLog('错误：缺少 simulationId')
    emit('update-status', 'error')
    return
  }

  resetAllState()
  addLog('Loading archived simulation workbench...')
  emit('update-status', 'processing')

  try {
    const [statusResponse, detailResponse] = await Promise.all([
      getRunStatus(props.simulationId),
      getRunStatusDetail(props.simulationId)
    ])

    if (statusResponse.success && statusResponse.data) {
      runStatus.value = statusResponse.data
      prevTwitterRound.value = statusResponse.data.twitter_current_round || 0
      prevRedditRound.value = statusResponse.data.reddit_current_round || 0

      const completed = statusResponse.data.runner_status === 'completed' ||
        statusResponse.data.runner_status === 'stopped' ||
        checkPlatformsCompleted(statusResponse.data)

      phase.value = completed ? 2 : 1
      emit('update-status', completed ? 'completed' : 'processing')
    }

    if (detailResponse.success && detailResponse.data) {
      const serverActions = detailResponse.data.all_actions || []
      const nextActions = []
      const nextActionIds = new Set()

      serverActions.forEach(action => {
        const actionId = action.id || `${action.timestamp}-${action.platform}-${action.agent_id}-${action.action_type}`
        if (nextActionIds.has(actionId)) return
        nextActionIds.add(actionId)
        nextActions.push({ ...action, _uniqueId: actionId })
      })

      allActions.value = nextActions
      actionIds.value = nextActionIds
      addLog(`Loaded ${nextActions.length} archived actions`)
    }

    if (runStatus.value.runner_status === 'running' || runStatus.value.runner_status === 'starting') {
      startStatusPolling()
      startDetailPolling()
      addLog('Archived view attached to live branch state')
    } else {
      addLog('Archived branch ready')
    }
  } catch (error) {
    addLog(`归档加载异常: ${error.message}`)
    emit('update-status', 'error')
  }
}

async function handleStopSimulation() {
  if (!props.simulationId) return

  addLog('Stopping simulation...')
  try {
    const response = await stopSimulation({ simulation_id: props.simulationId })
    if (response.success) {
      addLog('Simulation stopped')
      phase.value = 2
      stopPolling()
      emit('update-status', 'completed')
    }
  } catch (error) {
    addLog(`停止异常: ${error.message}`)
  }
}

function startStatusPolling() {
  statusTimer = setInterval(fetchRunStatus, 2000)
}

function startDetailPolling() {
  detailTimer = setInterval(fetchRunStatusDetail, 3000)
}

function stopPolling() {
  if (statusTimer) clearInterval(statusTimer)
  if (detailTimer) clearInterval(detailTimer)
  statusTimer = null
  detailTimer = null
}

function checkPlatformsCompleted(data) {
  if (!data) return false
  const twitterCompleted = data.twitter_completed === true
  const redditCompleted = data.reddit_completed === true
  const twitterEnabled = (data.twitter_actions_count > 0) || data.twitter_running || twitterCompleted
  const redditEnabled = (data.reddit_actions_count > 0) || data.reddit_running || redditCompleted
  if (!twitterEnabled && !redditEnabled) return false
  if (twitterEnabled && !twitterCompleted) return false
  if (redditEnabled && !redditCompleted) return false
  return true
}

async function fetchRunStatus() {
  if (!props.simulationId) return
  try {
    const response = await getRunStatus(props.simulationId)
    if (!(response.success && response.data)) return

    const data = response.data
    runStatus.value = data

    if (data.twitter_current_round > prevTwitterRound.value) {
      addLog(`[Plaza] R${data.twitter_current_round}/${data.total_rounds} | T:${data.twitter_simulated_hours || 0}h | A:${data.twitter_actions_count}`)
      prevTwitterRound.value = data.twitter_current_round
    }

    if (data.reddit_current_round > prevRedditRound.value) {
      addLog(`[Community] R${data.reddit_current_round}/${data.total_rounds} | T:${data.reddit_simulated_hours || 0}h | A:${data.reddit_actions_count}`)
      prevRedditRound.value = data.reddit_current_round
    }

    const completed = data.runner_status === 'completed' || data.runner_status === 'stopped' || checkPlatformsCompleted(data)
    if (completed) {
      addLog('Simulation complete')
      phase.value = 2
      stopPolling()
      emit('update-status', 'completed')
    }
  } catch (error) {
    console.warn('获取运行状态失败:', error)
  }
}

async function fetchRunStatusDetail() {
  if (!props.simulationId) return

  try {
    const response = await getRunStatusDetail(props.simulationId)
    if (!(response.success && response.data)) return

    const serverActions = response.data.all_actions || []
    serverActions.forEach(action => {
      const actionId = action.id || `${action.timestamp}-${action.platform}-${action.agent_id}-${action.action_type}`
      if (actionIds.value.has(actionId)) return
      actionIds.value.add(actionId)
      allActions.value.push({ ...action, _uniqueId: actionId })
    })
  } catch (error) {
    console.warn('获取详细状态失败:', error)
  }
}

function getActionTypeLabel(type) {
  const labels = {
    CREATE_POST: 'POST',
    REPOST: 'REPOST',
    LIKE_POST: 'LIKE',
    CREATE_COMMENT: 'COMMENT',
    LIKE_COMMENT: 'LIKE',
    DO_NOTHING: 'IDLE',
    FOLLOW: 'FOLLOW',
    SEARCH_POSTS: 'SEARCH',
    QUOTE_POST: 'QUOTE',
    UPVOTE_POST: 'UPVOTE',
    DOWNVOTE_POST: 'DOWNVOTE',
    TREND: 'TREND',
    REFRESH: 'REFRESH'
  }
  return labels[type] || type || 'UNKNOWN'
}

function getPrimaryContent(action) {
  const args = action.action_args || {}
  return args.content || args.quote_content || args.query || args.post_content || ''
}

function getSecondaryContent(action) {
  const args = action.action_args || {}
  if (args.original_content) return args.original_content
  if (args.post_content && args.post_content !== args.content) return args.post_content
  return ''
}

function getContextLabel(action) {
  const args = action.action_args || {}
  if (action.action_type === 'FOLLOW') return `target :: ${args.target_user || args.user_id || 'user'}`
  if (action.action_type === 'SEARCH_POSTS') return `query :: ${args.query || 'n/a'}`
  if (action.action_type === 'CREATE_COMMENT') return `reply :: post #${args.post_id || 'n/a'}`
  if (args.original_author_name) return `source :: @${args.original_author_name}`
  if (args.post_author_name) return `source :: @${args.post_author_name}`
  return ''
}

function getPlatformLabel(platform) {
  if (platform === 'twitter') return 'PLAZA'
  if (platform === 'reddit') return 'COMMUNITY'
  return (platform || 'STREAM').toUpperCase()
}

function getActionRound(action) {
  return Number(action.round_num ?? action.round ?? 0)
}

function isFocusedRound(action) {
  return props.focusRound === null || props.focusRound === undefined || getActionRound(action) === props.focusRound
}

function scrollToFocusedRound() {
  if (props.focusRound === null || props.focusRound === undefined) return
  nextTick(() => {
    const target = timelineFeed.value?.querySelector(`[data-round="${props.focusRound}"]`)
    if (target) {
      target.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      })
    }
  })
}

function formatActionTime(timestamp) {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  } catch {
    return ''
  }
}

async function handleNextStep() {
  if (!props.simulationId || isGeneratingReport.value) return
  isGeneratingReport.value = true
  addLog('Starting report generation...')

  try {
    const response = await generateReport({
      simulation_id: props.simulationId,
      force_regenerate: true
    })

    if (response.success && response.data) {
      addLog(`Report task online: ${response.data.report_id}`)
      router.push({ name: 'Report', params: { reportId: response.data.report_id } })
      return
    }

    addLog(`报告生成失败: ${response.error || '未知错误'}`)
  } catch (error) {
    addLog(`报告生成异常: ${error.message}`)
  } finally {
    isGeneratingReport.value = false
  }
}

watch(() => props.systemLogs?.length, () => {
  nextTick(() => {
    if (logContent.value) {
      logContent.value.scrollTop = logContent.value.scrollHeight
    }
  })
})

watch(() => props.focusRound, () => {
  scrollToFocusedRound()
})

watch(() => allActions.value.length, () => {
  if (props.focusRound === null || props.focusRound === undefined) return
  scrollToFocusedRound()
})

onMounted(() => {
  addLog(props.readOnly ? 'Archived simulation workbench armed' : 'Simulation workbench armed')
  if (!props.simulationId) return
  if (props.readOnly) {
    loadArchivedSimulation()
    return
  }
  doStartSimulation()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.simulation-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: radial-gradient(circle at top, rgba(17, 40, 30, 0.95), #050908 48%);
  color: #dbffed;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  overflow: hidden;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  padding: 16px 24px;
  border-bottom: 1px solid rgba(122, 240, 181, 0.12);
  background: rgba(4, 9, 8, 0.85);
  backdrop-filter: blur(18px);
}

.status-group {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.platform-status {
  min-width: 220px;
  padding: 12px 14px;
  border: 1px solid rgba(122, 240, 181, 0.12);
  background: rgba(255, 255, 255, 0.02);
  transition: border-color 0.2s ease, background 0.2s ease;
}

.platform-status.active {
  border-color: rgba(122, 240, 181, 0.34);
  background: rgba(122, 240, 181, 0.06);
}

.platform-status.completed {
  border-color: rgba(255, 211, 106, 0.34);
}

.platform-header,
.platform-stats,
.action-controls,
.timeline-statline,
.card-header,
.card-footer,
.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.platform-name,
.action-btn,
.timeline-statline,
.round-pill,
.log-header,
.agent-meta,
.context-line,
.card-footer {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
}

.platform-name,
.timeline-statline,
.log-header {
  letter-spacing: 0.14em;
  font-size: 10px;
}

.platform-name {
  color: #8cf6c2;
}

.platform-stats {
  margin-top: 8px;
  flex-wrap: wrap;
  font-size: 11px;
  color: rgba(219, 255, 237, 0.76);
}

.status-chip,
.round-pill {
  padding: 3px 7px;
  border: 1px solid rgba(122, 240, 181, 0.16);
  font-size: 10px;
  color: rgba(219, 255, 237, 0.72);
}

.action-controls {
  flex-shrink: 0;
}

.action-btn {
  padding: 11px 14px;
  border: 1px solid rgba(122, 240, 181, 0.16);
  background: rgba(255, 255, 255, 0.02);
  color: #dbffed;
  letter-spacing: 0.12em;
  font-size: 11px;
  cursor: pointer;
}

.action-btn.primary {
  background: linear-gradient(90deg, rgba(77, 226, 165, 0.16), rgba(255, 211, 106, 0.12));
}

.action-btn:hover:not(:disabled) {
  border-color: rgba(122, 240, 181, 0.34);
}

.action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.main-content-area {
  flex: 1;
  overflow-y: auto;
}

.intel-layout {
  display: block;
  padding: 20px 24px 24px;
}

.timeline-shell {
  min-width: 0;
}

.timeline-header {
  position: sticky;
  top: 0;
  z-index: 4;
  padding-bottom: 12px;
  background: linear-gradient(180deg, rgba(5, 9, 8, 0.92), rgba(5, 9, 8, 0.32));
  backdrop-filter: blur(12px);
}

.timeline-statline {
  justify-content: flex-start;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid rgba(122, 240, 181, 0.12);
  background: rgba(255, 255, 255, 0.03);
  color: rgba(219, 255, 237, 0.72);
}

.timeline-feed {
  position: relative;
  min-height: 100%;
  padding: 12px 0 24px;
}

.timeline-axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: linear-gradient(180deg, rgba(122, 240, 181, 0.16), rgba(122, 240, 181, 0.02));
  transform: translateX(-50%);
}

.timeline-item {
  position: relative;
  width: 100%;
  display: flex;
  margin-bottom: 24px;
  transition: opacity 0.2s ease, transform 0.2s ease, filter 0.2s ease;
}

.timeline-item.twitter {
  justify-content: flex-start;
  padding-right: 50%;
}

.timeline-item.reddit {
  justify-content: flex-end;
  padding-left: 50%;
}

.timeline-item.focused .timeline-card,
.timeline-item.focused .timeline-marker {
  border-color: rgba(255, 211, 106, 0.32);
  box-shadow: 0 0 0 1px rgba(255, 211, 106, 0.12), 0 18px 36px rgba(0, 0, 0, 0.22);
}

.timeline-item.muted {
  opacity: 0.34;
  filter: saturate(0.7);
}

.timeline-marker {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  width: 14px;
  height: 14px;
  border: 1px solid rgba(122, 240, 181, 0.2);
  background: #06100d;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
}

.marker-core {
  width: 6px;
  height: 6px;
  background: #82f7bf;
}

.timeline-card {
  width: calc(100% - 44px);
  padding: 16px 18px;
  border: 1px solid rgba(122, 240, 181, 0.12);
  background:
    linear-gradient(180deg, rgba(12, 23, 18, 0.96), rgba(5, 10, 8, 0.98)),
    repeating-linear-gradient(0deg, rgba(122, 240, 181, 0.03), rgba(122, 240, 181, 0.03) 1px, transparent 1px, transparent 20px);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.18);
}

.timeline-item.twitter .timeline-card {
  margin-right: 32px;
}

.timeline-item.reddit .timeline-card {
  margin-left: 32px;
}

.card-header {
  align-items: flex-start;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(122, 240, 181, 0.08);
}

.agent-name {
  font-size: 14px;
  font-weight: 700;
  color: #f2fff8;
}

.agent-meta,
.context-line,
.card-footer {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: rgba(219, 255, 237, 0.56);
  text-transform: uppercase;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.content-text {
  font-size: 13px;
  line-height: 1.7;
  color: rgba(219, 255, 237, 0.85);
}

.main-text {
  color: #f6fff9;
}

.support-block {
  padding: 10px 12px;
  border: 1px solid rgba(122, 240, 181, 0.08);
  background: rgba(255, 255, 255, 0.03);
  font-size: 12px;
  line-height: 1.6;
  color: rgba(219, 255, 237, 0.72);
}

.waiting-state {
  min-height: 380px;
  display: grid;
  place-items: center;
  text-align: center;
  border: 1px dashed rgba(122, 240, 181, 0.16);
  color: rgba(219, 255, 237, 0.55);
}

.waiting-title {
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.16em;
  margin-bottom: 10px;
  color: #8cf6c2;
}

.system-logs {
  flex-shrink: 0;
  padding: 14px 18px 16px;
  border-top: 1px solid rgba(122, 240, 181, 0.1);
  background: rgba(2, 5, 4, 0.98);
  font-family: 'JetBrains Mono', monospace;
}

.log-header {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: #8cf6c2;
  margin-bottom: 10px;
}

.log-content {
  max-height: 132px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.log-line {
  display: grid;
  grid-template-columns: 112px 1fr;
  gap: 12px;
  font-size: 11px;
  line-height: 1.5;
}

.log-time {
  color: rgba(219, 255, 237, 0.44);
}

.log-msg {
  color: rgba(219, 255, 237, 0.8);
}

.loading-spinner-small {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.timeline-item-enter-active {
  transition: all 0.35s ease;
}

.timeline-item-enter-from {
  opacity: 0;
  transform: translateY(14px);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1440px) {
  .intel-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .control-bar {
    flex-direction: column;
  }

  .timeline-axis,
  .timeline-marker {
    left: 14px;
    transform: none;
  }

  .timeline-item,
  .timeline-item.twitter,
  .timeline-item.reddit {
    padding: 0 0 0 34px;
    justify-content: flex-start;
  }

  .timeline-item.twitter .timeline-card,
  .timeline-item.reddit .timeline-card {
    margin: 0;
    width: 100%;
  }

  .log-line {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}
</style>
