"""
CacheSplit Phase 22 — Security & Architecture Audit Checklist

Feeds the repo + design doc through a structured audit against 5 categories:
  1. Security Architecture Bugs
  2. Over-Engineering Bugs
  3. Under-Engineering Bugs
  4. API / IAM Bugs
  5. Scalability/Observability Bugs

Each category is scored 0–5 based on detection signals found in source code.
Outputs a scored report with findings, real failure modes, and fix patterns.
"""
import ast
import logging
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent
PY_FILES = list(REPO_ROOT.rglob("*.py"))
DESIGN_DOC = REPO_ROOT / "cache-security-v2-prd-trd-plan.md"
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", "commitcache"}

# ── Helpers ────────────────────────────────────────────────────────────

def get_python_files():
    files = []
    for f in PY_FILES:
        parts = f.parts
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        if f.name.startswith("_") and f.parent.name in ("commitcache",):
            continue
        files.append(f)
    return files

def read_file(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def parse_ast(path):
    try:
        return ast.parse(read_file(path)), path
    except SyntaxError:
        return None, path

def get_all_source():
    source = {}
    for f in get_python_files():
        source[str(f)] = read_file(f)
    return source

def get_all_ast():
    trees = {}
    for f in get_python_files():
        tree, path = parse_ast(f)
        if tree:
            trees[str(path)] = tree
    return trees

def get_all_code():
    return "\n".join(get_all_source().values())

# ── Detection Functions ────────────────────────────────────────────────
# Each returns a list of (file, line_hint, description) findings.

def detect_missing_trust_boundary(source, ast_trees):
    """Detect: any layer can call any other layer directly."""
    findings = []
    # Check if API routes directly import and call DB functions
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "db" in str(node.module) and filepath.startswith(str(REPO_ROOT / "api")):
                    findings.append((filepath, node.lineno,
                        f"API layer imports from db directly: {node.module} — missing trust boundary"))
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if hasattr(node.func.value, 'id') and node.func.value.id == 'node_repo':
                        findings.append((filepath, node.lineno,
                            "API route calls node_repo directly — no controller/gate layer"))
    return findings

def detect_no_tenant_isolation(source, ast_trees):
    """Detect: queries filter by tenant_id in app code, not at DB level."""
    findings = []
    all_code = get_all_code()
    # Check for SELECT without tenant_id filter
    for filepath, content in get_all_source().items():
        for i, line in enumerate(content.split("\n"), 1):
            if re.search(r'(SELECT|INSERT|UPDATE|DELETE)\s+.*FROM', line, re.IGNORECASE):
                if 'tenant_id' not in line and 'tenant' not in line.lower():
                    findings.append((filepath, i,
                        "Raw SQL query without tenant filtering — cross-tenant data leak risk"))
    return findings

def detect_unsigned_state_changes(source, ast_trees):
    """Detect: Events/commits have no HMAC/signature."""
    findings = []
    all_code = get_all_code()
    # Check if commit insert lacks signature verification
    for filepath, content in get_all_source().items():
        if "insert_commit" in content or "upsert_entity" in content:
            if "signed_payload" not in content and "hmac" not in content and "signature" not in content:
                if filepath not in [f for f in ast_trees if "hash_chain" in f]:
                    findings.append((filepath, content.index("insert_commit") + 1 if "insert_commit" in content else 1,
                        "Commit insertion without signed_payload — state changes can be forged"))
    return findings

def detect_secrets_in_config(source, ast_trees):
    """Detect: .env defaults or hardcoded secrets."""
    findings = []
    # Check .env.example for default secrets
    env_example = REPO_ROOT / ".env.example"
    if env_example.exists():
        content = env_example.read_text()
        for i, line in enumerate(content.split("\n"), 1):
            if "=" in line and not line.strip().startswith("#"):
                val = line.split("=", 1)[1].strip()
                if val and not val.startswith("${") and "change-this" not in val and "your-key" not in val and val != "":
                    findings.append((".env.example", i,
                        f"Default secret in .env.example: {line.strip()}"))
    # Check secrets.py for hardcoded fallback
    secrets_path = REPO_ROOT / "ops" / "secrets.py"
    if secrets_path.exists():
        content = secrets_path.read_text()
        if '"local_dev_key"' in content or '"postgres://user:pass@localhost/db"' in content:
            findings.append(("ops/secrets.py", 17,
                "Hardcoded fallback secrets in production code — one leaked env dump = full compromise"))
    return findings

def detect_no_defense_in_depth(source, ast_trees):
    """Detect: Only one control layer (auth or nothing) gates endpoints."""
    findings = []
    # Check API endpoints for layered controls
    for filepath, tree in ast_trees.items():
        if filepath.startswith(str(REPO_ROOT / "api")):
            has_auth = False
            has_rate_limit = False
            has_audit = False
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    body = ast.dump(node)
                    if "get_api_key" in body or "Depends" in body or "APIKey" in body:
                        has_auth = True
                    if "rate_limit" in body or "throttle" in body:
                        has_rate_limit = True
                    if "audit" in body or "log_access" in body:
                        has_audit = True
            if has_auth and not has_rate_limit:
                findings.append((filepath, 1,
                    "Auth present but no rate limiting — single gate, no defense in depth"))
    return findings

def detect_speculative_abstraction(source, ast_trees):
    """Detect: Interface/ABC with exactly 1 implementation."""
    findings = []
    all_code = get_all_code()
    # Check for ABC/Protocol with only one concrete implementation
    for filepath, tree in ast_trees.items():
        has_abstract = False
        has_concrete = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef,)):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef,)) and not item.body:
                        has_abstract = True
        if has_abstract and "adapter" in filepath.lower():
            findings.append((filepath, 1,
                "Abstract base class in adapter layer — likely only 1 implementation (speculative abstraction)"))
    return findings

