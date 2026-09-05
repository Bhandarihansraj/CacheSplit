import sys
import requests
import json
import uuid

BASE_URL = "http://localhost:8000"

def print_banner():
    print("=======================================")
    print("      CacheSplit CLI Demo Menu         ")
    print("=======================================")

def register_node():
    node_id = input("Enter Node ID (e.g., node-custom-1): ") or f"node-{uuid.uuid4().hex[:4]}"
    region = input("Enter Region (e.g., us-west-1): ") or "us-west-1"
    tier = input("Enter Tier (e.g., edge): ") or "edge"
    
    url = f"{BASE_URL}/api/register"
    params = {
        "node_id": node_id,
        "region": region,
        "tier": tier,
        "join_token": "demo-token"
    }
    
    try:
        resp = requests.post(url, params=params)
        print(f"\nResponse [{resp.status_code}]: {json.dumps(resp.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

def create_user():
    name = input("Enter user name: ") or "Alice Demo"
    email = input("Enter user email: ") or "alice@demo.local"
    url = f"{BASE_URL}/api/users"
    payload = {"name": name, "email": email}
    
    try:
        resp = requests.post(url, json=payload)
        print(f"\nResponse [{resp.status_code}]: {json.dumps(resp.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

def scan_entity():
    entity_id = input("Enter entity ID to scan: ")
    if not entity_id:
        print("Entity ID is required!")
        return
        
    url = f"{BASE_URL}/api/scan/{entity_id}"
    try:
        resp = requests.get(url)
        print(f"\nResponse [{resp.status_code}]: {json.dumps(resp.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

def trigger_anomaly():
    req_node = input("Enter requesting node ID: ") or "node-hacker-1"
    req_region = input("Enter requester region: ") or "ru-moscow-1"
    target_id = input("Enter target entity ID (e.g., some orphan ID): ") or "orphan_billing_001"
    
    url = f"{BASE_URL}/api/dashboard/security/test-anomaly"
    payload = {
        "requesting_node_id": req_node,
        "requester_region": req_region,
        "target_entity_id": target_id
    }
    
    try:
        resp = requests.post(url, json=payload)
        print(f"\nResponse [{resp.status_code}]: {json.dumps(resp.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

def main():
    while True:
        print_banner()
        print("1) Handshake & Register a node")
        print("2) Submit a Compound Commit (Create User)")
        print("3) Scan an Entity")
        print("4) Trigger a Security Anomaly")
        print("5) Exit")
        
        choice = input("\nSelect an option [1-5]: ").strip()
        
        if choice == '1':
            register_node()
        elif choice == '2':
            create_user()
        elif choice == '3':
            scan_entity()
        elif choice == '4':
            trigger_anomaly()
        elif choice == '5' or choice.lower() in ('q', 'quit', 'exit'):
            print("Exiting...")
            sys.exit(0)
        else:
            print("Invalid choice, please try again.")
            
        print("\n" + "-"*40 + "\n")

if __name__ == "__main__":
    main()
