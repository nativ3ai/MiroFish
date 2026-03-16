<template>
  <div class="forensics-panel">
    <section class="panel-block hero-block">
      <div class="block-head hero-head">
        <div>
          <span class="block-kicker">BRANCH FORENSICS</span>
          <h2 class="block-title">Counterfactual Diff Console</h2>
          <p class="block-copy">
            {{ actorName }} forks the base run at round {{ injectionRound }}. Scrub the timeline,
            inspect the selected round, and trace how branch relationships diverged from the legacy path.
          </p>
          <p class="hero-note">{{ requirementExcerpt }}</p>
        </div>

        <button class="lab-btn" @click="$emit('open-lab')">Inject Another Actor</button>
      </div>

      <div class="tag-row">
        <span class="tag">BASE {{ compactBaseId }}</span>
        <span class="tag active">BRANCH {{ compactBranchId }}</span>
        <span class="tag actor">{{ actorName }}</span>
      </div>

      <div class="metric-grid">
        <article class="metric-card">
          <span class="metric-label">Branch Actions</span>
          <span class="metric-value">{{ totalBranchActions }}</span>
          <span class="metric-copy">{{ totalRounds }} rounds recorded</span>
        </article>
        <article class="metric-card">
          <span class="metric-label">Base Actions</span>
          <span class="metric-value">{{ totalBaseActions }}</span>
          <span class="metric-copy">Legacy comparison window</span>
        </article>
        <article class="metric-card emphasis">
          <span class="metric-label">Round {{ selectedRound }} Delta</span>
          <span class="metric-value" :class="{ positive: selectedRoundDelta >= 0, negative: selectedRoundDelta < 0 }">
            {{ signed(selectedRoundDelta) }}
          </span>
          <span class="metric-copy">branch {{ selectedRoundBranchCount }} vs base {{ selectedRoundBaseCount }}</span>
        </article>
        <article class="metric-card">
          <span class="metric-label">Injected Actor</span>
          <span class="metric-value">{{ selectedRoundActorActions.length }}</span>
          <span class="metric-copy">actions in selected round</span>
        </article>
      </div>
    </section>

    <section class="panel-block round-block">
      <div class="block-head">
        <div>
          <span class="block-kicker">ROUND SCRUBBER</span>
          <div class="section-title">R{{ selectedRound }}</div>
        </div>
        <div class="round-meta">
          <span class="round-chip">INJECTION @ {{ injectionRound }}</span>
          <span class="round-chip">UPTAKE {{ selectedRoundAmplifiers.length }}</span>
        </div>
      </div>

      <input
        class="round-slider"
        type="range"
        :min="0"
        :max="sliderMax"
        :value="selectedRound"
        @input="emitRound($event.target.value)"
      />

      <div class="round-labels">
        <span>0</span>
        <span>{{ Math.floor(sliderMax / 2) }}</span>
        <span>{{ sliderMax }}</span>
      </div>

      <div class="compare-strip">
        <button
          v-for="round in compareRounds"
          :key="round.round"
          class="compare-cell"
          :class="{
            active: round.round === selectedRound,
            injected: round.round === injectionRound,
            positive: round.delta > 0,
            negative: round.delta < 0
          }"
          @click="emitRound(round.round)"
          :title="`Round ${round.round}: branch ${round.branch} / base ${round.base}`"
        >
          <span class="compare-bars">
            <span class="compare-bar base" :style="barStyle(round.base)"></span>
            <span class="compare-bar branch" :style="barStyle(round.branch)"></span>
            <span v-if="round.actor > 0" class="actor-blip" :style="blipStyle(round.actor)"></span>
          </span>
          <span class="compare-label">{{ round.round }}</span>
        </button>
      </div>

      <div class="round-summary-grid">
        <article class="round-summary-card">
          <span class="round-summary-label">Branch</span>
          <span class="round-summary-value">{{ selectedRoundBranchCount }}</span>
        </article>
        <article class="round-summary-card">
          <span class="round-summary-label">Base</span>
          <span class="round-summary-value">{{ selectedRoundBaseCount }}</span>
        </article>
        <article class="round-summary-card">
          <span class="round-summary-label">Actor Touches</span>
          <span class="round-summary-value">{{ selectedRoundActorActions.length }}</span>
        </article>
        <article class="round-summary-card">
          <span class="round-summary-label">Amplifiers</span>
          <span class="round-summary-value">{{ selectedRoundAmplifiers.length }}</span>
        </article>
      </div>
    </section>

    <section class="panel-block graph-block">
      <div class="block-head graph-head">
        <div>
          <span class="block-kicker">RELATIONSHIP TIMELINE</span>
          <div class="section-title">Branch Graph @ Round {{ selectedRound }}</div>
        </div>
        <div class="round-meta">
          <span class="round-chip">FOCUS {{ focusedAgent || 'ALL AGENTS' }}</span>
          <span class="round-chip">{{ graphEdges.length }} LINKS</span>
        </div>
      </div>

      <div class="signal-row">
        <button
          v-for="signal in signalTerms"
          :key="signal.term"
          class="signal-pill"
        >
          {{ signal.term }} · {{ signal.count }}
        </button>
        <span v-if="signalTerms.length === 0" class="signal-pill muted">No distinct branch terms in this round.</span>
      </div>

      <div class="graph-stage">
        <svg viewBox="0 0 1000 360" class="graph-svg">
          <defs>
            <linearGradient id="branchPath" x1="0%" x2="100%" y1="0%" y2="0%">
              <stop offset="0%" stop-color="#5f6b66" />
              <stop offset="52%" stop-color="#ffd36a" />
              <stop offset="100%" stop-color="#4de2a5" />
            </linearGradient>
          </defs>

          <g class="stage-grid">
            <line v-for="row in [60, 120, 180, 240, 300]" :key="row" x1="60" :y1="row" x2="940" :y2="row"></line>
          </g>

          <path class="stage-path" d="M 300 180 C 380 180, 405 140, 500 120 C 590 102, 618 168, 690 180"></path>
          <text x="500" y="92" class="stage-annotation">counterfactual fork</text>
          <text x="258" y="330" class="stage-caption">Base signal</text>
          <text x="460" y="330" class="stage-caption">Injection @ R{{ injectionRound }}</text>
          <text x="654" y="330" class="stage-caption">Branch signal</text>

          <g v-for="edge in graphEdges" :key="edge.id" class="edge-layer">
            <line
              :x1="edge.x1"
              :y1="edge.y1"
              :x2="edge.x2"
              :y2="edge.y2"
              class="edge-line"
              :class="edge.kind"
              :style="{ '--edge-opacity': edge.opacity, '--edge-width': edge.width }"
            />
            <text :x="edge.labelX" :y="edge.labelY" class="edge-badge">{{ edge.label }}</text>
          </g>

          <g v-for="node in graphNodes" :key="node.id" class="node-layer" @click="handleNodeClick(node)">
            <rect
              :x="node.x - node.width / 2"
              :y="node.y - node.height / 2"
              :width="node.width"
              :height="node.height"
              rx="14"
              class="node-shell"
              :class="[node.kind, { active: focusedAgent === node.agentKey }]"
            />
            <text :x="node.x" :y="node.y - 5" class="node-title">{{ node.title }}</text>
            <text :x="node.x" :y="node.y + 14" class="node-subtitle">{{ node.subtitle }}</text>
          </g>
        </svg>
      </div>
    </section>

    <section class="panel-block feed-block">
      <div class="block-head feed-head">
        <div>
          <span class="block-kicker">ROUND FEED</span>
          <div class="section-title">Detailed event stream</div>
        </div>
        <div class="filter-row">
          <button
            v-for="mode in feedModes"
            :key="mode.id"
            class="filter-chip"
            :class="{ active: feedMode === mode.id }"
            @click="feedMode = mode.id"
          >
            {{ mode.label }}
          </button>
        </div>
      </div>

      <div class="feed-grid">
        <section class="feed-column branch">
          <div class="feed-column-head">
            <span>Branch / R{{ selectedRound }}</span>
            <span>{{ loadingActions ? 'SYNCING' : `${filteredBranchActions.length} EVENTS` }}</span>
          </div>
          <div v-if="loadingActions" class="empty-state">Loading branch actions...</div>
          <div v-else-if="filteredBranchActions.length === 0" class="empty-state">No branch actions match this filter.</div>
          <div v-else class="action-list">
            <article
              v-for="action in filteredBranchActions.slice(0, 18)"
              :key="action.id || `${action.timestamp}-${action.agent_id}-${action.action_type}`"
              class="action-item"
            >
              <div class="action-top">
                <div>
                  <div class="action-agent">{{ action.agent_name || `Agent ${action.agent_id}` }}</div>
                  <div class="action-context">{{ actionTypeLabel(action.action_type) }} · {{ contextLabel(action) }}</div>
                </div>
                <span class="action-time">{{ formatTime(action.timestamp) }}</span>
              </div>
              <div class="action-body">{{ actionText(action) }}</div>
            </article>
          </div>
        </section>

        <section class="feed-column base">
          <div class="feed-column-head">
            <span>Base / R{{ selectedRound }}</span>
            <span>{{ loadingActions ? 'SYNCING' : `${filteredBaseActions.length} EVENTS` }}</span>
          </div>
          <div v-if="loadingActions" class="empty-state">Loading base actions...</div>
          <div v-else-if="filteredBaseActions.length === 0" class="empty-state">No base actions match this filter.</div>
          <div v-else class="action-list">
            <article
              v-for="action in filteredBaseActions.slice(0, 18)"
              :key="action.id || `${action.timestamp}-${action.agent_id}-${action.action_type}`"
              class="action-item"
            >
              <div class="action-top">
                <div>
                  <div class="action-agent">{{ action.agent_name || `Agent ${action.agent_id}` }}</div>
                  <div class="action-context">{{ actionTypeLabel(action.action_type) }} · {{ contextLabel(action) }}</div>
                </div>
                <span class="action-time">{{ formatTime(action.timestamp) }}</span>
              </div>
              <div class="action-body">{{ actionText(action) }}</div>
            </article>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  simulationId: String,
  baseSimulationId: String,
  simulationData: Object,
  simulationConfig: Object,
  timeline: {
    type: Array,
    default: () => []
  },
  baseTimeline: {
    type: Array,
    default: () => []
  },
  agentStats: {
    type: Array,
    default: () => []
  },
  branchRoundActions: {
    type: Array,
    default: () => []
  },
  baseRoundActions: {
    type: Array,
    default: () => []
  },
  selectedRound: {
    type: Number,
    default: 0
  },
  loadingActions: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:selectedRound', 'open-lab'])