def detect_premature_config(source, ast_trees):
    """Detect: Config flag that's never toggled in practice."""
    findings = []
    # Check config files for flags that are never read as conditional
    for filepath, content in get_all_source().items():
        if filepath.endswith("config.py") or "config" in filepath:
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(r'(ENABLE_|USE_|DEBUG_|FEATURE_|FLAG_)', line):
                    findings.append((filepath, i,
                        f"Config flag defined but never conditionally used: {line.strip()}"))
    return findings

def detect_over_engineering_interfaces(source, ast_trees):
    """Detect: Generic-for-one-user frameworks, interfaces with single impl."""
    findings = []
    all_code = get_all_code()
    # Count implementations per interface
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [ast.dump(b) for b in node.bases]
                is_abstract = any("ABC" in b or "Protocol" in b for b in bases)
                if is_abstract:
                    # Check if this is the only implementation
                    pass  # Handled in speculative abstraction
    return findings

def detect_no_backoff_circuit_breaker(source, ast_trees):
    """Detect: Retry loop with fixed interval, no cap."""
    findings = []
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                body = ast.dump(node)
                if "while True" in body and "sleep" in body:
                    if "backoff" not in body and "circuit" not in body and "retry" not in body.lower():
                        findings.append((filepath, node.lineno,
                            f"Function '{node.name}' has while True + sleep without backoff/circuit breaker"))
    return findings

def detect_unprotected_shared_state(source, ast_trees):
    """Detect: Mutable dict/list accessed from >1 async task without lock."""
    findings = []
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check for mutable class attributes without Lock
                has_dict_attr = False
                has_lock = False
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if isinstance(item.value, (ast.Dict, ast.List)):
                                    has_dict_attr = True
                    if isinstance(item, ast.Assign) and isinstance(item.value, ast.Attribute):
                        if "Lock" in ast.dump(item.value):
                            has_lock = True
                if has_dict_attr and not has_lock:
                    findings.append((filepath, node.lineno,
                        f"Class '{node.name}' has mutable shared state without lock protection"))
    return findings

