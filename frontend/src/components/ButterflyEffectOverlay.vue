<template>
  <section v-if="isEnabled" class="butterfly-shell">
    <div class="shell-head">
      <div class="head-copy">
        <div class="head-kicker">BUTTERFLY EFFECT // COUNTERFACTUAL BRANCH</div>
        <h3>{{ actorName }} @ R{{ injectionRound }}</h3>
        <p>
          Tracking how the injected actor bends the branch against base run
          <strong>{{ compactId(baseSimulationId) }}</strong>.
        </p>
      </div>

      <div class="shell-tags">
        <span class="shell-tag">BASE {{ compactId(baseSimulationId) }}</span>
        <span class="shell-tag active">BRANCH {{ compactId(simulationId) }}</span>
        <span class="shell-tag">{{ overlayLoading ? 'SYNCING BASE' : (runStatus?.runner_status || 'running').toUpperCase() }}</span>
      </div>
    </div>

    <div class="impact-grid">
      <article class="impact-card">
        <span class="impact-label">Post-Injection Delta</span>
        <span class="impact-value" :class="{ positive: postInjectionDelta >= 0, negative: postInjectionDelta < 0 }">
          {{ signed(postInjectionDelta) }}
        </span>
        <span class="impact-copy">branch {{ branchPostInjectionActions }} vs base {{ basePostInjectionActions }}</span>
      </article>

      <article class="impact-card">
        <span class="impact-label">Injected Actor Actions</span>
        <span class="impact-value">{{ actorActions.length }}</span>
        <span class="impact-copy">{{ actorStance }} · influence {{ actorInfluence }}</span>
      </article>

      <article class="impact-card">
        <span class="impact-label">Amplifying Agents</span>
        <span class="impact-value">{{ topAmplifiers.length }}</span>
        <span class="impact-copy">{{ amplificationEvents.length }} direct uptake events</span>
      </article>

      <article class="impact-card">
        <span class="impact-label">Leader Drift</span>
        <span class="impact-value">{{ enteredLeaders.length }}</span>
        <span class="impact-copy">{{ enteredLeaders.map(item => item.agent_name).slice(0, 2).join(' · ') || 'Stable leadership' }}</span>
      </article>
    </div>

    <div class="compare-grid">
      <section class="compare-panel timeline-panel">
        <div class="panel-head">
          <div>
            <div class="panel-kicker">BRANCH VS BASE TIMELINE</div>
            <div class="panel-title">Interactive divergence map</div>
          </div>
          <div class="panel-copy">
            Round {{ selectedRound }} · Branch {{ selectedRoundData.branch }} / Base {{ selectedRoundData.base }}
          </div>
        </div>

        <div class="timeline-strip">
          <button
            v-for="round in compareRounds"
            :key="round.round"
            class="round-cell"
            :class="{
              active: round.round === selectedRound,
              injected: round.round === injectionRound,
              positive: round.delta > 0,
              negative: round.delta < 0
            }"
            @click="selectedRound = round.round"
          >
            <span class="bar-track">
              <span class="bar base" :style="heightStyle(round.base)"></span>
              <span class="bar branch" :style="heightStyle(round.branch)"></span>
              <span v-if="round.actor > 0" class="actor-dot" :style="actorDotStyle(round.actor)"></span>
            </span>
            <span class="round-num">{{ round.round }}</span>
          </button>
        </div>

        <div class="round-detail-grid">
          <div class="round-detail-card">
            <span class="detail-label">Round Delta</span>
            <span class="detail-value" :class="{ positive: selectedRoundData.delta >= 0, negative: selectedRoundData.delta < 0 }">
              {{ signed(selectedRoundData.delta) }}
            </span>
          </div>
          <div class="round-detail-card">
            <span class="detail-label">Actor Touches</span>
            <span class="detail-value">{{ selectedRoundData.actor }}</span>
          </div>
          <div class="round-detail-card">
            <span class="detail-label">Uptake This Round</span>
            <span class="detail-value">{{ selectedRoundAmplifiers.length }}</span>
          </div>
        </div>
      </section>

      <section class="compare-panel impact-panel">
        <div class="panel-head">
          <div>
            <div class="panel-kicker">INDIVIDUAL IMPACT</div>
            <div class="panel-title">{{ actorName }}</div>
          </div>
          <div class="panel-copy">injected @ round {{ injectionRound }}</div>
        </div>

        <div class="impact-stream">
          <article
            v-for="action in actorActionPreview"
            :key="`${action.timestamp}-${action.agent_id}-${action.action_type}`"
            class="impact-item"
          >
            <div class="impact-item-top">
              <span>{{ actionTypeLabel(action.action_type) }}</span>
              <span>R{{ action.round_num || action.round || 0 }}</span>
            </div>
            <div class="impact-item-body">{{ actionText(action) }}</div>
          </article>

          <div v-if="actorActionPreview.length === 0" class="impact-empty">
            No branch actions from the injected actor yet.
          </div>
        </div>
      </section>
    </div>

    <div class="compare-grid lower">
      <section class="compare-panel uptake-panel">
        <div class="panel-head">
          <div>
            <div class="panel-kicker">FRAME PROPAGATION</div>
            <div class="panel-title">Who picked up the injected frame</div>
          </div>
          <div class="panel-copy">{{ amplificationEvents.length }} direct references</div>
        </div>

        <div class="pill-row">
          <span v-for="term in frameKeywords" :key="term.term" class="signal-pill">
            {{ term.term }} · {{ term.count }}
          </span>
          <span v-if="frameKeywords.length === 0" class="signal-pill muted">Awaiting distinct frame terms</span>
        </div>

        <div class="amplifier-list">
          <article v-for="amplifier in topAmplifiers" :key="amplifier.agent_name" class="amplifier-row">
            <div>
              <div class="amplifier-name">{{ amplifier.agent_name }}</div>
              <div class="amplifier-meta">{{ amplifier.actions.join(' · ') }}</div>
            </div>
            <span class="amplifier-count">{{ amplifier.count }}</span>
          </article>

          <div v-if="topAmplifiers.length === 0" class="impact-empty">
            No direct amplifier events detected yet.
          </div>
        </div>
      </section>

      <section class="compare-panel drift-panel">
        <div class="panel-head">
          <div>
            <div class="panel-kicker">POWER SHIFT</div>
            <div class="panel-title">Leader changes vs base</div>
          </div>
          <div class="panel-copy">top-agent roster drift</div>
        </div>

        <div class="drift-grid">
          <div class="drift-column">
            <div class="drift-label">Entered Branch Leaders</div>
            <div class="drift-list">
              <div v-for="agent in enteredLeaders" :key="agent.agent_id" class="drift-item">
                <span>{{ agent.agent_name }}</span>
                <strong>{{ agent.total_actions }}</strong>
              </div>
              <div v-if="enteredLeaders.length === 0" class="impact-empty small">No new leaders</div>
            </div>
          </div>

          <div class="drift-column">
            <div class="drift-label">Dropped From Base</div>
            <div class="drift-list">
              <div v-for="agent in droppedLeaders" :key="agent.agent_id" class="drift-item">
                <span>{{ agent.agent_name }}</span>
                <strong>{{ agent.total_actions }}</strong>
              </div>
              <div v-if="droppedLeaders.length === 0" class="impact-empty small">No major exits</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getAgentStats, getSimulationTimeline } from '../api/simulation'