const feedMode = ref('all')
const focusedAgent = ref('')

const compactBranchId = computed(() => compactId(props.simulationId))
const compactBaseId = computed(() => compactId(props.baseSimulationId))
const counterfactual = computed(() => props.simulationConfig?.counterfactual || {})
const actorProfile = computed(() => (props.simulationConfig?.agent_configs || []).find(agent => agent.counterfactual) || null)
const actorName = computed(() => counterfactual.value?.actor_name || actorProfile.value?.entity_name || 'Injected actor')
const actorId = computed(() => actorProfile.value?.agent_id ?? null)
const injectionRound = computed(() => Number(counterfactual.value?.injection_round || 0))
const requirementExcerpt = computed(() => {
  const requirement = props.simulationConfig?.simulation_requirement || props.simulationData?.simulation_requirement || ''
  if (!requirement) return 'Counterfactual branch ready for round-level inspection.'
  return requirement.length > 240 ? `${requirement.slice(0, 240)}...` : requirement
})

const totalBranchActions = computed(() => props.timeline.reduce((sum, round) => sum + (round.total_actions || 0), 0))
const totalBaseActions = computed(() => props.baseTimeline.reduce((sum, round) => sum + (round.total_actions || 0), 0))
const totalRounds = computed(() => props.timeline.length ? Math.max(...props.timeline.map(item => item.round_num || 0)) : 0)
const sliderMax = computed(() => Math.max(totalRounds.value, 1))

