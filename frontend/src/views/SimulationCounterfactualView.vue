<template>
  <div class="main-view">
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="router.push('/')">MIROFISH // COUNTERFACTUAL</div>
      </div>

      <div class="header-center">
        <div class="view-switcher">
          <button
            v-for="mode in ['dashboard', 'split', 'lab']"
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{ { dashboard: '分支态', split: '差分', lab: '实验室' }[mode] }}
          </button>
        </div>
      </div>

      <div class="header-right">
        <div class="workflow-step">
          <span class="step-num">Step 3/5</span>
          <span class="step-name">反事实注入</span>
        </div>
        <div class="step-divider"></div>
        <span class="status-indicator" :class="statusClass">
          <span class="dot"></span>
          {{ statusText }}
        </span>
      </div>
    </header>

    <main class="content-area">
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <Step3Simulation
          :simulation-id="currentSimulationId"
          :read-only="true"
          :focus-round="selectedRound"
          :simulation-config="simulationConfig"
          :max-rounds="maxRound"
          :minutes-per-round="minutesPerRound"
          :project-data="simulationData"
          :graph-data="null"
          :system-logs="systemLogs"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </div>

      <div class="panel-wrapper right" :style="rightPanelStyle">
        <CounterfactualArchivePanel
          v-if="viewMode !== 'lab'"
          :simulation-id="currentSimulationId"
          :base-simulation-id="baseSimulationId"
          :simulation-data="simulationData"
          :simulation-config="simulationConfig"
          :timeline="timeline"
          :base-timeline="baseTimeline"
          :agent-stats="agentStats"
          :branch-round-actions="branchRoundActions"
          :base-round-actions="baseRoundActions"
          :selected-round="selectedRound"
          :loading-actions="loadingActions"
          @update:selected-round="selectedRound = $event"
          @open-lab="viewMode = 'lab'"
        />

        <CounterfactualLabPanel
          v-else
          :simulation-id="currentSimulationId"
          :profiles="profiles"
          :selected-round="selectedRound"
          :max-round="maxRound"
          @launched="handleLaunched"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CounterfactualArchivePanel from '../components/CounterfactualArchivePanel.vue'
import CounterfactualLabPanel from '../components/CounterfactualLabPanel.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import {
  getSimulation,
  getSimulationActions,
  getSimulationConfig,
  getSimulationTimeline,
  getAgentStats,
  getSimulationProfiles
} from '../api/simulation'

const route = useRoute()
const router = useRouter()

const viewMode = ref('split')
const currentSimulationId = ref(route.params.simulationId)
const simulationData = ref(null)
const simulationConfig = ref(null)
const timeline = ref([])
const baseTimeline = ref([])
const agentStats = ref([])
const profiles = ref([])
const branchRoundActions = ref([])
const baseRoundActions = ref([])
const selectedRound = ref(0)
const currentStatus = ref('processing')
const systemLogs = ref([])
const minutesPerRound = ref(60)
const loadingActions = ref(false)

const baseSimulationId = computed(() => simulationConfig.value?.counterfactual?.base_simulation_id || '')
const maxRound = computed(() => timeline.value.length ? Math.max(...timeline.value.map(item => item.round_num || 0)) : 0)

const leftPanelStyle = computed(() => {
  if (viewMode.value === 'dashboard') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'lab') return { width: '0%', opacity: 0, transform: 'translateX(-20px)' }
  return { width: '58%', opacity: 1, transform: 'translateX(0)' }
})

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'lab') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'dashboard') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '42%', opacity: 1, transform: 'translateX(0)' }
})

const statusClass = computed(() => currentStatus.value)
const statusText = computed(() => {
  if (currentStatus.value === 'error') return 'Error'
  if (currentStatus.value === 'completed') return 'Ready'
  return 'Loading'
})

function addLog(message) {
  const time = new Date().toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }) + '.' + new Date().getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg: message })
  if (systemLogs.value.length > 200) {
    systemLogs.value.shift()
  }
}

function updateStatus(status) {
  currentStatus.value = status
}

function normalizeActions(actions) {
  return [...(actions || [])].sort((left, right) => {
    const leftTime = new Date(left.timestamp || 0).getTime()
    const rightTime = new Date(right.timestamp || 0).getTime()
    return leftTime - rightTime
  })
}

async function loadRoundActions() {
  if (!currentSimulationId.value || selectedRound.value === null || selectedRound.value === undefined) return

  loadingActions.value = true
  try {
    const requests = [
      getSimulationActions(currentSimulationId.value, { round_num: selectedRound.value, limit: 200 })
    ]

    if (baseSimulationId.value) {
      requests.push(getSimulationActions(baseSimulationId.value, { round_num: selectedRound.value, limit: 200 }))
    }

    const [branchRes, baseRes] = await Promise.all(requests)
    branchRoundActions.value = normalizeActions(branchRes.data || [])
    baseRoundActions.value = normalizeActions(baseRes?.data || [])
    addLog(`Round ${selectedRound.value} forensics synced`) 
  } catch (error) {
    console.error('加载轮次动作失败:', error)
    branchRoundActions.value = []
    baseRoundActions.value = []
  } finally {
    loadingActions.value = false
  }
}