const props = defineProps({
  simulationId: {
    type: String,
    default: ''
  },
  simulationConfig: {
    type: Object,
    default: null
  },
  branchActions: {
    type: Array,
    default: () => []
  },
  runStatus: {
    type: Object,
    default: () => ({})
  }
})

const baseTimeline = ref([])
const baseAgentStats = ref([])
const overlayLoading = ref(false)
const selectedRound = ref(0)

const counterfactual = computed(() => props.simulationConfig?.counterfactual || null)
const isEnabled = computed(() => Boolean(counterfactual.value?.base_simulation_id))
const baseSimulationId = computed(() => counterfactual.value?.base_simulation_id || '')
const injectionRound = computed(() => Number(counterfactual.value?.injection_round || 0))
const actorName = computed(() => counterfactual.value?.actor_name || 'Injected actor')
const actorProfile = computed(() => {
  return (props.simulationConfig?.agent_configs || []).find(agent => agent.counterfactual || agent.entity_name === actorName.value) || null
})
const actorId = computed(() => actorProfile.value?.agent_id ?? null)
const actorStance = computed(() => actorProfile.value?.stance || counterfactual.value?.entity_type || 'counterfactual')
const actorInfluence = computed(() => {
  const value = actorProfile.value?.influence_weight
  return typeof value === 'number' ? value.toFixed(1) : 'n/a'
})