const compareRounds = computed(() => {
  const baseMap = new Map(props.baseTimeline.map(item => [Number(item.round_num || 0), item]))
  const branchMap = new Map(props.timeline.map(item => [Number(item.round_num || 0), item]))
  const rounds = [...new Set([...baseMap.keys(), ...branchMap.keys()])].sort((left, right) => left - right)
  return rounds.map(round => {
    const base = baseMap.get(round)?.total_actions || 0
    const branch = branchMap.get(round)?.total_actions || 0
    const actor = branchRoundActorCounts.value.get(round) || 0
    return {
      round,
      base,
      branch,
      actor,
      delta: branch - base
    }
  })
})

const branchRoundActorCounts = computed(() => {
  const counts = new Map()
  props.timeline.forEach(round => counts.set(Number(round.round_num || 0), 0))
  if (actorId.value === null) return counts
  props.branchRoundActions.forEach(action => {
    const round = Number(action.round_num ?? action.round ?? 0)
    if (action.agent_id === actorId.value) {
      counts.set(round, (counts.get(round) || 0) + 1)
    }
  })
  return counts
})

const selectedRoundRow = computed(() => {
  return compareRounds.value.find(item => item.round === props.selectedRound) || {
    round: props.selectedRound,
    base: 0,
    branch: 0,
    actor: 0,
    delta: 0
  }
})