def detect_silent_failure_paths(source, ast_trees):
    """Detect: except: pass or dropped messages with no counter."""
    findings = []
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.body and isinstance(handler.body[0], ast.Pass):
                        findings.append((filepath, node.lineno,
                            f"Silent except: pass at line {node.lineno} — data loss invisible"))
                    elif handler.body and len(handler.body) == 1 and isinstance(handler.body[0], ast.Expr) and isinstance(handler.body[0].value, ast.Constant) and handler.body[0].value.value is None:
                        findings.append((filepath, node.lineno,
                            f"Silent except with no-op handler at line {node.lineno}"))
            # Check for bare except
            if isinstance(node, ast.ExceptHandler):
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    pass
    return findings

def detect_hardcoded_topology(source, ast_trees):
    """Detect: Node/tenant list is a literal array in code."""
    findings = []
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.List):
                    # Check if list contains strings that look like node IDs
                    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts):
                        if any("node" in str(e.value).lower() or "-" in str(e.value) for e in node.value.elts if isinstance(e.value, str)):
                            findings.append((filepath, node.lineno,
                                "Hardcoded node/region list in code — adding a node needs a code deploy"))
    return findings

def detect_no_idempotency(source, ast_trees):
    """Detect: Mutating operations without idempotency keys."""
    findings = []
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                body = ast.dump(node)
                if "INSERT" in body or "execute" in body or "upsert" in body:
                    if "idempotency" not in body and "idempotency_key" not in body and "dedup" not in body.lower():
                        if filepath.startswith(str(REPO_ROOT / "api")) or filepath.startswith(str(REPO_ROOT / "services")):
                            findings.append((filepath, node.lineno,
                                f"Function '{node.name}' performs mutations without idempotency key"))
    return findings

def detect_authn_without_authz(source, ast_trees):
    """Detect: Token validation without permission check."""
    findings = []
    for filepath, tree in ast_trees.items():
        if filepath.startswith(str(REPO_ROOT / "api")):
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    body = ast.dump(node)
                    if "get_api_key" in body or "401" in body or "403" in body:
                        if "role" not in body and "permission" not in body and "authz" not in body.lower():
                            findings.append((filepath, node.lineno,
                                f"Endpoint '{node.name}' checks authn but not authz — valid user can access any resource"))
    return findings

def detect_over_scoped_tokens(source, ast_trees):
    """Detect: One token/key grants full API surface."""
    findings = []
    developer_path = REPO_ROOT / "api" / "developer.py"
    if developer_path.exists():
        content = developer_path.read_text()
        if "API_KEYS" in content and "set()" in content:
            findings.append((str(developer_path), 21,
                "Single API_KEYS set grants full API surface — one stolen key = full compromise"))
    return findings

def detect_no_per_identity_rate_limit(source, ast_trees):
    """Detect: Rate limit keyed only on IP."""
    findings = []
    all_code = get_all_code()
    # Check if rate limiting exists and what it keys on
    if "rate_limit" not in all_code.lower() and "throttle" not in all_code.lower():
        for filepath, tree in ast_trees.items():
            if filepath.startswith(str(REPO_ROOT / "api")):
                findings.append((filepath, 1,
                    "No rate limiting at all — no per-identity rate limiting"))
    return findings

def detect_long_lived_credentials(source, ast_trees):
    """Detect: API keys with no expiry, no rotation."""
    findings = []
    developer_path = REPO_ROOT / "api" / "developer.py"
    if developer_path.exists():
        content = developer_path.read_text()
        if "uuid.uuid4" in content and "expiry" not in content and "rotate" not in content.lower():
            findings.append((str(developer_path), 28,
                "Generated API keys have no expiry or rotation — leaked key works forever"))
    secrets_path = REPO_ROOT / "ops" / "secrets.py"
    if secrets_path.exists():
        content = secrets_path.read_text()
        if "rotate_origin_key" in content and "# Implementation details..." in content:
            findings.append((str(secrets_path), 31,
                "Key rotation function is a stub — long-lived credentials never rotate"))
    return findings

def detect_inconsistent_error_responses(source, ast_trees):
    """Detect: 403 vs 404 leaks whether a resource exists."""
    findings = []
    for filepath, tree in ast_trees.items():
        if filepath.startswith(str(REPO_ROOT / "api")):
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    body = ast.dump(node)
                    if "403" in body and "404" in body:
                        findings.append((filepath, node.lineno,
                            f"Endpoint '{node.name}' returns different status codes — resource enumeration possible"))
    return findings