const branchTimeline = computed(() => {
  const rounds = new Map()
  props.branchActions.forEach(action => {
    const round = Number(action.round_num ?? action.round ?? 0)
    if (!rounds.has(round)) {
      rounds.set(round, { round_num: round, total_actions: 0, actor_actions: 0 })
    }
    const bucket = rounds.get(round)
    bucket.total_actions += 1
    if (actorId.value !== null && action.agent_id === actorId.value) {
      bucket.actor_actions += 1
    }
  })
  return [...rounds.values()].sort((left, right) => left.round_num - right.round_num)
})

const branchAgentStats = computed(() => {
  const stats = new Map()
  props.branchActions.forEach(action => {
    const key = action.agent_id ?? action.agent_name
    if (!stats.has(key)) {
      stats.set(key, {
        agent_id: action.agent_id,
        agent_name: action.agent_name || `Agent ${action.agent_id}`,
        total_actions: 0
      })
    }
    stats.get(key).total_actions += 1
  })
  return [...stats.values()].sort((left, right) => right.total_actions - left.total_actions)
})

const actorActions = computed(() => {
  if (actorId.value === null) return []
  return props.branchActions.filter(action => action.agent_id === actorId.value)
})

const amplificationEvents = computed(() => {
  if (!actorName.value) return []
  return props.branchActions.filter(action => {
    if (actorId.value !== null && action.agent_id === actorId.value) return false
    const args = action.action_args || {}
    const names = [args.original_author_name, args.post_author_name, args.author_name]
      .map(value => String(value || '').trim())
      .filter(Boolean)
    return names.includes(actorName.value)
  })
})

const topAmplifiers = computed(() => {
  const stats = new Map()
  amplificationEvents.value.forEach(action => {
    const name = action.agent_name || `Agent ${action.agent_id}`
    if (!stats.has(name)) {
      stats.set(name, { agent_name: name, count: 0, actions: new Set() })
    }
    const bucket = stats.get(name)
    bucket.count += 1
    bucket.actions.add(actionTypeLabel(action.action_type))
  })
  return [...stats.values()]
    .map(item => ({ ...item, actions: [...item.actions] }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 6)
})

const compareRounds = computed(() => {
  const baseMap = new Map(baseTimeline.value.map(item => [Number(item.round_num || 0), item]))
  const branchMap = new Map(branchTimeline.value.map(item => [Number(item.round_num || 0), item]))
  const rounds = [...new Set([...baseMap.keys(), ...branchMap.keys()])].sort((left, right) => left - right)
  return rounds.map(round => {
    const base = baseMap.get(round)?.total_actions || 0
    const branch = branchMap.get(round)?.total_actions || 0
    const actor = branchMap.get(round)?.actor_actions || 0
    return {
      round,
      base,
      branch,
      actor,
      delta: branch - base
    }
  })
})

const selectedRoundData = computed(() => {
  return compareRounds.value.find(item => item.round === selectedRound.value) || {
    round: selectedRound.value,
    base: 0,
    branch: 0,
    actor: 0,
    delta: 0
  }
})

const actorActionPreview = computed(() => {
  const roundSpecific = actorActions.value.filter(action => Number(action.round_num ?? action.round ?? 0) === selectedRound.value)
  const source = roundSpecific.length > 0 ? roundSpecific : actorActions.value
  return source.slice(0, 4)
})

const selectedRoundAmplifiers = computed(() => {
  return amplificationEvents.value.filter(action => Number(action.round_num ?? action.round ?? 0) === selectedRound.value)
})

const maxBarValue = computed(() => {
  return Math.max(...compareRounds.value.map(item => Math.max(item.base, item.branch)), 1)
})

const branchPostInjectionActions = computed(() => {
  return compareRounds.value
    .filter(item => item.round >= injectionRound.value)
    .reduce((sum, item) => sum + item.branch, 0)
})

const basePostInjectionActions = computed(() => {
  return compareRounds.value
    .filter(item => item.round >= injectionRound.value)
    .reduce((sum, item) => sum + item.base, 0)
})

const postInjectionDelta = computed(() => branchPostInjectionActions.value - basePostInjectionActions.value)

const baseLeaderIds = computed(() => new Set(baseAgentStats.value.slice(0, 8).map(item => item.agent_id)))
const enteredLeaders = computed(() => {
  return branchAgentStats.value
    .filter(item => !baseLeaderIds.value.has(item.agent_id))
    .slice(0, 4)
})
const branchLeaderIds = computed(() => new Set(branchAgentStats.value.slice(0, 8).map(item => item.agent_id)))
const droppedLeaders = computed(() => {
  return baseAgentStats.value
    .filter(item => !branchLeaderIds.value.has(item.agent_id))
    .slice(0, 4)
})

const frameKeywords = computed(() => {
  const texts = [
    ...actorActions.value.map(action => actionText(action)),
    ...amplificationEvents.value.map(action => actionText(action))
  ].join(' ').toLowerCase()
  if (!texts) return []

  const stopwords = new Set([
    'the', 'and', 'that', 'with', 'from', 'into', 'this', 'just', 'treat',
    'they', 'their', 'about', 'your', 'have', 'will', 'what', 'when', 'where',
    'which', 'under', 'actor', 'branch', 'core', 'variable', 'now', 'post',
    'comment', 'likes', 'like', 'said', 'says', 'amid', 'over', 'through',
    'gulf', 'transits', 'round', 'original', 'content', 'headline', 'headlines'
  ])

  const counts = new Map()
  texts.match(/[a-z][a-z-]{2,}/g)?.forEach(token => {
    if (stopwords.has(token)) return
    if (token === actorName.value.toLowerCase()) return
    counts.set(token, (counts.get(token) || 0) + 1)
  })

  return [...counts.entries()]
    .map(([term, count]) => ({ term, count }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 6)
})

watch(compareRounds, (rounds) => {
  if (!rounds.length) {
    selectedRound.value = 0
    return
  }
  if (rounds.some(item => item.round === selectedRound.value)) return
  const hottestDelta = rounds
    .filter(item => item.round >= injectionRound.value)
    .sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta))[0]
  selectedRound.value = hottestDelta?.round || injectionRound.value || rounds[0].round
}, { immediate: true })

