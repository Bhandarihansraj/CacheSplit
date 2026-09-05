/**
 * CacheSplit v3 — Frontend Runtime
 * All data sourced from real API endpoints.
 * Zero hardcoded / mock values.
 */

// ── API Client ──────────────────────────────────────────────────────────────
const API = {
  get: async (path) => {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
    return r.json();
  },
  post: async (path, body) => {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status} — ${txt}`);
    }
    return r.json();
  },
  put: async (path, body) => {
    const r = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status} — ${txt}`);
    }
    return r.json();
  },
  del: async (path) => {
    const r = await fetch(path, { method: 'DELETE' });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status} — ${txt}`);
    }
    return r.json();
  },
};

// ── Health Status Helpers ─────────────────────────────────────────────────
function healthBadge(raw) {
  if (raw === 'ok')          return '<span class="badge badge-ok">All clear</span>';
  if (raw === 'stale')       return '<span class="badge badge-stale">Needs attention</span>';
  if (raw === 'quarantined') return '<span class="badge badge-quarantine">Paused — critical</span>';
  return '<span class="badge badge-neutral">Unknown</span>';
}
function healthDot(raw) {
  return `<span class="status-dot ${raw}"></span>`;
}
function severityBadge(sev) {
  const s = (sev || '').toUpperCase();
  if (s === 'HIGH' || s === 'CRITICAL') return '<span class="badge badge-quarantine">Critical</span>';
  if (s === 'MEDIUM') return '<span class="badge badge-stale">Medium</span>';
  return '<span class="badge badge-neutral">Low</span>';
}
function relTime(ts) {
  if (!ts) return '—';
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (secs < 60)   return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs/60)}m ago`;
  return `${Math.floor(secs/3600)}h ago`;
}
function timeFmt(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute:'2-digit', second:'2-digit' });
}

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  nodes: [],
  selectedEntityId: null,
  selectedNodeId: null,
  commitLog: [],
  securityFeed: [],
  pollInterval: null,
  stagedMutations: [],
};

