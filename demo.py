import asyncio
import httpx
import json

async def run_demo():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000') as c:
        print('1. Verify Nodes')
        r = await c.get('/api/dashboard/node-map')
        for n in r.json()['nodes']:
            print(f"  [Node {n['id']}] Health: {n['health_raw']}, Entities: {n['cached_entity_count']}")
        
        print('\n2. Execute Compound Commit (Mutating pat_us_east_005)')
        commit_payload = {
            'transaction_id': 'tx-demo-123',
            'mutations': [
                {
                    'entity_id': 'pat_us_east_005',
                    'entity_type': 'patient',
                    'data': {'condition': 'Cured - Discharged', 'status': 'completed'}
                }
            ],
            'edges': []
        }
        r2 = await c.post('/api/dashboard/compound-commit', json=commit_payload)
        print('  Commit response:', r2.status_code, r2.json()['status'])
        
        print('\n3. Check ReBAC Authorization')
        r3 = await c.post('/api/dashboard/rebac/test', json={'clinician_id': 'doc_jenkins', 'target_entity_id': 'pat_us_east_005'})
        print('  ReBAC Access:', 'GRANTED' if r3.json().get('authorized') else 'DENIED')
        
        print('\n4. Inject Graph Security Anomaly (Cross-Region Scrape)')
        r4 = await c.post('/api/dashboard/security/test-anomaly', json={
            'requesting_node_id': 'eu-west-1',
            'requester_region': 'EU-West',
            'target_entity_id': 'bill_rogue_999'
        })
        print('  Anomaly Verdict:', r4.json().get('verdict'), '- Flagged:', r4.json().get('flagged'))
        
        print('\n5. Fetch Security Feed')
        r5 = await c.get('/api/dashboard/security-feed')
        for alert in r5.json()['alerts']:
            print(f"  [ALERT] {alert['severity']}: {alert['description']}")

asyncio.run(run_demo())