const selectedRoundBaseCount = computed(() => selectedRoundRow.value.base)
const selectedRoundBranchCount = computed(() => selectedRoundRow.value.branch)
const selectedRoundDelta = computed(() => selectedRoundRow.value.delta)

const selectedRoundActorActions = computed(() => {
  if (actorId.value !== null) {
    return props.branchRoundActions.filter(action => action.agent_id === actorId.value)
  }
  return props.branchRoundActions.filter(action => (action.agent_name || '') === actorName.value)
})

const selectedRoundAmplifiers = computed(() => {
  return props.branchRoundActions.filter(action => {
    if (actorId.value !== null && action.agent_id === actorId.value) return false
    return referencedNames(action).includes(actorName.value)
  })
})

const baseRoundLeaders = computed(() => groupAgents(props.baseRoundActions).slice(0, 4))
const branchRoundLeaders = computed(() => groupAgents(props.branchRoundActions).filter(item => item.agent_name !== actorName.value).slice(0, 6))
const amplifierLeaders = computed(() => groupAgents(selectedRoundAmplifiers.value).slice(0, 6))

const signalTerms = computed(() => {
  const stopwords = new Set([
    'the', 'and', 'that', 'with', 'from', 'have', 'this', 'were', 'they', 'will', 'into', 'about', 'amid',
    'iran', 'deal', 'hormuz', 'round', 'branch', 'base', 'actor', 'said', 'says', 'just', 'treat', 'under',
    'gulf', 'transits', 'news', 'risk', 'risks', 'market', 'markets', 'post', 'comment', 'quote', 'original'
  ])
  const counts = new Map()
  props.branchRoundActions.forEach(action => {
    actionText(action).toLowerCase().match(/[a-z][a-z-]{2,}/g)?.forEach(token => {
      if (stopwords.has(token)) return
      counts.set(token, (counts.get(token) || 0) + 1)
    })
  })
  return [...counts.entries()]
    .map(([term, count]) => ({ term, count }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 7)
})

const graphNodes = computed(() => {
  const baseNodes = layoutSideNodes(baseRoundLeaders.value, 120, 'base-agent')
  const branchSeed = mergeBranchNodes(branchRoundLeaders.value, amplifierLeaders.value)
  const branchNodes = layoutSideNodes(branchSeed, 870, 'branch-agent')
  const nodes = [
    { id: 'base-hub', title: `Base R${props.selectedRound}`, subtitle: `${selectedRoundBaseCount.value} acts`, x: 300, y: 180, width: 148, height: 52, kind: 'hub base-hub', agentKey: '' },
    { id: 'actor', title: actorName.value, subtitle: `${selectedRoundActorActions.value.length} direct acts`, x: 500, y: 120, width: 180, height: 58, kind: 'actor', agentKey: actorName.value },
    { id: 'branch-hub', title: `Branch R${props.selectedRound}`, subtitle: `${selectedRoundBranchCount.value} acts`, x: 700, y: 180, width: 152, height: 52, kind: 'hub branch-hub', agentKey: '' },
    ...baseNodes,
    ...branchNodes
  ]
  return nodes
})

const graphEdges = computed(() => {
  const nodeMap = new Map(graphNodes.value.map(node => [node.id, node]))
  const edges = []

  baseRoundLeaders.value.forEach((agent, index) => {
    const source = nodeMap.get(`base-${index}`)
    const target = nodeMap.get('base-hub')
    if (!source || !target) return
    edges.push(makeEdge(`base-${agent.agent_name}`, source, target, agent.total_actions, 'base', `${agent.total_actions}x`))
  })

  const baseHub = nodeMap.get('base-hub')
  const actorNode = nodeMap.get('actor')
  const branchHub = nodeMap.get('branch-hub')
  if (baseHub && actorNode) {
    edges.push(makeEdge('base-pivot', baseHub, actorNode, Math.max(1, selectedRoundBaseCount.value), 'pivot', 'fork'))
  }
  if (actorNode && branchHub) {
    edges.push(makeEdge('actor-branch', actorNode, branchHub, Math.max(1, selectedRoundActorActions.value.length || selectedRoundAmplifiers.value.length), 'actor', `${selectedRoundAmplifiers.value.length}x`))
  }

  mergeBranchNodes(branchRoundLeaders.value, amplifierLeaders.value).forEach((agent, index) => {
    const source = nodeMap.get('branch-hub')
    const target = nodeMap.get(`branch-${index}`)
    if (!source || !target) return
    edges.push(makeEdge(
      `branch-${agent.agent_name}`,
      source,
      target,
      agent.total_actions,
      agent.isAmplifier ? 'amplifier' : 'branch',
      agent.isAmplifier ? `${agent.total_actions}x amp` : `${agent.total_actions}x`
    ))
  })

  return edges
})

const feedModes = computed(() => {
  const modes = [
    { id: 'all', label: 'All' },
    { id: 'actor', label: actorName.value },
    { id: 'amplifiers', label: 'Amplifiers' }
  ]
  if (focusedAgent.value) {
    modes.push({ id: 'focused', label: focusedAgent.value })
  }
  return modes
})

const filteredBranchActions = computed(() => filterActions(props.branchRoundActions, feedMode.value, focusedAgent.value, actorName.value, actorId.value))
const filteredBaseActions = computed(() => filterActions(props.baseRoundActions, feedMode.value, focusedAgent.value, actorName.value, null))

function emitRound(value) {
  emit('update:selectedRound', Number(value))
}

function compactId(value) {
  return String(value || 'sim_unknown').replace('sim_', 'SIM_').toUpperCase()
}

function signed(value) {
  if (value > 0) return `+${value}`
  return `${value}`
}

function barStyle(value) {
  const max = Math.max(...compareRounds.value.map(item => Math.max(item.base, item.branch)), 1)
  return { height: `${Math.max(8, (value / max) * 100)}%` }
}

function blipStyle(value) {
  const max = Math.max(...compareRounds.value.map(item => item.actor), 1)
  return { bottom: `${Math.min(92, Math.max(12, (value / max) * 100))}%` }
}

function actionText(action) {
  const args = action.action_args || {}
  return args.content || args.quote_content || args.original_content || args.post_content || args.comment_content || 'No captured body.'
}

function contextLabel(action) {
  const names = referencedNames(action)
  if (names.length > 0) return names.join(' · ')
  const args = action.action_args || {}
  if (args.query) return `query:${args.query}`
  return action.platform || 'stream'
}

function formatTime(timestamp) {
  if (!timestamp) return 'n/a'
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  } catch {
    return timestamp
  }
}

