/**
 * CacheSplit v4 — Controller Layer (MVC)
 * All UI interactions route through Controller.
 * Models (services_v4.js) handle data. Views (HTML) render output.
 * TestRunner provides the test framework.
 */

// ── Controller ───────────────────────────────────────────────
const Controller = {
    // ── Auth ────────────────────────────────────────────────
    async authLogin() {
        const identity = document.getElementById('auth-identity').value;
        const password = document.getElementById('auth-password').value;
        try {
            const data = await Models.Auth.login(identity, password);
            const el = document.getElementById('auth-result');
            const info = document.getElementById('auth-info');
            if (data.access_token) {
                el.textContent = `✅ Authenticated as ${identity}\nTenant: ${data.tenant_id}\nTier: ${data.tier || 'standard'}`;
                info.style.display = 'block';
                document.getElementById('auth-tenant').textContent = data.tenant_id;
                document.getElementById('auth-tier').textContent = data.tier || 'standard';
                document.getElementById('auth-perms').textContent = data.permissions?.join(', ') || 'read';
                document.getElementById('auth-status').textContent = `Authenticated: ${identity}`;
                document.getElementById('auth-status').className = 'auth-badge ok';
                document.getElementById('tenant-display').textContent = data.tenant_id;
                document.getElementById('tenant-display').className = 'tenant-badge active';
            } else {
                el.textContent = `❌ ${data.error || 'Login failed'}`;
            }
        } catch(e) {
            document.getElementById('auth-result').textContent = `❌ ${e.message}`;
        }
    },

    async authRefresh() {
        try {
            const data = await Models.Auth.refresh();
            document.getElementById('auth-result').textContent = `✅ Token refreshed\nExpires: ${data.expires_in}s`;
        } catch(e) {
            document.getElementById('auth-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Tenant ──────────────────────────────────────────────
    async loadTenants() {
        try {
            const tenants = await Models.Tenant.loadAll();
            const el = document.getElementById('tenant-list');
            el.innerHTML = tenants.map(t => `
                <div class="tenant-card">
                    <strong>${t.tenant_id}</strong> (${t.region})<br>
                    <small>Tier: ${t.role || 'standard'} · Permission: ${t.permissions?.join(', ') || 'N/A'}</small>
                </div>
            `).join('') || 'No tenants registered.';
        } catch(e) {
            document.getElementById('tenant-list').innerHTML = `❌ ${e.message}`;
        }
    },

    // ── Topology ────────────────────────────────────────────
    async loadTopology() {
        try {
            const views = await Models.Topology.load();
            const el = document.getElementById('topology-views');
            el.innerHTML = Object.entries(views).map(([rid, v]) => `
                <div class="topology-view">
                    <h4>${rid} — ${v.is_home_region ? '🏠 Home' : '📡 Replica'}</h4>
                    <p>Nodes: ${v.nodes?.length || 0} | Tenants: ${v.tenant_shards?.length || 0} | Version: ${v.version}</p>
                    <p>Stale: ${Models.Topology.isStale() ? '⚠ Yes' : '✓ Fresh'}</p>
                </div>
            `).join('') || 'No topology loaded.';
        } catch(e) {
            document.getElementById('topology-views').innerHTML = `❌ ${e.message}`;
        }
    },

    async addRegion() {
        const region = document.getElementById('topo-region').value;
        const nodes = document.getElementById('topo-nodes').value.split(',').map(n => n.trim());
        const tenants = document.getElementById('topo-tenants').value.split(',').map(t => t.trim());
        try {
            const data = await Models.Topology.addRegion(region, nodes, tenants, 'dr-lease-token');
            document.getElementById('topology-views').innerHTML += `<div class="success">✅ Region ${region} added</div>`;
        } catch(e) {
            document.getElementById('topology-views').innerHTML += `<div class="error">❌ ${e.message}</div>`;
        }
    },

    // ── Network ─────────────────────────────────────────────
    async loadNetworkZones() {
        try {
            const zones = await Models.Network.loadZones();
            const el = document.getElementById('network-zones');
            el.innerHTML = Object.entries(zones).map(([tid, z]) => `
                <div class="network-zone">
                    <strong>${tid}</strong> — ${z.tier}<br>
                    VPC: ${z.vpc_cidr} | Subnet: ${z.subnet_cidr} | SG: ${z.security_group_ids?.join(', ')}<br>
                    Isolated: ${z.is_isolated ? '✅' : '❌'}
                </div>
            `).join('') || 'No network zones configured.';
        } catch(e) {
            document.getElementById('network-zones').innerHTML = `❌ ${e.message}`;
        }
    },

    // ── DR Failover ─────────────────────────────────────────
    async initiateFailover() {
        const region = document.getElementById('failover-region').value;
        const signal = document.getElementById('failover-signal').value;
        try {
            const data = await Models.Failover.initiate(region, signal);
            document.getElementById('failover-result').textContent = JSON.stringify(data, null, 2);
        } catch(e) {
            document.getElementById('failover-result').textContent = `❌ ${e.message}`;
        }
    },

    async confirmFailover() {
        try {
            const events = await Models.Failover.loadHistory();
            const pending = events.filter(e => e.state === 'PROMOTING');
            if (!pending.length) {
                document.getElementById('failover-result').textContent = 'No pending failovers to confirm.';
                return;
            }
            const data = await Models.Failover.confirm(pending[0].event_id || pending[0].proposal_id);
            document.getElementById('failover-result').textContent = JSON.stringify(data, null, 2);
        } catch(e) {
            document.getElementById('failover-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Sharding ────────────────────────────────────────────
    async loadShardRing() {
        try {
            const ring = await Models.Shard.load();
            document.getElementById('shard-result').textContent = JSON.stringify(ring, null, 2);
        } catch(e) {
            document.getElementById('shard-result').textContent = `❌ ${e.message}`;
        }
    },

    async getShard() {
        const tenantId = document.getElementById('shard-tenant').value;
        try {
            const data = await Models.Shard.getShard(tenantId);
            document.getElementById('shard-result').textContent = JSON.stringify(data, null, 2);
        } catch(e) {
            document.getElementById('shard-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Queue Pool ──────────────────────────────────────────
    async loadQueues() {
        try {
            const pools = await Models.Queue.loadStats();
            const el = document.getElementById('queue-stats');
            el.innerHTML = Object.entries(pools).map(([tid, s]) => `
                <div class="queue-stat">
                    <strong>${tid}</strong> — Depth: ${s.queue_depth}/${s.max_size}
                    <br>Processed: ${s.processed} | Rejected: ${s.rejected} | Tier: ${s.tier}
                    <br>Full: ${s.queue_depth >= s.max_size ? '⚠️ YES' : '✓ No'}
                </div>
            `).join('') || 'No queues.';
        } catch(e) {
            document.getElementById('queue-stats').innerHTML = `❌ ${e.message}`;
        }
    },

    // ── Read Replicas ───────────────────────────────────────
    async routeReplica() {
        const tenantId = document.getElementById('replica-tenant').value;
        const op = document.getElementById('replica-op').value;
        try {
            const data = await Models.ReadReplica.route(tenantId, op);
            document.getElementById('replica-result').textContent = JSON.stringify(data, null, 2);
        } catch(e) {
            document.getElementById('replica-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Ingress ─────────────────────────────────────────────
    async loadIngressStats() {
        try {
            const stats = await Models.Ingress.getStats();
            document.getElementById('ingress-result').textContent = JSON.stringify(stats, null, 2);
        } catch(e) {
            document.getElementById('ingress-result').textContent = `❌ ${e.message}`;
        }
    },

    async checkBackpressure() {
        const tenantId = document.getElementById('ingress-tenant').value;
        const tier = document.getElementById('ingress-tier').value;
        try {
            const data = await Models.Backpressure.check(tenantId, tier);
            document.getElementById('ingress-result').textContent =
                `Allow: ${data.allow}\nRetry-After: ${data.retry_after_seconds}s\nDepth: ${data.current_depth}/${data.threshold}\nReason: ${data.reason}`;
        } catch(e) {
            document.getElementById('ingress-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Priority Model ──────────────────────────────────────
    async loadFallbackRate() {
        try {
            const data = await Models.Priority.getFallbackRate();
            document.getElementById('priority-result').textContent = JSON.stringify(data, null, 2);
        } catch(e) {
            document.getElementById('priority-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Anomaly Detector ────────────────────────────────────
    async loadAnomalies() {
        try {
            const alerts = await Models.Anomaly.loadAlerts();
            const el = document.getElementById('anomaly-result');
            el.innerHTML = alerts.length ? alerts.map(a =>
                `⚠️ ${a.node_id}/${a.tenant_id} — Score: ${a.score}\n   ${a.reason}\n`
            ).join('\n') : 'No anomalies detected.';
        } catch(e) {
            document.getElementById('anomaly-result').textContent = `❌ ${e.message}`;
        }
    },

    async getAnomalyMetrics() {
        try {
            const data = await Models.Anomaly.getMetrics();
            document.getElementById('anomaly-metrics').textContent =
                `Verification Failures: ${data.verification_failures || 0}`;
        } catch(e) {
            document.getElementById('anomaly-metrics').textContent = `❌ ${e.message}`;
        }
    },

    // ── Guardrail ───────────────────────────────────────────
    async loadGuardrailHistory() {
        try {
            const history = await Models.Guardrail.getHistory();
            document.getElementById('guardrail-result').textContent =
                history.length ? history.map(p =>
                    `${p.approved ? '✅' : '❌'} ${p.action} target=${p.target} confidence=${p.confidence}`
                ).join('\n') : 'No proposals.';
        } catch(e) {
            document.getElementById('guardrail-result').textContent = `❌ ${e.message}`;
        }
    },

    // ── Dashboard ───────────────────────────────────────────
    async loadDashboard() {
        try {
            await Models.Dashboard.loadNodeMap();
            const commits = await Models.Dashboard.loadCommits();
            const metrics = await Models.Dashboard.getMetrics();
            document.getElementById('node-map').innerHTML =
                `<div>Nodes: ${Models.Dashboard.nodes.length}</div>` +
                Models.Dashboard.nodes.map(n => `
                    <div class="node-mini">${n.id || n.region} — Health: ${n.health || 'ok'}</div>
                `).join('');
            document.getElementById('dashboard-metrics').textContent =
                `Commits: ${commits.length} | Nodes: ${Models.Dashboard.nodes.length}`;
        } catch(e) {
            document.getElementById('node-map').innerHTML = `❌ ${e.message}`;
        }
    },

    // ── WebSocket ───────────────────────────────────────────
    initWS() {
        Models.WS.onMessage((data) => {
            if (data.type === 'STATE_MUTATED') {
                console.log('[WS] State mutated:', data);
                Controller.loadDashboard();
            }
        });
        Models.WS.connect();
    }
};

// ── Navigation ───────────────────────────────────────────────
function switchPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const pg = document.getElementById(pageId);
    if (pg) pg.classList.add('active');
    document.getElementById('page-title').textContent =
        pg?.querySelector('h3')?.textContent || pageId;
}

// ── Bootstrap ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            switchPage(item.dataset.page);
        });
    });
    Controller.loadDashboard();
    Controller.initWS();
});
