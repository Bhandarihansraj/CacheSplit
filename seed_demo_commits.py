"""
CacheSplit v3 — Seed 100 Realistic Demo Commits
Creates 100 compound commits that update real entities in the system.
Run against a live server:  python seed_demo_commits.py [--count N] [--base-url URL]
"""
import argparse
import random
import time
import uuid
import httpx

REGIONS = ["us-east-1", "eu-west-1", "asia-south-1"]
REGION_LABELS = ["US-East", "EU-West", "Asia-South"]
ENTITY_TYPES = ["patient", "visit", "lab_result", "bed"]
CONDITIONS = [
    "Hypertension", "Type-2 Diabetes", "Asthma", "Arrhythmia",
    "Recovery", "Stable", "Post-Surgery", "Oncology", "Pneumonia",
    "Fracture", "Infection", "Cardiac Event", "Stroke Recovery",
]
STATUS_OPTIONS = ["admitted", "discharged", "transferred", "stable", "critical", "monitoring"]
LAB_NAMES = ["CBC", "BMP", "Lipid Panel", "TSH", "HbA1c", "Urinalysis", "Chest X-Ray"]
CLINICIANS = ["doc_jenkins", "doc_vance", "doc_chen"]


def pick_region():
    idx = random.randint(0, len(REGIONS) - 1)
    return REGIONS[idx], REGION_LABELS[idx]


def make_patient_mutation(region_label):
    region_safe = region_label.lower().replace(" ", "_").replace("-", "_")
    idx = random.randint(1, 50)
    eid = f"pat_{region_safe}_{idx:03d}"
    return {
        "entity_id": eid,
        "entity_type": "patient",
        "data": {
            "condition": random.choice(CONDITIONS),
            "status": random.choice(STATUS_OPTIONS),
            "age": random.randint(18, 85),
            "updated_by": random.choice(CLINICIANS),
        },
    }


def make_visit_mutation(region_label):
    region_safe = region_label.lower().replace(" ", "_").replace("-", "_")
    idx = random.randint(1, 50)
    eid = f"vis_{region_safe}_{idx:03d}"
    return {
        "entity_id": eid,
        "entity_type": "visit",
        "data": {
            "purpose": random.choice(["routine_check", "emergency", "follow_up", "procedure"]),
            "status": random.choice(["active", "completed", "cancelled"]),
            "department": random.choice(["Emergency", "Cardiology", "Oncology", "General"]),
        },
    }


def make_lab_mutation(region_label):
    region_safe = region_label.lower().replace(" ", "_").replace("-", "_")
    idx = random.randint(1, 50)
    eid = f"lab_{region_safe}_{idx:03d}"
    return {
        "entity_id": eid,
        "entity_type": "lab_result",
        "data": {
            "test_name": random.choice(LAB_NAMES),
            "result_value": round(random.uniform(70.0, 145.0), 1),
            "unit": "mg/dL",
            "status": random.choice(["final", "preliminary", "corrected"]),
        },
    }


def make_bed_mutation(region_label):
    region_safe = region_label.lower().replace(" ", "_").replace("-", "_")
    idx = random.randint(1, 50)
    eid = f"bed_{region_safe}_{idx:03d}"
    return {
        "entity_id": eid,
        "entity_type": "bed",
        "data": {
            "bed_number": random.randint(1, 20),
            "ward": random.choice(["ICU", "General", "Pediatric", "Maternity"]),
            "status": random.choice(["occupied", "available", "maintenance"]),
            "patient_id": f"pat_{region_safe}_{idx:03d}",
        },
    }


MUTATION_BUILDERS = [make_patient_mutation, make_visit_mutation, make_lab_mutation, make_bed_mutation]


def generate_commit(i):
    region_id, region_label = pick_region()
    n_mutations = random.choices([1, 2, 3], weights=[50, 35, 15])[0]
    builder = random.choice(MUTATION_BUILDERS)
    mutations = [builder(region_label) for _ in range(n_mutations)]
    edges = []
    if n_mutations >= 2 and random.random() > 0.5:
        edges.append({
            "source_id": mutations[0]["entity_id"],
            "relation": "HAS_CURRENT_VISIT" if mutations[0]["entity_type"] == "patient" else "CONTAINS_LAB",
            "target_id": mutations[1]["entity_id"],
        })
    return {
        "transaction_id": f"tx-demo-{i:04d}-{uuid.uuid4().hex[:8]}",
        "mutations": mutations,
        "edges": edges,
    }


def main():
    parser = argparse.ArgumentParser(description="Seed demo commits into CacheSplit")
    parser.add_argument("--count", type=int, default=100, help="Number of commits (default: 100)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server base URL")
    args = parser.parse_args()

    success = 0
    errors = 0
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        for i in range(1, args.count + 1):
            commit = generate_commit(i)
            try:
                r = client.post("/api/dashboard/compound-commit", json=commit)
                if r.status_code == 200:
                    success += 1
                    if i % 10 == 0 or i == args.count:
                        print(f"  [{i}/{args.count}] OK — {commit['transaction_id']}")
                else:
                    errors += 1
                    print(f"  [{i}/{args.count}] HTTP {r.status_code}: {r.text[:80]}")
            except Exception as e:
                errors += 1
                print(f"  [{i}/{args.count}] ERROR: {e}")
            # Tiny delay to avoid flooding
            if i % 20 == 0:
                time.sleep(0.1)

    print(f"\nDone: {success} committed, {errors} errors")


if __name__ == "__main__":
    main()