function actionTypeLabel(type) {
  const labels = {
    CREATE_POST: 'POST',
    QUOTE_POST: 'QUOTE',
    REPOST: 'REPOST',
    CREATE_COMMENT: 'COMMENT',
    LIKE_POST: 'LIKE',
    LIKE_COMMENT: 'LIKE',
    DISLIKE_POST: 'DISLIKE',
    DISLIKE_COMMENT: 'DISLIKE',
    SEARCH_POSTS: 'SEARCH',
    SEARCH_USER: 'SEARCH',
    DO_NOTHING: 'IDLE'
  }
  return labels[type] || type || 'ACTION'
}

function referencedNames(action) {
  const args = action.action_args || {}
  return [args.original_author_name, args.post_author_name, args.comment_author_name, args.author_name]
    .map(value => String(value || '').trim())
    .filter(Boolean)
}

function groupAgents(actions) {
  const buckets = new Map()
  actions.forEach(action => {
    const key = action.agent_name || `Agent ${action.agent_id}`
    if (!buckets.has(key)) {
      buckets.set(key, { agent_name: key, total_actions: 0 })
    }
    buckets.get(key).total_actions += 1
  })
  return [...buckets.values()].sort((left, right) => right.total_actions - left.total_actions)
}

function mergeBranchNodes(branchLeaders, amplifiers) {
  const merged = new Map()
  amplifiers.forEach(agent => {
    merged.set(agent.agent_name, { ...agent, isAmplifier: true })
  })
  branchLeaders.forEach(agent => {
    if (!merged.has(agent.agent_name)) {
      merged.set(agent.agent_name, { ...agent, isAmplifier: false })
    }
  })
  return [...merged.values()].slice(0, 5)
}