watch(baseSimulationId, async (simulationId) => {
  if (!simulationId) {
    baseTimeline.value = []
    baseAgentStats.value = []
    return
  }

  overlayLoading.value = true
  try {
    const [timelineRes, agentStatsRes] = await Promise.all([
      getSimulationTimeline(simulationId, 0),
      getAgentStats(simulationId)
    ])
    baseTimeline.value = timelineRes.data?.timeline || []
    baseAgentStats.value = agentStatsRes.data || []
  } catch (error) {
    console.error('加载 base simulation comparison 失败:', error)
    baseTimeline.value = []
    baseAgentStats.value = []
  } finally {
    overlayLoading.value = false
  }
}, { immediate: true })

function compactId(value) {
  return String(value || 'sim_unknown').replace('sim_', 'SIM_').toUpperCase()
}

function heightStyle(value) {
  const pct = Math.max(8, (value / maxBarValue.value) * 100)
  return { height: `${pct}%` }
}

function actorDotStyle(value) {
  const pct = Math.max(10, (value / Math.max(...compareRounds.value.map(item => item.actor), 1)) * 100)
  return { bottom: `${Math.min(92, pct)}%` }
}

function signed(value) {
  if (value > 0) return `+${value}`
  return `${value}`
}

function actionTypeLabel(type) {
  const labels = {
    CREATE_POST: 'POST',
    REPOST: 'REPOST',
    LIKE_POST: 'LIKE',
    LIKE_COMMENT: 'LIKE',
    CREATE_COMMENT: 'COMMENT',
    QUOTE_POST: 'QUOTE'
  }
  return labels[type] || type || 'ACTION'
}

function actionText(action) {
  const args = action.action_args || {}
  return args.content || args.quote_content || args.original_content || args.post_content || 'No captured body.'
}
</script>

<style scoped>
.butterfly-shell {
  margin: 18px 24px 0;
  padding: 18px;
  border: 1px solid rgba(255, 206, 122, 0.18);
  background:
    linear-gradient(180deg, rgba(16, 15, 9, 0.94), rgba(9, 10, 7, 0.96)),
    radial-gradient(circle at top right, rgba(255, 206, 122, 0.08), transparent 38%);
  box-shadow: 0 22px 40px rgba(0, 0, 0, 0.22);
}

.shell-head,
.impact-grid,
.panel-head,
.impact-item-top,
.amplifier-row,
.drift-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.shell-head {
  align-items: flex-start;
}

