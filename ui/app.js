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
    <div class="dag-node-hash">⬡ ${shortHash}…</div>
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
    logEl.innerHTML = `<div class="state-msg text-muted">No commits yet. Use the Compound Commit form to write data.</div>`;
    return;
  }
  logEl.innerHTML = `<div class="feed">` + commits.map(c => `
    <div class="feed-item">
      <div class="feed-dot" style="background:var(--accent-2)"></div>
      <div class="feed-body">
        <div class="feed-title font-mono text-xs">${c.transaction_id}</div>
        <div class="feed-meta">
          ${c.entity_ids?.length || 0} entities · hash: ${(c.commit_hash||'').slice(0,16)}… · ${timeFmt(c.created_at)}
        </div>
      </div>
      <div class="feed-badge"><span class="badge badge-ok">Committed</span></div>
    </div>
  `).join('') + `</div>`;
}

async function submitCompoundCommit() {
  const resultEl = document.getElementById('commit-result');
  const entityId  = document.getElementById('commit-entity-id').value.trim();
  const entityType= document.getElementById('commit-entity-type').value.trim();
  const dataRaw   = document.getElementById('commit-data-json').value.trim();

  if (!entityId || !entityType || !dataRaw) {
    resultEl.innerHTML = `<div class="result-err">All fields required.</div>`;
    return;
  }
  let dataObj;
  try { dataObj = JSON.parse(dataRaw); }
  catch { resultEl.innerHTML = `<div class="result-err">Invalid JSON in data field.</div>`; return; }

  resultEl.innerHTML = `<div class="state-msg"><div class="spinner"></div><span>Committing…</span></div>`;
  try {
    const txId = `tx-${Date.now()}`;
    const data = await API.post('/api/dashboard/compound-commit', {
      transaction_id: txId,
      mutations: [{ entity_id: entityId, entity_type: entityType, data: dataObj }],
      edges: [],
    });
    resultEl.innerHTML = `
      <div class="result-ok">
        <strong>Committed</strong> — tx: ${data.result?.transaction_id}<br>
        <span class="result-mono">Hash: ${data.result?.commit_hash}</span>
      </div>`;
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
// Confirm Dialog
// ─────────────────────────────────────────────────────────────────────────
function confirmAction(message, onConfirm) {
  if (window.confirm(message)) onConfirm();
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
// Live Poll — refreshes node map and security feed every 5s
// ─────────────────────────────────────────────────────────────────────────
function startPolling() {
  if (state.pollInterval) clearInterval(state.pollInterval);
  state.pollInterval = setInterval(async () => {
    const activePage = document.querySelector('.page.active')?.id;
    if (activePage === 'page-ops')      await loadNodeMap();
    if (activePage === 'page-security') await loadSecurityFeed();
    if (activePage === 'page-commits')  await loadCommitLog();
  }, 5000);
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
      if (page === 'page-ops')      loadNodeMap();
      if (page === 'page-entities') { if (state.selectedNodeId) loadEntities(state.selectedNodeId); }
      if (page === 'page-commits')  loadCommitLog();
      if (page === 'page-security') loadSecurityFeed();
    });
  });

  // Initial load
  loadNodeMap();
  startPolling();
});
