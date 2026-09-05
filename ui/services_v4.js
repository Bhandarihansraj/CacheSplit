"""
Model Layer — CacheSplit v4 API Client.
Encapsulates all HTTP/WebSocket communication.
Controller and View never touch raw fetch() directly.
"""
const API_BASE = 'http://127.0.0.1:8000';
const API_KEY = 'cs_live_55464b6bedb94e77b6444fe49c2e4a2c';
const AUTH_TOKEN = null; // Set after login via /api/auth/token

// ── Model: Auth ──────────────────────────────────────────────
const AuthModel = {
    token: null,
    tenant_id: null,
    identity: null,
    permissions: [],
    tier: 'standard',

    async login(identity, password) {
        const res = await fetch(`${API_BASE}/api/auth/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity, password })
        });
        const data = await res.json();
        if (data.access_token) {
            this.token = data.access_token;
            this.tenant_id = data.tenant_id;
            this.identity = data.identity;
            this.permissions = data.permissions || [];
            this.tier = data.tier || 'standard';
        }
        return data;
    },

    async refresh() {
        const res = await fetch(`${API_BASE}/api/auth/refresh`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.token}`
            }
        });
        const data = await res.json();
        this.token = data.access_token;
        return data;
    },

    headers() {
        return {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.token || API_KEY}`
        };
    },

    isAuthenticated() {
        return !!this.token && !!this.tenant_id;
    }
};

// ── Model: Tenant ────────────────────────────────────────────
const TenantModel = {
    tenants: [],
    current: null,

    async loadAll() {
        const res = await fetch(`${API_BASE}/api/tenant/registry`, {
            headers: AuthModel.headers()
        });
        this.tenants = await res.json();
        return this.tenants;
    },

    async get(tenantId) {
        const res = await fetch(`${API_BASE}/api/tenant/${tenantId}`, {
            headers: AuthModel.headers()
        });
        this.current = await res.json();
        return this.current;
    }
};

// ── Model: Topology ──────────────────────────────────────────
const TopologyModel = {
    views: {},
    lastUpdated: null,

    async load() {
        const res = await fetch(`${API_BASE}/api/topology`, {
            headers: AuthModel.headers()
        });
        this.views = await res.json();
        this.lastUpdated = Date.now();
        return this.views;
    },

    async addRegion(regionId, nodes, tenantIds, leaseToken) {
        const res = await fetch(`${API_BASE}/api/topology/regions`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify({ region_id: regionId, nodes, tenant_ids: tenantIds, lease_token: leaseToken })
        });
        return await res.json();
    },

    isStale() {
        if (!this.lastUpdated) return true;
        return (Date.now() - this.lastUpdated) > 30000;
    }
};

// ── Model: Shard Ring ────────────────────────────────────────
const ShardModel = {
    ring: {},

    async load() {
        const res = await fetch(`${API_BASE}/api/sharding/ring`, {
            headers: AuthModel.headers()
        });
        this.ring = await res.json();
        return this.ring;
    },

    async getShard(tenantId) {
        const res = await fetch(
            `${API_BASE}/api/sharding/shard/${encodeURIComponent(tenantId)}`,
            { headers: AuthModel.headers() }
        );
        return await res.json();
    },

    async rebalance(leaseToken, newNodes, removedNodes) {
        const res = await fetch(`${API_BASE}/api/sharding/rebalance`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify({ lease_token: leaseToken, new_nodes: newNodes, removed_nodes: removedNodes })
        });
        return await res.json();
    }
};

// ── Model: Queue Pool ────────────────────────────────────────
const QueueModel = {
    pools: {},

    async loadStats() {
        const res = await fetch(`${API_BASE}/api/queue/stats`, {
            headers: AuthModel.headers()
        });
        this.pools = await res.json();
        return this.pools;
    },

    async getTenantQueue(tenantId) {
        const res = await fetch(
            `${API_BASE}/api/queue/${encodeURIComponent(tenantId)}`,
            { headers: AuthModel.headers() }
        );
        return await res.json();
    },

    async getDepth(tenantId) {
        const res = await fetch(
            `${API_BASE}/api/queue/${encodeURIComponent(tenantId)}/depth`,
            { headers: AuthModel.headers() }
        );
        const data = await res.json();
        return data.depth;
    },

    async backpressureCheck(tenantId, tier) {
        const res = await fetch(
            `${API_BASE}/api/queue/backpressure`,
            {
                method: 'POST',
                headers: AuthModel.headers(),
                body: JSON.stringify({ tenant_id: tenantId, tier })
            }
        );
        return await res.json();
    }
};

// ── Model: Repair Queue ──────────────────────────────────────
const RepairModel = {
    queue: [],
    priorityScores: {},

    async load() {
        const res = await fetch(`${API_BASE}/api/repair/queue`, {
            headers: AuthModel.headers()
        });
        this.queue = await res.json();
        return this.queue;
    },

    async score(report) {
        const res = await fetch(`${API_BASE}/api/repair/score`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify(report)
        });
        return await res.json();
    },

    async enqueue(task) {
        const res = await fetch(`${API_BASE}/api/repair/enqueue`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify(task)
        });
        return await res.json();
    }
};

// ── Model: Backpressure ──────────────────────────────────────
const BackpressureModel = {
    async check(tenantId, tier) {
        const res = await fetch(
            `${API_BASE}/api/backpressure/check`,
            {
                method: 'POST',
                headers: AuthModel.headers(),
                body: JSON.stringify({ tenant_id: tenantId, tier })
            }
        );
        return await res.json();
    },

    async getStats() {
        const res = await fetch(`${API_BASE}/api/backpressure/stats`, {
            headers: AuthModel.headers()
        });
        return await res.json();
    }
};

// ── Model: Read Replica Router ───────────────────────────────
const ReadReplicaModel = {
    async route(tenantId, op) {
        const res = await fetch(
            `${API_BASE}/api/read-replica/route`,
            {
                method: 'POST',
                headers: AuthModel.headers(),
                body: JSON.stringify({ tenant_id: tenantId, operation: op })
            }
        );
        return await res.json();
    }
};

// ── Model: Anomaly Detector ──────────────────────────────────
const AnomalyModel = {
    alerts: [],
    verificationFailures: 0,

    async loadAlerts(limit = 50) {
        const res = await fetch(
            `${API_BASE}/api/anomaly/alerts?limit=${limit}`,
            { headers: AuthModel.headers() }
        );
        this.alerts = await res.json();
        return this.alerts;
    },

    async verifyEvent(event) {
        const res = await fetch(`${API_BASE}/api/anomaly/verify`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify({ event })
        });
        return await res.json();
    },

    async getMetrics() {
        const res = await fetch(`${API_BASE}/api/anomaly/metrics`, {
            headers: AuthModel.headers()
        });
        const data = await res.json();
        this.verificationFailures = data.verification_failures || 0;
        return data;
    }
};

// ── Model: Agent Guardrail ───────────────────────────────────
const GuardrailModel = {
    proposals: [],
    rejectionRate: 0,

    async submit(proposal) {
        const res = await fetch(`${API_BASE}/api/guardrail/submit`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify(proposal)
        });
        const data = await res.json();
        this.rejectionRate = data.rejection_rate || 0;
        return data;
    },

    async getHistory(limit = 50) {
        const res = await fetch(
            `${API_BASE}/api/guardrail/history?limit=${limit}`,
            { headers: AuthModel.headers() }
        );
        this.proposals = await res.json();
        return this.proposals;
    }
};

// ── Model: DR Failover ───────────────────────────────────────
const FailoverModel = {
    events: [],

    async initiate(regionId, healthSignal) {
        const res = await fetch(`${API_BASE}/api/failover/initiate`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify({ region_id: regionId, health_signal: healthSignal })
        });
        return await res.json();
    },

    async confirm(eventId) {
        const res = await fetch(`${API_BASE}/api/failover/confirm`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify({ event_id: eventId })
        });
        return await res.json();
    },

    async loadHistory() {
        const res = await fetch(`${API_BASE}/api/failover/history`, {
            headers: AuthModel.headers()
        });
        this.events = await res.json();
        return this.events;
    },

    async getState() {
        const res = await fetch(`${API_BASE}/api/failover/state`, {
            headers: AuthModel.headers()
        });
        return await res.json();
    }
};

// ── Model: Network Policy ────────────────────────────────────
const NetworkModel = {
    zones: {},

    async loadZones() {
        const res = await fetch(`${API_BASE}/api/network/zones`, {
            headers: AuthModel.headers()
        });
        this.zones = await res.json();
        return this.zones;
    },

    async getZone(tenantId) {
        const res = await fetch(
            `${API_BASE}/api/network/zone/${encodeURIComponent(tenantId)}`,
            { headers: AuthModel.headers() }
        );
        return await res.json();
    }
};

// ── Model: Audit Log ─────────────────────────────────────────
const AuditModel = {
    async getEvents(tenantId, limit = 100) {
        const params = tenantId ? `?tenant_id=${tenantId}&limit=${limit}` : `?limit=${limit}`;
        const res = await fetch(`${API_BASE}/api/audit/events${params}`, {
            headers: AuthModel.headers()
        });
        return await res.json();
    },

    async verifyChain(tenantId) {
        const res = await fetch(
            `${API_BASE}/api/audit/verify${tenantId ? `?tenant_id=${tenantId}` : ''}`,
            { headers: AuthModel.headers() }
        );
        return await res.json();
    }
};

// ── Model: Ingress Backpressure ──────────────────────────────
const IngressModel = {
    async check(tenantId, tier) {
        const res = await fetch(
            `${API_BASE}/api/ingress/check`,
            {
                method: 'POST',
                headers: AuthModel.headers(),
                body: JSON.stringify({ tenant_id: tenantId, tier })
            }
        );
        return await res.json();
    },

    async getStats() {
        const res = await fetch(`${API_BASE}/api/ingress/stats`, {
            headers: AuthModel.headers()
        });
        return await res.json();
    }
};

// ── Model: Dashboard ─────────────────────────────────────────
const DashboardModel = {
    nodes: [],
    commits: [],
    securityFeed: [],

    async loadNodeMap() {
        const res = await fetch(`${API_BASE}/api/dashboard/node-map`, {
            headers: AuthModel.headers()
        });
        this.nodes = await res.json().nodes || [];
        return this.nodes;
    },

    async loadCommits(limit = 20) {
        const res = await fetch(
            `${API_BASE}/api/dashboard/commits/recent?limit=${limit}`,
            { headers: AuthModel.headers() }
        );
        this.commits = await res.json().commits || [];
        return this.commits;
    },

    async loadSecurityFeed(limit = 20) {
        const res = await fetch(
            `${API_BASE}/api/dashboard/security-feed?limit=${limit}`,
            { headers: AuthModel.headers() }
        );
        this.securityFeed = await res.json().alerts || [];
        return this.securityFeed;
    },

    async getMetrics() {
        const res = await fetch(`${API_BASE}/api/dashboard/metrics`, {
            headers: AuthModel.headers()
        });
        return await res.json();
    }
};

// ── Model: Priority Model ────────────────────────────────────
const PriorityModel = {
    async score(features) {
        const res = await fetch(`${API_BASE}/api/priority/score`, {
            method: 'POST',
            headers: AuthModel.headers(),
            body: JSON.stringify(features)
        });
        return await res.json();
    },

    async getFallbackRate() {
        const res = await fetch(`${API_BASE}/api/priority/fallback-rate`, {
            headers: AuthModel.headers()
        });
        return await res.json();
    }
};

// ── WebSocket Model ──────────────────────────────────────────
const WSModel = {
    ws: null,
    connected: false,
    listeners: [],

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        this.ws = new WebSocket(
            `${protocol}://${window.location.host}/api/ws/state`
        );

        this.ws.onopen = () => {
            this.connected = true;
            this.listeners.forEach(fn => fn('connected'));
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.listeners.forEach(fn => fn(data));
        };

        this.ws.onclose = () => {
            this.connected = false;
            this.listeners.forEach(fn => fn('disconnected'));
            setTimeout(() => this.connect(), 5000);
        };
    },

    onMessage(fn) { this.listeners.push(fn); },

    send(data) {
        if (this.ws && this.connected) {
            this.ws.send(JSON.stringify(data));
        }
    }
};

// ── Expose Models for Controller ─────────────────────────────
window.Models = {
    Auth: AuthModel,
    Tenant: TenantModel,
    Topology: TopologyModel,
    Shard: ShardModel,
    Queue: QueueModel,
    Repair: RepairModel,
    Backpressure: BackpressureModel,
    ReadReplica: ReadReplicaModel,
    Anomaly: AnomalyModel,
    Guardrail: GuardrailModel,
    Failover: FailoverModel,
    Network: NetworkModel,
    Audit: AuditModel,
    Ingress: IngressModel,
    Dashboard: DashboardModel,
    Priority: PriorityModel,
    WS: WSModel
};