.head-kicker,
.shell-tag,
.impact-label,
.panel-kicker,
.panel-copy,
.detail-label,
.amplifier-meta,
.drift-label,
.round-num {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.head-kicker,
.impact-label,
.panel-kicker,
.panel-copy,
.detail-label,
.amplifier-meta,
.drift-label,
.round-num {
  font-size: 10px;
  color: rgba(255, 239, 206, 0.62);
}

.head-copy h3,
.panel-title {
  margin: 10px 0 6px;
  color: #fff8e6;
}

.head-copy h3 {
  font-size: 28px;
}

.head-copy p {
  margin: 0;
  color: rgba(255, 245, 224, 0.78);
  line-height: 1.7;
  max-width: 720px;
}

.shell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.shell-tag {
  padding: 6px 8px;
  border: 1px solid rgba(255, 206, 122, 0.16);
  color: rgba(255, 239, 206, 0.82);
}

.shell-tag.active {
  border-color: rgba(122, 240, 181, 0.24);
  color: #8cf6c2;
}

.impact-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.impact-card,
.compare-panel,
.round-detail-card {
  border: 1px solid rgba(255, 206, 122, 0.1);
  background: rgba(255, 255, 255, 0.03);
}

.impact-card {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.impact-value,
.detail-value,
.amplifier-count {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
}

.impact-value {
  font-size: 28px;
  color: #fff8e6;
}

.impact-value.positive,
.detail-value.positive {
  color: #8cf6c2;
}

.impact-value.negative,
.detail-value.negative {
  color: #ff9f8f;
}

.impact-copy {
  color: rgba(255, 245, 224, 0.68);
  font-size: 12px;
  line-height: 1.6;
}

.compare-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.9fr);
  gap: 12px;
  margin-top: 12px;
}

.compare-grid.lower {
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
}

.compare-panel {
  padding: 14px;
}

.timeline-strip {
  margin-top: 14px;
  padding-bottom: 6px;
  display: flex;
  align-items: flex-end;
  gap: 6px;
  overflow-x: auto;
}

.round-cell {
  width: 30px;
  flex: 0 0 30px;
  border: 1px solid rgba(255, 206, 122, 0.08);
  background: rgba(255, 255, 255, 0.02);
  padding: 8px 4px 6px;
  cursor: pointer;
}

.round-cell.active {
  border-color: rgba(255, 206, 122, 0.28);
  background: rgba(255, 206, 122, 0.07);
}

.round-cell.injected {
  box-shadow: inset 0 0 0 1px rgba(122, 240, 181, 0.24);
}

.bar-track {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 3px;
  height: 100px;
}

.bar {
  width: 7px;
  min-height: 8px;
  align-self: flex-end;
}

.bar.base {
  background: rgba(255, 206, 122, 0.38);
}

.bar.branch {
  background: rgba(122, 240, 181, 0.78);
}

.actor-dot {
  position: absolute;
  left: 50%;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #fff8e6;
  transform: translateX(-50%);
}

.round-num {
  display: block;
  margin-top: 8px;
  text-align: center;
}

.round-detail-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.round-detail-card {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-value {
  font-size: 20px;
  color: #fff8e6;
}

.impact-stream,
.amplifier-list,
.drift-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.impact-item,
.amplifier-row,
.drift-item {
  padding: 10px 12px;
  border: 1px solid rgba(255, 206, 122, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.impact-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.impact-item-body,
.amplifier-name,
.drift-item span {
  color: rgba(255, 245, 224, 0.86);
  line-height: 1.6;
}

.impact-empty {
  padding: 12px;
  border: 1px dashed rgba(255, 206, 122, 0.12);
  color: rgba(255, 245, 224, 0.52);
  font-size: 12px;
}

.impact-empty.small {
  padding: 8px 10px;
}

.pill-row {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.signal-pill {
  padding: 6px 10px;
  border: 1px solid rgba(122, 240, 181, 0.16);
  color: #8cf6c2;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
}

.signal-pill.muted {
  border-color: rgba(255, 206, 122, 0.12);
  color: rgba(255, 245, 224, 0.58);
}

.amplifier-count,
.drift-item strong {
  color: #fff8e6;
}

.drift-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.drift-column {
  min-width: 0;
}

@media (max-width: 1180px) {
  .impact-grid,
  .compare-grid,
  .compare-grid.lower,
  .round-detail-grid,
  .drift-grid {
    grid-template-columns: 1fr;
  }

  .shell-head {
    flex-direction: column;
  }
}
</style>