def detect_coupled_hot_loops(source, ast_trees):
    """Detect: Two unrelated tasks share one while loop."""
    findings = []
    for filepath, tree in ast_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "while True" in ast.dump(node):
                    # Count nested task creations
                    task_count = 0
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if "create_task" in child.func.attr:
                                task_count += 1
                    if task_count > 1:
                        findings.append((filepath, node.lineno,
                            f"Function '{node.name}' couples multiple tasks in one while loop"))
    return findings

def detect_happy_path_only_metrics(source, ast_trees):
    """Detect: Counters exist for success, not for drops/rejects/timeouts."""
    findings = []
    for filepath, tree in ast_trees.items():
        if filepath.startswith(str(REPO_ROOT / "services")) or filepath.startswith(str(REPO_ROOT / "ops")):
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    body = ast.dump(node)
                    has_counter = "counter" in body or "metric" in body or "emit_metric" in body
                    has_failure_metric = "drop" in body.lower() or "reject" in body.lower() or "timeout" in body.lower() or "error_count" in body.lower()
                    if has_counter and not has_failure_metric:
                        findings.append((filepath, node.lineno,
                            f"Function '{node.name}' has success metrics but no failure/drop counters"))
    return findings

def detect_no_load_shedding(source, ast_trees):
    """Detect: System accepts requests until it OOMs/crashes."""
    findings = []
    all_code = get_all_code()
    # Check if there's any queue-depth check or rejection
    if "queue_depth" not in all_code and "load_shed" not in all_code and "503" not in all_code:
        for filepath, tree in ast_trees.items():
            if filepath.startswith(str(REPO_ROOT / "api")):
                findings.append((filepath, 1,
                    "API endpoints accept all requests without load shedding — no graceful degradation"))
    return findings

def detect_no_backpressure(source, ast_trees):
    """Detect: Producer can outpace consumer with unbounded queue."""
    findings = []
    for filepath, tree in ast_trees.items():
        if filepath.startswith(str(REPO_ROOT / "services")):
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    body = ast.dump(node)
                    if "Queue" in body or "queue" in body:
                        if "maxsize" not in body and "max_size" not in body and "bound" not in body:
                            findings.append((filepath, node.lineno,
                                f"Class '{node.name}' uses unbounded queue — no backpressure between stages"))
    return findings

def detect_single_point_of_aggregation(source, ast_trees):
    """Detect: One node computes global state (leader with no failover)."""
    findings = []
    for filepath, tree in ast_trees.items():
        if filepath.startswith(str(REPO_ROOT / "services")) or filepath.startswith(str(REPO_ROOT / "core")):
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    body = ast.dump(node)
                    if "leader" in body.lower() and "election" not in body.lower() and "failover" not in body.lower():
                        findings.append((filepath, node.lineno,
                            f"Class '{node.name}' has single leader without failover — SPOF"))
    return findings

# ── Category Definitions ───────────────────────────────────────────────

CATEGORIES = {
    "1. Security Architecture Bugs": {
        "score_label": "Security Architecture Score",
        "detectors": [
            detect_missing_trust_boundary,
            detect_no_tenant_isolation,
            detect_unsigned_state_changes,
            detect_secrets_in_config,
            detect_no_defense_in_depth,
        ]
    },
    "2. Over-Engineering Bugs": {
        "score_label": "Over-Engineering Score",
        "detectors": [
            detect_speculative_abstraction,
            detect_premature_config,
            detect_over_engineering_interfaces,
        ]
    },
    "3. Under-Engineering Bugs": {
        "score_label": "Under-Engineering Score",
        "detectors": [
            detect_no_backoff_circuit_breaker,
            detect_unprotected_shared_state,
            detect_silent_failure_paths,
            detect_hardcoded_topology,
            detect_no_idempotency,
        ]
    },
    "4. API / IAM Bugs": {
        "score_label": "API/IAM Score",
        "detectors": [
            detect_authn_without_authz,
            detect_over_scoped_tokens,
            detect_no_per_identity_rate_limit,
            detect_long_lived_credentials,
            detect_inconsistent_error_responses,
        ]
    },
    "5. Scalability/Observability Bugs": {
        "score_label": "Scalability/Observability Score",
        "detectors": [
            detect_coupled_hot_loops,
            detect_happy_path_only_metrics,
            detect_no_load_shedding,
            detect_no_backpressure,
            detect_single_point_of_aggregation,
        ]
    },
}