function layoutSideNodes(items, x, kind) {
  if (items.length === 0) return []
  const gap = items.length === 1 ? 0 : 190 / Math.max(items.length - 1, 1)
  return items.map((item, index) => ({
    id: `${kind.startsWith('base') ? 'base' : 'branch'}-${index}`,
    title: truncate(item.agent_name, 22),
    subtitle: item.isAmplifier ? `${item.total_actions} amplifier` : `${item.total_actions} actions`,
    x,
    y: 85 + (gap * index),
    width: 148,
    height: 48,
    kind: item.isAmplifier ? 'amplifier-node' : kind,
    agentKey: item.agent_name
  }))
}

function truncate(value, length) {
  if (value.length <= length) return value
  return `${value.slice(0, length - 1)}…`
}

function makeEdge(id, source, target, weight, kind, label) {
  const opacity = Math.min(0.95, 0.3 + (weight / Math.max(selectedRoundBranchCount.value, selectedRoundBaseCount.value, 1)))
  const width = Math.min(4.8, 1.2 + weight * 0.24)
  return {
    id,
    x1: source.x + (source.x < target.x ? source.width / 2 - 6 : -source.width / 2 + 6),
    y1: source.y,
    x2: target.x + (target.x > source.x ? -target.width / 2 + 6 : target.width / 2 - 6),
    y2: target.y,
    labelX: (source.x + target.x) / 2,
    labelY: ((source.y + target.y) / 2) - 8,
    kind,
    label,
    opacity,
    width
  }
}

function handleNodeClick(node) {
  if (!node.agentKey) {
    focusedAgent.value = ''
    feedMode.value = 'all'
    return
  }
  focusedAgent.value = node.agentKey
  feedMode.value = node.agentKey === actorName.value ? 'actor' : 'focused'
}

function filterActions(actions, mode, agentName, injectedActorName, injectedActorId) {
  if (mode === 'actor') {
    return actions.filter(action => {
      if (injectedActorId !== null && injectedActorId !== undefined) {
        return action.agent_id === injectedActorId
      }
      return (action.agent_name || '') === injectedActorName
    })
  }

  if (mode === 'amplifiers') {
    return actions.filter(action => referencedNames(action).includes(injectedActorName) && (action.agent_name || '') !== injectedActorName)
  }

  if (mode === 'focused' && agentName) {
    return actions.filter(action => (action.agent_name || '') === agentName || referencedNames(action).includes(agentName))
  }

  return actions
}
</script>

<style scoped>
.forensics-panel {
  height: 100%;
  overflow-y: auto;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background:
    radial-gradient(circle at top right, rgba(255, 211, 106, 0.07), transparent 28%),
    linear-gradient(180deg, rgba(8, 12, 10, 0.98), rgba(6, 9, 8, 0.98));
  color: #dbffed;
}

.panel-block {
  border: 1px solid rgba(122, 240, 181, 0.12);
  background:
    linear-gradient(180deg, rgba(13, 20, 17, 0.92), rgba(8, 11, 10, 0.96)),
    repeating-linear-gradient(0deg, rgba(122, 240, 181, 0.03), rgba(122, 240, 181, 0.03) 1px, transparent 1px, transparent 22px);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.24);
  padding: 18px;
}

.block-head,
.hero-head,
.metric-grid,
.round-meta,
.feed-column-head,
.action-top,
.tag-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero-head,
.feed-head,
.graph-head {
  align-items: flex-start;
}