async function loadBaseData() {
  currentStatus.value = 'processing'
  const simulationId = currentSimulationId.value
  try {
    const [simulationRes, configRes, timelineRes, agentStatsRes, profilesRes] = await Promise.all([
      getSimulation(simulationId),
      getSimulationConfig(simulationId),
      getSimulationTimeline(simulationId, 0),
      getAgentStats(simulationId),
      getSimulationProfiles(simulationId, 'reddit')
    ])

    simulationData.value = simulationRes.data || null
    simulationConfig.value = configRes.data || null
    timeline.value = timelineRes.data?.timeline || []
    agentStats.value = agentStatsRes.data || []
    profiles.value = profilesRes.data?.profiles || []
    minutesPerRound.value = configRes.data?.time_config?.minutes_per_round || minutesPerRound.value

    if (baseSimulationId.value) {
      try {
        const baseTimelineRes = await getSimulationTimeline(baseSimulationId.value, 0)
        baseTimeline.value = baseTimelineRes.data?.timeline || []
      } catch (error) {
        console.warn('加载基线时间线失败:', error)
        baseTimeline.value = []
      }
    }

    if (timeline.value.length > 0) {
      const hottestRound = [...timeline.value].sort((a, b) => (b.total_actions || 0) - (a.total_actions || 0))[0]
      const nextRound = hottestRound?.round_num ?? timeline.value[0].round_num ?? 0
      const shouldForceInitialLoad = nextRound === selectedRound.value
      selectedRound.value = nextRound
      if (shouldForceInitialLoad) {
        await loadRoundActions()
      }
    } else {
      selectedRound.value = 0
      await loadRoundActions()
    }

    currentStatus.value = 'completed'
  } catch (error) {
    console.error('加载反事实工作台失败:', error)
    currentStatus.value = 'error'
  }
}

function handleLaunched(payload) {
  const simulationId = payload?.simulation?.simulation_id
  if (!simulationId) return
  router.push({
    name: 'SimulationRun',
    params: { simulationId }
  })
}

watch(selectedRound, async (round, previousRound) => {
  if (round === null || round === undefined) return
  if (round === previousRound && branchRoundActions.value.length > 0) return
  await loadRoundActions()
})

watch(baseSimulationId, async (nextId, previousId) => {
  if (!nextId || nextId === previousId) return
  try {
    const response = await getSimulationTimeline(nextId, 0)
    baseTimeline.value = response.data?.timeline || []
  } catch (error) {
    console.warn('刷新基线时间线失败:', error)
    baseTimeline.value = []
  }
})

onMounted(async () => {
  addLog('Counterfactual branch workbench armed')
  await loadBaseData()
})
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(circle at top, rgba(22, 48, 38, 0.96), rgba(5, 10, 8, 0.98) 44%),
    #050908;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.app-header {
  height: 60px;
  border-bottom: 1px solid rgba(122, 240, 181, 0.12);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: rgba(5, 9, 8, 0.88);
  backdrop-filter: blur(18px);
  z-index: 100;
  position: relative;
}

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 16px;
  letter-spacing: 0.14em;
  cursor: pointer;
  color: #dffeed;
}

.view-switcher {
  display: flex;
  background: rgba(255, 255, 255, 0.04);
  padding: 4px;
  border-radius: 6px;
  gap: 4px;
  border: 1px solid rgba(122, 240, 181, 0.1);
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: rgba(219, 255, 237, 0.58);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.switch-btn.active {
  background: rgba(122, 240, 181, 0.12);
  color: #f0fff7;
  box-shadow: inset 0 0 0 1px rgba(122, 240, 181, 0.08);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  color: rgba(219, 255, 237, 0.72);
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: rgba(219, 255, 237, 0.52);
}

.step-name {
  font-weight: 700;
  color: #eafef4;
}

.step-divider {
  width: 1px;
  height: 14px;
  background-color: rgba(122, 240, 181, 0.12);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(219, 255, 237, 0.58);
  font-weight: 500;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}

.status-indicator.processing .dot {
  background: #ffbf67;
  animation: pulse 1s infinite;
}

.status-indicator.completed .dot {
  background: #4de2a5;
}

.status-indicator.error .dot {
  background: #ff6767;
}

@keyframes pulse {
  50% { opacity: 0.5; }
}

.content-area {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1), opacity 0.3s ease, transform 0.3s ease;
}

.panel-wrapper.left {
  border-right: 1px solid rgba(122, 240, 181, 0.12);
}

.panel-wrapper.right {
  background: rgba(5, 9, 8, 0.86);
}
</style>