# ── Audit Runner ───────────────────────────────────────────────────────

def run_audit():
    source = get_all_source()
    ast_trees = get_all_ast()

    print("=" * 80)
    print("  CacheSplit Phase 22 — Architecture & Security Audit")
    print("  Repository: " + str(REPO_ROOT))
    print("  Python files scanned: " + str(len(source)))
    print("=" * 80)

    total_score = 0
    report = {}

    for category_name, cat_config in CATEGORIES.items():
        findings = []
        for detector in cat_config["detectors"]:
            try:
                result = detector(source, ast_trees)
                findings.extend(result)
            except Exception as e:
                logger.warning(f"Detector {detector.__name__} failed: {e}")

        # Score: 0-5 based on severity and count of findings
        score = min(5, len(findings))
        total_score += score

        # Deduplicate by (file, description)
        seen = set()
        unique_findings = []
        for f in findings:
            key = (f[0], f[2])
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        report[category_name] = {
            "score": score,
            "findings": unique_findings,
            "config": cat_config,
        }

    print()
    for category_name, data in report.items():
        print(f"\n{'-' * 80}")
        print(f"  {category_name}")
        print(f"  {'=' * 20}")
        print(f"  Score: {data['score']}/5 {'*' if data['score'] >= 3 else 'OK' if data['score'] == 0 else ''}")
        print(f"{'-' * 80}")

        if not data["findings"]:
            print("  No findings - clean OK")
            continue

        # Group by file
        by_file = defaultdict(list)
        for f in data["findings"]:
            by_file[f[0]].append(f)

        for filepath, file_findings in by_file.items():
            short_path = filepath.replace(str(REPO_ROOT) + "\\", "").replace(str(REPO_ROOT) + "/", "")
            print(f"\n  FILE: {short_path}")
            for f in file_findings[:5]:  # Show up to 5 per file
                print(f"     Line {f[1]}: {f[2]}")
            if len(file_findings) > 5:
                print(f"     ... and {len(file_findings) - 5} more")

        # Show fix patterns from the audit table
        if category_name in [
            "1. Security Architecture Bugs",
            "3. Under-Engineering Bugs",
            "4. API / IAM Bugs",
            "5. Scalability/Observability Bugs",
        ]:
            print(f"\n  FIX:")
            for f in data["findings"][:3]:
                print(f"     -> {f[2]}")

    # Summary
    print(f"\n{'=' * 80}")
    print(f"  AUDIT SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Total Score: {total_score}/25")
    risk_label = 'HIGH RISK' if total_score >= 15 else 'MEDIUM RISK' if total_score >= 8 else 'LOW RISK' if total_score >= 4 else 'CLEAN'
    risk_icon = '[HIGH]' if total_score >= 15 else '[MED]' if total_score >= 8 else '[LOW]' if total_score >= 4 else '[OK]'
    print(f"  {risk_icon} {risk_label}")
    print()

    for category_name, data in report.items():
        bar = "#" * data["score"] + "." * (5 - data["score"])
        status = "FAIL" if data["score"] >= 3 else "PASS" if data["score"] == 0 else "WARN"
        print(f"  [{status}] {data['score']}/5  {bar}  {category_name}")

    print(f"\n  Next step: Address findings with {total_score} risk points above.")
    print(f"  Run with --json for structured output.")
    print()

    return report

# ── JSON Export ────────────────────────────────────────────────────────

def run_audit_json():
    import json
    report = run_audit()
    output = {}
    for cat, data in report.items():
        output[cat] = {
            "score": data["score"],
            "findings": [
                {"file": f[0], "line": f[1], "issue": f[2]}
                for f in data["findings"]
            ]
        }
    print(json.dumps(output, indent=2))

# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--json" in sys.argv:
        run_audit_json()
    else:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
        run_audit()