.block-kicker,
.tag,
.metric-label,
.metric-copy,
.round-chip,
.round-labels,
.compare-label,
.round-summary-label,
.action-context,
.action-time,
.feed-column-head,
.signal-pill,
.filter-chip {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.block-kicker,
.metric-label,
.metric-copy,
.round-chip,
.round-labels,
.compare-label,
.round-summary-label,
.action-context,
.action-time,
.feed-column-head {
  font-size: 10px;
  color: rgba(219, 255, 237, 0.58);
}

.block-title,
.section-title {
  margin: 0;
  color: #f1fff8;
  line-height: 1.05;
}

.block-title {
  margin-top: 10px;
  font-size: 28px;
}

.section-title {
  margin-top: 8px;
  font-size: 20px;
}

.block-copy {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(219, 255, 237, 0.72);
  max-width: 60ch;
}

.hero-note {
  margin: 12px 0 0;
  padding-left: 12px;
  border-left: 1px solid rgba(255, 211, 106, 0.22);
  color: rgba(219, 255, 237, 0.54);
  font-size: 12px;
  line-height: 1.6;
  max-width: 62ch;
}

.lab-btn {
  border: 1px solid rgba(255, 211, 106, 0.22);
  background: linear-gradient(90deg, rgba(255, 211, 106, 0.12), rgba(122, 240, 181, 0.08));
  color: #f3fffa;
  padding: 12px 14px;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  cursor: pointer;
}

.tag-row {
  margin-top: 16px;
  justify-content: flex-start;
  flex-wrap: wrap;
}

.tag {
  display: inline-flex;
  align-items: center;
  padding: 7px 10px;
  border: 1px solid rgba(122, 240, 181, 0.16);
  color: rgba(219, 255, 237, 0.72);
  background: rgba(255, 255, 255, 0.03);
  font-size: 10px;
}

.tag.active {
  border-color: rgba(122, 240, 181, 0.28);
  color: #4de2a5;
}

.tag.actor {
  border-color: rgba(255, 211, 106, 0.22);
  color: #ffd36a;
}

.metric-grid {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.round-summary-card {
  padding: 14px;
  border: 1px solid rgba(122, 240, 181, 0.12);
  background: rgba(255, 255, 255, 0.03);
}

.metric-card.emphasis {
  border-color: rgba(255, 211, 106, 0.22);
}

.metric-value,
.round-summary-value {
  display: block;
  margin-top: 8px;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 28px;
  color: #effff7;
}

.metric-copy {
  display: block;
  margin-top: 8px;
}

.metric-value.positive,
.round-summary-value.positive {
  color: #4de2a5;
}

.metric-value.negative,
.round-summary-value.negative {
  color: #ff8b8b;
}

.round-slider {
  width: 100%;
  margin-top: 16px;
  accent-color: #ffd36a;
}

.round-labels {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
}

.round-meta {
  flex-wrap: wrap;
}

.round-chip {
  padding: 5px 8px;
  border: 1px solid rgba(122, 240, 181, 0.12);
}

.compare-strip {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(18px, 1fr));
  gap: 7px;
  align-items: end;
}

.compare-cell {
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
}

.compare-bars {
  position: relative;
  height: 74px;
  display: flex;
  gap: 3px;
  align-items: end;
  justify-content: center;
  border: 1px solid rgba(122, 240, 181, 0.04);
  background: rgba(255, 255, 255, 0.02);
}

.compare-bar {
  width: 5px;
  min-height: 8px;
  display: block;
  opacity: 0.88;
}

.compare-bar.base {
  background: rgba(162, 174, 168, 0.72);
}

.compare-bar.branch {
  background: linear-gradient(180deg, #ffd36a, #4de2a5);
}

.actor-blip {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: 8px;
  height: 8px;
  background: #ffd36a;
  border-radius: 999px;
  box-shadow: 0 0 10px rgba(255, 211, 106, 0.38);
}

.compare-label {
  display: block;
  margin-top: 6px;
  text-align: center;
}

.compare-cell.active .compare-bars,
.compare-cell:hover .compare-bars {
  border-color: rgba(122, 240, 181, 0.24);
  transform: translateY(-2px);
}

.compare-cell.injected .compare-bars {
  box-shadow: inset 0 0 0 1px rgba(255, 211, 106, 0.24);
}

.round-summary-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.signal-row,
.filter-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.signal-row {
  margin-top: 14px;
}

.signal-pill,
.filter-chip {
  padding: 7px 10px;
  border: 1px solid rgba(122, 240, 181, 0.12);
  background: rgba(255, 255, 255, 0.03);
  color: rgba(219, 255, 237, 0.72);
  font-size: 10px;
}

.signal-pill {
  cursor: default;
}

.signal-pill.muted {
  cursor: default;
  opacity: 0.64;
}

.filter-chip.active {
  border-color: rgba(255, 211, 106, 0.26);
  color: #ffd36a;
}

.graph-stage {
  margin-top: 16px;
  border: 1px solid rgba(122, 240, 181, 0.08);
  background:
    radial-gradient(circle at top, rgba(77, 226, 165, 0.05), transparent 42%),
    rgba(5, 9, 8, 0.82);
  overflow: hidden;
}

.graph-svg {
  width: 100%;
  height: auto;
  display: block;
}

.stage-grid line {
  stroke: rgba(122, 240, 181, 0.07);
  stroke-width: 1;
}

.stage-path {
  fill: none;
  stroke: url(#branchPath);
  stroke-width: 3;
  stroke-dasharray: 8 8;
}

.stage-annotation,
.stage-caption,
.edge-badge,
.node-subtitle {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  letter-spacing: 0.12em;
}

.stage-annotation,
.stage-caption,
.edge-badge,
.node-subtitle {
  fill: rgba(219, 255, 237, 0.6);
  font-size: 10px;
  text-transform: uppercase;
}

.stage-annotation,
.stage-caption,
.edge-badge,
.node-title {
  text-anchor: middle;
}

.edge-line {
  stroke-width: var(--edge-width);
  stroke-opacity: var(--edge-opacity);
}

.edge-line.base {
  stroke: rgba(162, 174, 168, 0.9);
}

.edge-line.pivot {
  stroke: rgba(255, 211, 106, 0.7);
  stroke-dasharray: 5 4;
}

.edge-line.actor {
  stroke: rgba(255, 211, 106, 0.92);
}

.edge-line.branch {
  stroke: rgba(77, 226, 165, 0.78);
}

.edge-line.amplifier {
  stroke: rgba(77, 226, 165, 0.96);
}

.node-layer {
  cursor: pointer;
}

.node-shell {
  fill: rgba(8, 14, 12, 0.96);
  stroke: rgba(122, 240, 181, 0.14);
  stroke-width: 1.2;
}

.node-shell.base-agent,
.node-shell.base-hub {
  stroke: rgba(162, 174, 168, 0.24);
}

.node-shell.actor {
  stroke: rgba(255, 211, 106, 0.34);
  fill: rgba(28, 24, 12, 0.96);
}

.node-shell.branch-hub,
.node-shell.branch-agent,
.node-shell.amplifier-node {
  stroke: rgba(77, 226, 165, 0.22);
}

.node-shell.amplifier-node {
  fill: rgba(9, 18, 14, 0.98);
}

.node-shell.active {
  stroke-width: 2;
  filter: drop-shadow(0 0 12px rgba(255, 211, 106, 0.22));
}

.node-title {
  fill: #f3fff9;
  font-size: 12px;
  font-weight: 700;
}

.feed-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.feed-column {
  border: 1px solid rgba(122, 240, 181, 0.1);
  background: rgba(255, 255, 255, 0.02);
  min-height: 280px;
  display: flex;
  flex-direction: column;
}

.feed-column.branch {
  box-shadow: inset 0 0 0 1px rgba(77, 226, 165, 0.06);
}

.feed-column.base {
  box-shadow: inset 0 0 0 1px rgba(162, 174, 168, 0.06);
}

.feed-column-head {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(122, 240, 181, 0.08);
}

.action-list {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}

.action-item {
  border: 1px solid rgba(122, 240, 181, 0.08);
  background: rgba(255, 255, 255, 0.03);
  padding: 12px;
}

.action-agent {
  color: #f2fff8;
  font-size: 13px;
  font-weight: 700;
}

.action-context,
.action-time {
  margin-top: 4px;
}

.action-body {
  margin-top: 10px;
  color: rgba(219, 255, 237, 0.8);
  font-size: 13px;
  line-height: 1.55;
}

.empty-state {
  padding: 22px 14px;
  color: rgba(219, 255, 237, 0.56);
  font-size: 12px;
}

@media (max-width: 1280px) {
  .metric-grid,
  .round-summary-grid,
  .feed-grid {
    grid-template-columns: 1fr;
  }
}
</style>