// ── Navigation ────────────────────────────────────────────────────────────
function switchPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pg = document.getElementById(pageId);
  if (pg) pg.classList.add('active');
  const nav = document.querySelector(`[data-page="${pageId}"]`);
  if (nav) nav.classList.add('active');
  document.getElementById('page-title').textContent = nav?.dataset.label || '';
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 1 — OPERATIONS (Node Map)
// ─────────────────────────────────────────────────────────────────────────
async function loadNodeMap() {
  const container = document.getElementById('node-grid');
  container.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Loading nodes…</span></div>`;
  try {
    const data = await API.get('/api/dashboard/node-map');
    state.nodes = data.nodes;
    renderNodeMap(data.nodes);
    updateTopbarMetrics(data.nodes);
  } catch (e) {
    container.innerHTML = `<div class="state-msg state-error">Failed to load node map<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderNodeMap(nodes) {
  const container = document.getElementById('node-grid');
  if (!nodes.length) {
    container.innerHTML = `<div class="state-msg">No nodes registered.</div>`;
    return;
  }
  container.innerHTML = nodes.map(n => `
    <div class="node-card ${n.health_raw}" data-node="${n.id}">
      <div class="node-card-body">
        <div class="row-between">
          <div>
            <div class="node-id">${n.region}</div>
            <div class="node-region">${n.tier} tier · ${n.id}</div>
          </div>
          ${healthDot(n.health_raw)}
        </div>
        <div class="node-status-row mt-8">
          ${healthBadge(n.health_raw)}
        </div>
        ${n.agent_flags?.length ? `<div class="node-flags">${n.agent_flags.slice(0,2).join(' · ')}</div>` : ''}
        <div class="node-metric-row">
          <div class="node-metric">
            <div class="label">Entities</div>
            <div class="value">${n.cached_entity_count.toLocaleString()}</div>
          </div>
          <div class="node-metric">
            <div class="label">Heartbeat</div>
            <div class="value">${n.last_heartbeat_secs_ago != null ? `${n.last_heartbeat_secs_ago}s ago` : 'Never'}</div>
          </div>
          <div class="node-metric">
            <div class="label">Version</div>
            <div class="value">${n.version_number}</div>
          </div>
          <div class="node-metric">
            <div class="label">HB Active</div>
            <div class="value">${n.heartbeat_enabled ? '● On' : '○ Off'}</div>
          </div>
        </div>
      </div>
      <div class="node-card-footer">
        <button class="btn btn-ghost btn-sm"
          onclick="confirmAction('Pause heartbeat for ${n.id}?', () => toggleHeartbeat('${n.id}'))">
          ${n.heartbeat_enabled ? 'Pause HB' : 'Resume HB'}
        </button>
        ${n.health_raw !== 'ok' ? `
          <button class="btn btn-ok btn-sm"
            onclick="confirmAction('Recover node ${n.id}?', () => recoverNode('${n.id}'))">
            Recover
          </button>` : ''}
        <button class="btn btn-ghost btn-sm" onclick="openEditModal('${n.id}')">Edit</button>
        <button class="btn btn-ghost btn-sm" style="color:var(--danger)"
          onclick="confirmAction('Delete node ${n.id}? This cannot be undone.', () => deleteNode('${n.id}'))">
          Remove
        </button>
        <button class="btn btn-ghost btn-sm" onclick="openEntityExplorer('${n.id}')">
          Explore →
        </button>
      </div>
    </div>
  `).join('');
}

function updateTopbarMetrics(nodes) {
  const healthy = nodes.filter(n => n.health_raw === 'ok').length;
  const total = nodes.length;
  const entities = nodes.reduce((a, n) => a + n.cached_entity_count, 0);
  document.getElementById('metric-nodes').textContent = `${healthy}/${total}`;
  document.getElementById('metric-entities').textContent = entities.toLocaleString();
  document.getElementById('metric-time').textContent = new Date().toLocaleTimeString();
}

async function toggleHeartbeat(nodeId) {
  try {
    const data = await API.post(`/api/dashboard/node/${nodeId}/toggle-heartbeat`, {});
    await loadNodeMap();
  } catch (e) {
    alert(`Toggle failed: ${e.message}`);
  }
}

async function recoverNode(nodeId) {
  try {
    await API.post(`/api/dashboard/node/${nodeId}/recover`, {});
    await loadNodeMap();
  } catch (e) {
    alert(`Recovery failed: ${e.message}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 2 — ENTITY EXPLORER
// ─────────────────────────────────────────────────────────────────────────
function openEntityExplorer(nodeId) {
  state.selectedNodeId = nodeId;
  switchPage('page-entities');
  loadEntities(nodeId);
}

async function loadEntities(nodeId) {
  const listEl = document.getElementById('entity-list');
  const treeEl = document.getElementById('dag-tree-panel');
  listEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Loading entities…</span></div>`;
  treeEl.innerHTML = `<div class="state-msg text-muted text-sm">Select a patient to view their ER tree.</div>`;
  try {
    const data = await API.get(`/api/dashboard/node/${nodeId}/entities?limit=50`);
    renderEntityList(data.entities, data.total_cached);
  } catch (e) {
    listEl.innerHTML = `<div class="state-msg state-error">Failed<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderEntityList(entities, total) {
  const listEl = document.getElementById('entity-list');
  const headerEl = document.getElementById('entity-list-header');
  headerEl.textContent = `${entities.length} shown / ${total} total`;
  if (!entities.length) {
    listEl.innerHTML = `<div class="state-msg">No entities in this node.</div>`;
    return;
  }
  listEl.innerHTML = entities.map(e => `
    <div class="feed-item" style="cursor:pointer" onclick="loadMerkleTree('${e.entity_id}')">
      <div class="feed-dot" style="background:${e.entity_type==='patient'?'var(--accent-3)':'var(--text-3)'}"></div>
      <div class="feed-body">
        <div class="feed-title">${e.entity_id}</div>
        <div class="feed-meta">
          ${e.entity_type} · ${e.region} · ${e.children_count} child entities
        </div>
        ${e.data?.condition ? `<div class="feed-meta">${e.data.condition}</div>` : ''}
      </div>
      <div class="feed-badge">
        <span class="badge badge-neutral">${e.entity_type}</span>
      </div>
    </div>
  `).join('');
}

async function loadMerkleTree(entityId) {
  state.selectedEntityId = entityId;
  const treeEl = document.getElementById('dag-tree-panel');
  treeEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Loading Merkle DAG…</span></div>`;
  try {
    const data = await API.get(`/api/dashboard/entity/${entityId}/merkle-tree`);
    renderMerkleTree(data.merkle_tree, treeEl);
  } catch (e) {
    treeEl.innerHTML = `<div class="state-msg state-error">Not found<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderMerkleTree(node, container, isRoot = true) {
  if (!node) return;
  const shortHash = (node.merkle_root_hash || node.local_hash || '').slice(0, 20);
  const el = document.createElement('div');
  el.className = `dag-node ${isRoot ? 'root' : ''}`;
  el.innerHTML = `
    <div class="dag-node-header">
      <span class="dag-node-id">${node.entity_id}</span>
      <span class="dag-node-type">${node.entity_type}</span>
    </div>
    <div class="dag-node-hash">⬡ ${shortHash}… | <b>v${node.version || 1}</b></div>
    ${node.data ? `<div class="dag-node-data">${JSON.stringify(node.data).slice(0,80)}…</div>` : ''}
  `;
  if (isRoot) { container.innerHTML = ''; container.className = 'dag-tree scroll-panel'; }
  container.appendChild(el);
  if (node.children?.length) {
    const childWrap = document.createElement('div');
    childWrap.className = 'dag-children';
    node.children.forEach(c => renderMerkleTree(c, childWrap, false));
    container.appendChild(childWrap);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 3 — COMMIT LAB (Compound Commit + Recent Log)
// ─────────────────────────────────────────────────────────────────────────
async function loadCommitLog() {
  const logEl = document.getElementById('commit-log');
  logEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Loading commits…</span></div>`;
  try {
    const data = await API.get('/api/dashboard/commits/recent?limit=20');
    renderCommitLog(data.commits);
  } catch (e) {
    logEl.innerHTML = `<div class="state-msg state-error">Failed to load commits<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderCommitLog(commits) {
  const logEl = document.getElementById('commit-log');
  if (!commits.length) {
    logEl.innerHTML = `<div class="state-msg text-muted">No commits yet.</div>`;
    return;
  }
  logEl.innerHTML = commits.map(c => `
    <div class="commit-node">
      <div class="commit-node-dot"></div>
      <div class="commit-node-body">
        <div class="feed-title font-mono text-xs">${c.transaction_id}</div>
        <div class="feed-meta">
          ${c.entity_ids?.length || 0} entities · hash: ${(c.commit_hash||'').slice(0,16)}… · ${timeFmt(c.created_at)}
        </div>
      </div>
      <div class="feed-badge"><span class="badge badge-ok">Committed</span></div>
    </div>
  `).join('');
}

async function fetchBaseJson() {
  const entityId = document.getElementById('commit-entity-id').value.trim();
  const resultEl = document.getElementById('commit-result');
  if (!entityId) {
    resultEl.innerHTML = `<div class="result-err">Entity ID required to fetch current state.</div>`;
    return;
  }
  try {
    const data = await API.get(`/api/dashboard/entity/${entityId}/merkle-tree`);
    if (data && data.merkle_tree) {
      document.getElementById('commit-entity-type').value = data.merkle_tree.entity_type || '';
      document.getElementById('commit-data-json').value = JSON.stringify(data.merkle_tree.data || {}, null, 2);
      document.getElementById('commit-expected-version').value = data.merkle_tree.version || '';
      resultEl.innerHTML = `<div class="result-ok">Fetched current state for ${entityId}</div>`;
    }
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">Failed to fetch base JSON: ${e.message}</div>`;
  }
}

function setStagingMode(mode) {
  document.getElementById('btn-mode-edit').classList.toggle('active', mode === 'edit');
  document.getElementById('btn-mode-diff').classList.toggle('active', mode === 'diff');
  document.getElementById('staging-edit-mode').style.display = mode === 'edit' ? 'block' : 'none';
  document.getElementById('staging-diff-mode').style.display = mode === 'diff' ? 'block' : 'none';
  if (mode === 'diff') {
    renderDiff();
  }
}

function stageMutation() {
  const resultEl = document.getElementById('commit-result');
  const entityId  = document.getElementById('commit-entity-id').value.trim();
  const entityType= document.getElementById('commit-entity-type').value.trim();
  const dataRaw   = document.getElementById('commit-data-json').value.trim();
  const expVerStr = document.getElementById('commit-expected-version').value.trim();

  if (!entityId || !entityType || !dataRaw) {
    resultEl.innerHTML = `<div class="result-err">Entity ID, Type, and Data fields are required.</div>`;
    return;
  }
  let dataObj;
  try { dataObj = JSON.parse(dataRaw); }
  catch { resultEl.innerHTML = `<div class="result-err">Invalid JSON in data field.</div>`; return; }

  let mutationPayload = { entity_id: entityId, entity_type: entityType, data: dataObj };
  if (expVerStr) mutationPayload.expected_version = parseInt(expVerStr, 10);

  state.stagedMutations.push(mutationPayload);
  updateStagedCount();
  resultEl.innerHTML = `<div class="result-ok">Staged mutation for ${entityId}</div>`;
  
  // Clear form
  document.getElementById('commit-entity-id').value = '';
  document.getElementById('commit-entity-type').value = '';
  document.getElementById('commit-data-json').value = '';
  document.getElementById('commit-expected-version').value = '';
}

function updateStagedCount() {
  const count = state.stagedMutations.length;
  document.getElementById('staged-count').textContent = count;
  document.getElementById('btn-commit-staged').disabled = count === 0;
}

function clearStaged() {
  state.stagedMutations = [];
  updateStagedCount();
  document.getElementById('commit-result').innerHTML = '';
  renderDiff();
}

function renderDiff() {
  const diffView = document.getElementById('diff-view');
  if (state.stagedMutations.length === 0) {
    diffView.innerHTML = `<div class="state-msg text-muted">No pending mutations staged.</div>`;
    return;
  }
  
  let html = '';
  for (const m of state.stagedMutations) {
    html += `<div class="diff-section">
      <div class="diff-header">${m.entity_id} (${m.entity_type}) ${m.expected_version ? `[v${m.expected_version}]` : ''}</div>
      <div class="diff-add">+ ${JSON.stringify(m.data)}</div>
    </div>`;
  }
  diffView.innerHTML = html;
}

async function submitStagedCommit() {
  const resultEl = document.getElementById('commit-result');
  if (state.stagedMutations.length === 0) {
    resultEl.innerHTML = `<div class="result-err">No mutations staged.</div>`;
    return;
  }

  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Committing…</span></div>`;
  try {
    const txId = `tx-${Date.now()}`;
    const data = await API.post('/api/dashboard/compound-commit', {
      transaction_id: txId,
      mutations: state.stagedMutations,
      edges: [],
    });
    resultEl.innerHTML = `
      <div class="result-ok">
        <strong>Committed</strong> — tx: ${data.result?.transaction_id}<br>
        <span class="result-mono">Hash: ${data.result?.commit_hash}</span>
      </div>`;
    clearStaged();
    await loadCommitLog();
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">${e.message}</div>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 4 — MULTI-MASTER QUERY
// ─────────────────────────────────────────────────────────────────────────
async function runQuery() {
  const resultEl = document.getElementById('query-result');
  const scope  = document.getElementById('query-scope').value.trim();
  const target = document.getElementById('query-target').value.trim();
  const qtype  = document.getElementById('query-type').value;

  if (!target) {
    resultEl.innerHTML = `<div class="result-err">Target is required (e.g. all_masters).</div>`;
    return;
  }
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Querying ${target}…</span></div>`;
  try {
    const data = await API.post('/api/query', {
      requester_scope: scope || 'patient_summary',
      target,
      query_type: qtype,
    });
    renderQueryResults(data, resultEl);
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">Query failed<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderQueryResults(data, container) {
  const results = data.results || {};
  const keys = Object.keys(results);
  if (!keys.length) {
    container.innerHTML = `<div class="state-msg text-muted">No nodes matched target "${data.target}".</div>`;
    return;
  }
  container.innerHTML = `<div class="feed">` + keys.map(nodeId => {
    const r = results[nodeId];
    if (r.error) {
      return `
        <div class="feed-item">
          <div class="feed-dot" style="background:var(--danger)"></div>
          <div class="feed-body">
            <div class="feed-title">${nodeId}</div>
            <div class="feed-meta">${r.error}</div>
          </div>
        </div>`;
    }
    let body = `
      <div class="feed-title">${nodeId} · ${r.region} · ${r.tier} tier</div>
      <div class="feed-meta">${healthBadge(r.health)}</div>`;

    if (data.query_type === 'status') {
      body += `
        <div class="feed-meta">Version ${r.version_number} · hash ${(r.current_commit_hash||'').slice(0,16)}…</div>`;
    } else if (data.query_type === 'cache_contents') {
      body += `
        <div class="feed-meta">${(r.cached_entity_count ?? 0).toLocaleString()} cached entities · ${r.partitions?.length || 0} partition root(s)</div>`;
      if (r.sample_entities?.length) {
        body += `<div class="feed-meta font-mono text-xs">` +
          r.sample_entities.map(e =>
            `${e.entity_id} (${e.entity_type}) · ${(e.merkle_root_hash||'').slice(0,16)}…`
          ).join('<br>') + `</div>`;
      }
    } else if (data.query_type === 'commit_history') {
      const hist = r.commit_history || [];
      body += hist.length
        ? `<div class="feed-meta font-mono text-xs">` + hist.map(c =>
            `${(c.commit_hash||'').slice(0,12)}… · ${c.transaction_id} · ${timeFmt(c.created_at)}`
          ).join('<br>') + `</div>`
        : `<div class="feed-meta text-muted">No commits recorded for this node yet.</div>`;
    }
    return `<div class="feed-item"><div class="feed-dot" style="background:var(--accent-2)"></div><div class="feed-body">${body}</div></div>`;
  }).join('') + `</div>`;
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 4 — ACCESS CONTROL (ReBAC)
// ─────────────────────────────────────────────────────────────────────────
async function testReBAC() {
  const resultEl = document.getElementById('rebac-result');
  const clinician = document.getElementById('rebac-clinician').value.trim();
  const target = document.getElementById('rebac-target').value.trim();
  if (!clinician || !target) {
    resultEl.innerHTML = `<div class="result-err">Both fields required.</div>`;
    return;
  }
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Checking authorization…</span></div>`;
  try {
    const data = await API.post('/api/dashboard/rebac/test', {
      clinician_id: clinician, target_entity_id: target,
    });
    if (data.authorized) {
      resultEl.innerHTML = `
        <div class="result-ok">
          <strong>Access granted</strong><br>
          <span class="result-mono">${JSON.stringify(data, null, 2)}</span>
        </div>`;
    } else {
      resultEl.innerHTML = `
        <div class="result-err">
          <strong>Access denied</strong><br>
          ${data.reason || 'No authorization path found.'}
        </div>`;
    }
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">${e.message}</div>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 5 — SECURITY
// ─────────────────────────────────────────────────────────────────────────
async function loadSecurityFeed() {
  const feedEl = document.getElementById('security-feed');
  feedEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Loading security events…</span></div>`;
  try {
    const data = await API.get('/api/dashboard/security-feed?limit=20');
    state.securityFeed = data.alerts;
    renderSecurityFeed(data.alerts);
  } catch (e) {
    feedEl.innerHTML = `<div class="state-msg state-error">Failed<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderSecurityFeed(alerts) {
  const feedEl = document.getElementById('security-feed');
  if (!alerts.length) {
    feedEl.innerHTML = `<div class="state-msg">No security events recorded. System is clean.</div>`;
    return;
  }
  feedEl.innerHTML = `<div class="feed">` + alerts.map(a => `
    <div class="feed-item">
      <div class="feed-dot" style="background:${
        (a.severity||'').toUpperCase() === 'CRITICAL' || (a.severity||'').toUpperCase() === 'HIGH'
          ? 'var(--danger)' : 'var(--stale)'}"></div>
      <div class="feed-body">
        <div class="feed-title">${a.description}</div>
        <div class="feed-meta">
          ${a.node_id} · ${a.event_type || ''} · ${timeFmt(a.created_at)}
        </div>
        ${a.target_entity_id ? `<div class="feed-meta">Target: ${a.target_entity_id}</div>` : ''}
      </div>
      <div class="feed-badge">${severityBadge(a.severity)}</div>
    </div>
  `).join('') + `</div>`;
}

async function injectAnomaly() {
  const resultEl = document.getElementById('anomaly-result');
  const nodeId   = document.getElementById('anomaly-node').value.trim();
  const region   = document.getElementById('anomaly-region').value.trim();
  const entityId = document.getElementById('anomaly-entity').value.trim();
  if (!nodeId || !region || !entityId) {
    resultEl.innerHTML = `<div class="result-err">All fields required.</div>`;
    return;
  }
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Evaluating traversal…</span></div>`;
  try {
    const data = await API.post('/api/dashboard/security/test-anomaly', {
      requesting_node_id: nodeId,
      requester_region: region,
      target_entity_id: entityId,
    });
    const cls = data.flagged ? 'result-err' : 'result-ok';
    resultEl.innerHTML = `
      <div class="${cls}">
        <strong>${data.flagged ? '⚠ Anomaly Detected' : '✓ No anomaly detected'}</strong>
        ${data.reason ? `<br>${data.reason}` : ''}
        <pre class="result-mono mt-8">${JSON.stringify(data, null, 2)}</pre>
      </div>`;
    if (data.flagged) await loadSecurityFeed();
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">${e.message}</div>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 6 — SCANNER
// ─────────────────────────────────────────────────────────────────────────
async function runScanner() {
  const resultEl = document.getElementById('scan-result');
  const entityId = document.getElementById('scan-entity-id').value.trim();
  if (!entityId) {
    resultEl.innerHTML = `<div class="result-err">Entity ID required.</div>`;
    return;
  }
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Scanning nodes…</span></div>`;
  try {
    const data = await API.get(`/api/scan/${entityId}`);
    renderScannerResults(data, resultEl);
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">Scan failed<br><span class="text-xs">${e.message}</span></div>`;
  }
}

function renderScannerResults(data, container) {
  const matrix = data.matrix || {};
  const nodes = Object.keys(matrix);
  if (!nodes.length) {
    container.innerHTML = `<div class="state-msg text-muted">No nodes available.</div>`;
    return;
  }
  let html = `<div class="feed">`;
  nodes.forEach(nodeId => {
    const res = matrix[nodeId];
    let badge = '';
    let dotColor = 'var(--text-3)';
    
    if (res.status === 'primary') {
      badge = '<span class="badge badge-ok">Primary</span>';
      dotColor = 'var(--accent-2)';
    } else if (res.status === 'replica') {
      badge = '<span class="badge badge-neutral">Replica</span>';
      dotColor = 'var(--accent-1)';
    } else if (res.status === 'missing') {
      badge = '<span class="badge badge-stale">Missing</span>';
      dotColor = 'var(--stale)';
    } else {
      badge = `<span class="badge badge-quarantine">${res.status}</span>`;
      dotColor = 'var(--danger)';
    }

    html += `
      <div class="feed-item">
        <div class="feed-dot" style="background:${dotColor}"></div>
        <div class="feed-body">
          <div class="feed-title">${nodeId}</div>
          <div class="feed-meta">Version: ${res.version || '—'} · Hash: ${res.hash ? res.hash.slice(0,16)+'…' : '—'}</div>
        </div>
        <div class="feed-badge">${badge}</div>
      </div>
    `;
  });
  html += `</div>`;
  container.innerHTML = html;
}

// ─────────────────────────────────────────────────────────────────────────
// Confirm Dialog
// ─────────────────────────────────────────────────────────────────────────
function confirmAction(message, onConfirm) {
  if (window.confirm(message)) onConfirm();
}

// ─────────────────────────────────────────────────────────────────────────
// DEVELOPER PORTAL
// ─────────────────────────────────────────────────────────────────────────
async function generateApiKey() {
  const resultEl = document.getElementById('dev-api-key-result');
  resultEl.style.display = 'block';
  resultEl.innerHTML = `<div class="spinner"></div> Generating…`;
  try {
    const data = await API.post('/api/dev/keys', {});
    resultEl.innerHTML = `<strong>API Key:</strong><br><span style="color:var(--accent-2)">${data.api_key}</span><br><br><span class="text-xs text-muted">Copy this key, it will not be shown again.</span>`;
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--danger)">Failed to generate key: ${e.message}</span>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// NODE CRUD
// ─────────────────────────────────────────────────────────────────────────
function toggleAddNodePanel() {
  const panel = document.getElementById('add-node-panel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  document.getElementById('add-node-result').innerHTML = '';
}

function toggleBatchNodePanel() {
  const panel = document.getElementById('batch-node-panel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  document.getElementById('batch-node-result').innerHTML = '';
}

async function createNode() {
  const resultEl = document.getElementById('add-node-result');
  const nodeId = document.getElementById('new-node-id').value.trim();
  const region = document.getElementById('new-node-region').value.trim();
  const tier = document.getElementById('new-node-tier').value;
  if (!nodeId || !region) {
    resultEl.innerHTML = `<div class="result-err">Node ID and Region are required.</div>`;
    return;
  }
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Creating…</span></div>`;
  try {
    await API.post('/api/dashboard/nodes', { node_id: nodeId, region, tier });
    resultEl.innerHTML = `<div class="result-ok">Node <strong>${nodeId}</strong> created.</div>`;
    document.getElementById('new-node-id').value = '';
    document.getElementById('new-node-region').value = '';
    await loadNodeMap();
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">${e.message}</div>`;
  }
}

async function batchCreateNodes() {
  const resultEl = document.getElementById('batch-node-result');
  const raw = document.getElementById('batch-nodes-input').value.trim();
  if (!raw) {
    resultEl.innerHTML = `<div class="result-err">Enter at least one node line.</div>`;
    return;
  }
  const lines = raw.split('\n').map(l => l.trim()).filter(Boolean);
  const nodes = lines.map(line => {
    const [id, region, tier] = line.split(',').map(s => s.trim());
    return { node_id: id, region: region || 'Unknown', tier: tier || 'main' };
  });
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Creating ${nodes.length} nodes…</span></div>`;
  try {
    const data = await API.post('/api/dashboard/nodes/batch', { nodes });
    resultEl.innerHTML = `<div class="result-ok">
      Created <strong>${data.created}</strong> node(s).
      ${data.skipped ? `Skipped ${data.skipped} (already exist).` : ''}
    </div>`;
    document.getElementById('batch-nodes-input').value = '';
    await loadNodeMap();
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">${e.message}</div>`;
  }
}

function openEditModal(nodeId) {
  const node = state.nodes.find(n => n.id === nodeId);
  if (!node) return;
  document.getElementById('edit-node-id').value = nodeId;
  document.getElementById('edit-node-region').value = node.region;
  document.getElementById('edit-node-tier').value = node.tier;
  document.getElementById('edit-node-health').value = node.health_raw;
  document.getElementById('edit-node-result').innerHTML = '';
  document.getElementById('edit-node-modal').style.display = 'flex';
}

function closeEditModal() {
  document.getElementById('edit-node-modal').style.display = 'none';
}

async function saveNodeEdit() {
  const resultEl = document.getElementById('edit-node-result');
  const nodeId = document.getElementById('edit-node-id').value;
  const region = document.getElementById('edit-node-region').value.trim();
  const tier = document.getElementById('edit-node-tier').value;
  const health = document.getElementById('edit-node-health').value;
  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Saving…</span></div>`;
  try {
    await API.put(`/api/dashboard/node/${nodeId}`, { region, tier, health });
    resultEl.innerHTML = `<div class="result-ok">Node updated.</div>`;
    setTimeout(() => { closeEditModal(); loadNodeMap(); }, 600);
  } catch (e) {
    resultEl.innerHTML = `<div class="result-err">${e.message}</div>`;
  }
}

async function deleteNode(nodeId) {
  try {
    await API.del(`/api/dashboard/node/${nodeId}`);
    await loadNodeMap();
  } catch (e) {
    alert(`Delete failed: ${e.message}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// WebSocket & Sync
// ─────────────────────────────────────────────────────────────────────────
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${protocol}://${window.location.host}/api/ws/state`);
  
  ws.onopen = () => console.log('[WebSocket] Connected');
  
  ws.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    console.log('[WebSocket] Event received:', data);
    
    if (data.type === 'STATE_MUTATED') {
      const activePage = document.querySelector('.page.active')?.id;
      if (activePage === 'page-commits')  await loadCommitLog();
      if (activePage === 'page-ops')      await loadNodeMap();
      
      // If we are looking at the entity that just mutated, reload it
      if (activePage === 'page-entities' && state.selectedEntityId && data.mutated_entities?.includes(state.selectedEntityId)) {
        await loadMerkleTree(state.selectedEntityId);
      }
    }
  };

  ws.onclose = () => {
    console.warn('[WebSocket] Disconnected, retrying in 5s...');
    setTimeout(initWebSocket, 5000);
  };
}

function startPolling() {
  if (state.pollInterval) clearInterval(state.pollInterval);
  // Slower background sync (30s) as fallback, WS does the heavy lifting now
  state.pollInterval = setInterval(async () => {
    const activePage = document.querySelector('.page.active')?.id;
    if (activePage === 'page-ops')      await loadNodeMap();
    if (activePage === 'page-security') await loadSecurityFeed();
  }, 30000);
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 7 — DEVELOPER PORTAL
// ─────────────────────────────────────────────────────────────────────────
async function generateApiKey() {
  const resultEl = document.getElementById('dev-api-key-result');
  if (!resultEl) return;
  resultEl.style.display = 'block';
  resultEl.innerHTML = '<div class="spinner"></div> Generating key...';
  try {
    const res = await API.post('/api/dev/keys');
    if (res.api_key) {
      resultEl.innerHTML = `<strong>Live Key Generated:</strong><br><span style="color:var(--accent); font-weight:600;">${res.api_key}</span><br><span class="text-xs text-muted">Use this in the Authorization: Bearer header</span>`;
    } else {
      resultEl.innerHTML = `<span style="color:var(--danger);">Error: ${JSON.stringify(res)}</span>`;
    }
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--danger);">Failed: ${e.message}</span>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 8 — STAMPEDE SIMULATOR (v4)
// ─────────────────────────────────────────────────────────────────────────

async function pollSimSnapshot() {
  const activePage = document.querySelector('.page.active')?.id;
  if (activePage !== 'page-simulator') return;
  try {
    const data = await API.get('/api/sim/snapshot');
    const convEl = document.getElementById('sim-val-converged');
    if (convEl) {
      convEl.innerText = data.converged ? 'CONVERGED' : 'DIVERGED';
      convEl.style.color = data.converged ? 'var(--fresh)' : 'var(--danger)';
    }
    const hitsEl = document.getElementById('sim-val-hits');
    if (hitsEl) hitsEl.innerText = data.origin_hits || 0;
    const rejEl = document.getElementById('sim-val-rejects');
    if (rejEl) rejEl.innerText = data.origin_rejects || 0;
    const dedupEl = document.getElementById('sim-val-dedup');
    if (dedupEl) dedupEl.innerText = data.dedup_savings || 0;

    const pct = Math.round((data.bucket_level || 1.0) * 100);
    const txtB = document.getElementById('sim-txt-bucket');
    if (txtB) txtB.innerText = pct + '%';
    const fillB = document.getElementById('sim-fill-bucket');
    if (fillB) {
      fillB.style.width = pct + '%';
      fillB.style.background = pct > 40 ? 'var(--fresh)' : pct > 15 ? 'var(--stale)' : 'var(--danger)';
    }

    const container = document.getElementById('sim-nodes-container');
    if (container) {
      container.innerHTML = '';
      (data.nodes || []).forEach(node => {
        const div = document.createElement('div');
        div.style.cssText = 'border:1px solid var(--border); border-radius:6px; padding:8px; margin-bottom:8px; background:var(--surface);';
        let rows = '';
        for (const [key, ent] of Object.entries(node.entries || {})) {
          const origV = data.origin_versions ? data.origin_versions[key] : ent.version;
          const badgeCls = ent.state === 'FRESH' ? 'badge-ok' : ent.state === 'STALE' ? 'badge-stale' : 'badge-quarantined';
          rows += `<div class="flex justify-between text-xs" style="font-family:monospace; margin-bottom:2px;">
            <span>${key}</span>
            <span>v${ent.version} (orig: v${origV}) <span class="badge ${badgeCls}">${ent.state}</span></span>
          </div>`;
        }
        div.innerHTML = `<div class="flex justify-between text-xs font-semibold mb-4" style="border-bottom:1px solid var(--border); padding-bottom:4px;">
          <span>${node.node_id}</span><span class="text-muted">${node.region}</span>
        </div>${rows}`;
        container.appendChild(div);
      });
    }

    const logEl = document.getElementById('sim-event-log');
    if (logEl) {
      logEl.innerHTML = '';
      (data.event_log || []).forEach(evt => {
        const d = document.createElement('div');
        d.style.marginBottom = '2px';
        d.innerText = `[${evt.type || 'EVENT'}] ${evt.detail || JSON.stringify(evt)}`;
        logEl.appendChild(d);
      });
      logEl.scrollTop = logEl.scrollHeight;
    }
  } catch (e) {
    console.error('Error in pollSimSnapshot:', e);
  }
}

async function startSim() {
  await API.post('/api/sim/start', { node_count: 4, key_count: 5, drop_prob: 0.4, max_rps: 6.0, burst: 3 });
  await pollSimSnapshot();
}

async function triggerSimUpdate() {
  await API.post('/api/sim/update', {});
  await pollSimSnapshot();
}

async function triggerSimOverlap() {
  await API.post('/api/sim/update', { key: 'entity:0', data: { value: 300 } });
  await API.post('/api/sim/update', { key: 'entity:1', data: { value: 400 } });
  await pollSimSnapshot();
}

async function stepSimRecovery() {
  await API.post('/api/sim/step', {});
  await pollSimSnapshot();
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 9 — GIT BRANCH MANAGER & DOT INDEXER
// ─────────────────────────────────────────────────────────────────────────
async function loadNodeBranches() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  try {
    const data = await API.get(`/api/branch/list/${nodeId}`);
    const sel = document.getElementById('branch-active-select');
    if (sel) {
      sel.innerHTML = '';
      (data.branches || []).forEach(b => {
        const opt = document.createElement('option');
        opt.value = b.branch_name;
        opt.textContent = `${b.branch_name} (${b.commit_count} commits, Root: ${b.merkle_root.slice(0, 8)}...)`;
        sel.appendChild(opt);
      });
    }
    await switchBranchView();
  } catch (e) {
    console.error('Error in loadNodeBranches:', e);
  }
}

async function switchBranchView() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  const branchName = document.getElementById('branch-active-select')?.value || 'main';
  const container = document.getElementById('branch-history-container');
  if (!container) return;
  try {
    const data = await API.get(`/api/branch/log/${nodeId}/${encodeURIComponent(branchName)}`);
    if (!data.log || !data.log.length) {
      container.innerHTML = `<div class="text-xs text-muted">No commits yet on branch '${branchName}'.</div>`;
      return;
    }
    container.innerHTML = data.log.map(c => `
      <div style="border-bottom:1px solid var(--border); padding:8px 0;">
        <div class="flex justify-between">
          <strong>${c.commit_id}</strong>
          <span class="text-muted text-xs">${new Date(c.timestamp * 1000).toLocaleTimeString()}</span>
        </div>
        <div>${c.message} <span class="text-muted text-xs">(by ${c.developer_id})</span></div>
        <div class="text-xs text-muted">Merkle Root: ${c.merkle_root}</div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="text-xs state-error">Failed to load log: ${e.message}</div>`;
  }
}

async function createBranchPrompt() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  const branchName = prompt("Enter new branch name (e.g. dev/feature-login):");
  if (!branchName) return;
  const devId = prompt("Enter developer ID:", "developer-1") || "developer-1";
  try {
    const res = await API.post('/api/branch/create', {
      node_id: nodeId,
      branch_name: branchName,
      developer_id: devId,
      from_branch: document.getElementById('branch-active-select')?.value || 'main',
    });
    alert(`Branch '${branchName}' created successfully!`);
    await loadNodeBranches();
  } catch (e) {
    alert(`Failed to create branch: ${e.message}`);
  }
}

async function commitBranchModal() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  const branchName = document.getElementById('branch-active-select')?.value || 'main';
  const entityId = prompt("Enter Entity ID to mutate on this branch:", "pat_us_east_001");
  if (!entityId) return;
  const msg = prompt("Enter commit message:", "Branch feature update") || "Branch feature update";
  try {
    const res = await API.post('/api/branch/commit', {
      node_id: nodeId,
      branch_name: branchName,
      developer_id: "dev-user",
      message: msg,
      mutations: [{ entity_id: entityId, entity_type: "patient", data: { status: "branch-updated", timestamp: Date.now() } }],
      edges: []
    });
    const resultBox = document.getElementById('branch-op-result');
    if (resultBox) {
      resultBox.style.display = 'block';
      resultBox.textContent = `✅ Committed ${res.commit_id}\nNew Merkle Root: ${res.merkle_root}`;
    }
    await switchBranchView();
  } catch (e) {
    alert(`Commit failed: ${e.message}`);
  }
}

async function pushActiveBranch() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  const branchName = document.getElementById('branch-active-select')?.value || 'main';
  if (branchName === 'main') {
    alert("Active branch is already 'main'. Select a feature branch to push into main.");
    return;
  }
  try {
    const res = await API.post('/api/branch/push', {
      node_id: nodeId,
      source_branch: branchName,
      target_branch: 'main',
    });
    alert(`✅ Successfully pushed '${branchName}' into 'main'!\nCommit: ${res.commit_id}`);
    await loadNodeBranches();
  } catch (e) {
    alert(`Push failed: ${e.message}`);
  }
}

async function pullActiveBranch() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  const branchName = document.getElementById('branch-active-select')?.value || 'main';
  try {
    const res = await API.post('/api/branch/pull', {
      node_id: nodeId,
      branch_name: branchName,
      from_branch: 'main',
    });
    alert(`✅ Successfully pulled from 'main' into '${branchName}'!`);
    await switchBranchView();
  } catch (e) {
    alert(`Pull failed: ${e.message}`);
  }
}

async function restoreBranchModal() {
  const nodeId = document.getElementById('branch-node-select')?.value || 'us-east-1';
  const branchName = document.getElementById('branch-active-select')?.value || 'main';
  const commitId = prompt("Enter Commit ID to restore/rollback this branch to:");
  if (!commitId) return;
  try {
    const res = await API.post('/api/branch/restore', {
      node_id: nodeId,
      branch_name: branchName,
      commit_id: commitId,
    });
    alert(`✅ Restored '${branchName}' to commit ${commitId}!`);
    await switchBranchView();
  } catch (e) {
    alert(`Restore failed: ${e.message}`);
  }
}

async function resolveDotPath() {
  const path = document.getElementById('dot-path-input')?.value.trim();
  const box = document.getElementById('dot-resolve-result');
  if (!path || !box) return;
  box.textContent = "Resolving dot path...";
  try {
    const res = await API.get(`/api/dot/resolve?path=${encodeURIComponent(path)}`);
    box.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    box.textContent = `Error: ${e.message}`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// PAGE 10 — COMPLIANCE AUDIT TRAIL & QA VERIFIER
// ─────────────────────────────────────────────────────────────────────────
let _auditBadDataOnly = false;

function filterAuditBadData(badOnly) {
  _auditBadDataOnly = badOnly;
  loadAuditTrail();
}

async function loadAuditTrail() {
  try {
    const statsRes = await API.get('/api/audit/stats');
    if (statsRes.trail_summary) {
      document.getElementById('audit-stat-total').textContent = statsRes.trail_summary.total_audit_events || 0;
      document.getElementById('audit-stat-bad').textContent = statsRes.trail_summary.bad_data_events || 0;
      document.getElementById('audit-stat-risk').textContent = statsRes.trail_summary.average_risk_score || "0.00";
    }
    if (statsRes.batch_buffer) {
      document.getElementById('audit-stat-buffer').textContent = statsRes.batch_buffer.queue_depth || 0;
    }

    const url = _auditBadDataOnly ? '/api/audit/trail?is_bad_data=true&limit=50' : '/api/audit/trail?limit=50';
    const trailRes = await API.get(url);
    const container = document.getElementById('audit-table-container');
    if (!container) return;

    if (!trailRes.events || !trailRes.events.length) {
      container.innerHTML = `<div class="text-xs text-muted">No audit records found. Click 'Inject QA Bad Data' to simulate audit logs.</div>`;
      return;
    }

    container.innerHTML = `
      <table style="width:100%; border-collapse:collapse; font-size:12px; font-family:monospace;">
        <thead>
          <tr style="border-bottom:2px solid var(--border); text-align:left; background:var(--surface-2);">
            <th style="padding:6px;">ID</th>
            <th style="padding:6px;">Node / Branch</th>
            <th style="padding:6px;">Event</th>
            <th style="padding:6px;">QA Status</th>
            <th style="padding:6px;">ML Risk</th>
            <th style="padding:6px;">Diagnostic</th>
          </tr>
        </thead>
        <tbody>
          ${trailRes.events.map(e => `
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:6px;">#${e.id}</td>
              <td style="padding:6px;">${e.node_id} <span class="text-muted">(${e.branch_name})</span></td>
              <td style="padding:6px;">${e.event_type}</td>
              <td style="padding:6px;">
                <span class="badge ${e.is_bad_data ? 'badge-quarantined' : 'badge-ok'}">
                  ${e.is_bad_data ? 'BAD DATA' : 'VALID'}
                </span>
              </td>
              <td style="padding:6px; font-weight:600; color:${e.risk_score > 0.7 ? 'var(--danger)' : 'var(--fresh)'};">
                ${e.risk_score}
              </td>
              <td style="padding:6px; color:var(--text-muted);">${e.diagnostic}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    console.error('Error in loadAuditTrail:', e);
  }
}

async function injectBadDataAudit() {
  try {
    await API.post('/api/audit/log', {
      node_id: "eu-west-1",
      branch_name: "qa/adversarial-suite",
      developer_id: "qa-tester-99",
      event_type: "QA_POISON_INJECTION",
      entity_id: "corrupted_entity_999",
      data: { "malformed_field": "X".repeat(1000) },
      timestamp: Date.now() / 1000 - 3600, // 1 hour timestamp drift to trigger QA rule
      request_rate: 95.0,
      is_cross_region: true,
      error_rate: 0.45
    });
    alert("⚠️ QA Bad Data event enqueued into batch buffer!");
    setTimeout(loadAuditTrail, 200);
  } catch (e) {
    alert(`Failed: ${e.message}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// DHCP Dynamic Discovery & Permissions (Phase 24)
// ─────────────────────────────────────────────────────────────────────────

async function loadDirectoryCatalog() {
  try {
    const catalog = await API.get('/api/discovery/catalog');
    const perms = await API.get('/api/permissions/list');
    
    const statTotal = document.getElementById('dhcp-stat-total');
    const statPerms = document.getElementById('dhcp-stat-perms');
    if (statTotal && catalog.total_leases) statTotal.textContent = catalog.total_leases.toLocaleString() + '+';
    if (statPerms && perms.total !== undefined) statPerms.textContent = perms.total;

    // Trigger sample search
    searchDhcpDirectory('');
    loadPermissionRequests();
  } catch (e) {
    console.error('Error in loadDirectoryCatalog:', e);
  }
}

async function searchDhcpDirectory(query) {
  const container = document.getElementById('dhcp-search-results');
  if (!container) return;
  try {
    const res = await API.get(`/api/discovery/search?q=${encodeURIComponent(query || 'pat')}&limit=25`);
    if (!res.results || res.results.length === 0) {
      container.innerHTML = '<div class="text-xs text-muted">No matching canonical aliases found.</div>';
      return;
    }
    container.innerHTML = `
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="border-bottom:1px solid var(--border); text-align:left; color:var(--text-muted);">
            <th style="padding:4px;">Canonical Alias (DHCP)</th>
            <th style="padding:4px;">Raw ID</th>
            <th style="padding:4px;">Assigned IP</th>
            <th style="padding:4px;">Node / Branch</th>
          </tr>
        </thead>
        <tbody>
          ${res.results.map(r => `
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:4px; font-weight:600; color:var(--accent);">${r.canonical_alias}</td>
              <td style="padding:4px;">${r.raw_id}</td>
              <td style="padding:4px; color:var(--text-muted);">${r.assigned_ip}</td>
              <td style="padding:4px;">${r.node_id}:${r.branch_name}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    container.innerHTML = `<div class="text-xs text-danger">Error: ${e.message}</div>`;
  }
}

async function loadPermissionRequests() {
  const container = document.getElementById('permission-requests-container');
  if (!container) return;
  try {
    const res = await API.get('/api/permissions/list');
    if (!res.requests || res.requests.length === 0) {
      container.innerHTML = '<div class="text-xs text-muted">No cross-node permission requests pending.</div>';
      return;
    }
    container.innerHTML = res.requests.map(req => `
      <div style="border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px; margin-bottom:8px; background:var(--surface-2);">
        <div class="row-between mb-4">
          <strong>${req.requester_id}@${req.requester_node} &rarr; ${req.target_node}:${req.target_branch}</strong>
          <span class="badge ${req.status === 'APPROVED' ? 'badge-ok' : req.status === 'PENDING' ? 'badge-stale' : 'badge-quarantined'}">
            ${req.status} [${req.access_level}]
          </span>
        </div>
        <div class="text-xs text-muted mb-4">Reason: ${req.reason}</div>
        ${req.status === 'PENDING' ? `
          <div class="btn-group">
            <button class="btn btn-primary btn-xs" onclick="reviewPermission('${req.request_id}', 'APPROVED')">Approve Lease</button>
            <button class="btn btn-danger btn-xs" onclick="reviewPermission('${req.request_id}', 'REJECTED')">Reject</button>
          </div>
        ` : `<div class="text-xs text-muted">Expires in: ${req.expires_in_s ? req.expires_in_s + 's' : 'Permanent/N/A'}</div>`}
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="text-xs text-danger">Error: ${e.message}</div>`;
  }
}

function openPermissionRequestModal(show = true) {
  const p = document.getElementById('perm-request-panel');
  if (p) p.style.display = show ? 'block' : 'none';
}

async function submitPermissionRequest() {
  const reqId = document.getElementById('perm-requester-id').value;
  const reqNode = document.getElementById('perm-requester-node').value;
  const tgtNode = document.getElementById('perm-target-node').value;
  const tgtBranch = document.getElementById('perm-target-branch').value;
  const accLevel = document.getElementById('perm-access-level').value;
  const reason = document.getElementById('perm-reason').value;

  try {
    const res = await API.post('/api/permissions/request', {
      requester_id: reqId,
      requester_node: reqNode,
      target_node: tgtNode,
      target_branch: tgtBranch,
      access_level: accLevel,
      reason: reason
    });
    alert(`Permission Request ${res.request.request_id} submitted! Status: ${res.request.status}`);
    openPermissionRequestModal(false);
    loadPermissionRequests();
  } catch (e) {
    alert(`Request failed: ${e.message}`);
  }
}

async function reviewPermission(requestId, decision) {
  try {
    const res = await API.post('/api/permissions/review', {
      request_id: requestId,
      reviewer_id: "node-owner-lead",
      decision: decision,
      lease_duration_s: 7200.0
    });
    alert(`Request ${requestId} is now ${res.request.status}`);
    loadPermissionRequests();
  } catch (e) {
    alert(`Review failed: ${e.message}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Nav wiring
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const page = item.dataset.page;
      switchPage(page);
      if (page === 'page-ops')       loadNodeMap();
      if (page === 'page-entities')  { if (state.selectedNodeId) loadEntities(state.selectedNodeId); }
      if (page === 'page-commits')   loadCommitLog();
      if (page === 'page-security')  loadSecurityFeed();
      if (page === 'page-simulator') pollSimSnapshot();
      if (page === 'page-branches')  loadNodeBranches();
      if (page === 'page-audit')     loadAuditTrail();
      if (page === 'page-directory') loadDirectoryCatalog();
    });
  });

  // Initial load
  loadNodeMap();
  initWebSocket();
  startPolling();
  setInterval(pollSimSnapshot, 1500);
});



