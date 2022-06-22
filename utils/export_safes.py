import sys
import os
import csv
from web3 import Web3, HTTPProvider
from pyflex.deployment import GfDeployment

out_file = sys.argv[1]

ETH_RPC_URL = os.environ['ETH_RPC_URL']
web3 = Web3(HTTPProvider(endpoint_uri=ETH_RPC_URL,
                         request_kwargs={"timeout": 10}))

geb = GfDeployment.from_node(web3, 'rai')
safe_owner = None

safes = []
#SAFE('0x0000000000000000000000000000000000000000')[[] locked_collateral=0.000000000000000000 generated_debt=0.000000000000000000]
safe_id = 1
while True:
    print(f"procesing {safe_id}")
    safe = geb.safe_manager.safe(safe_id)
    owner = geb.safe_manager.owns_safe(safe_id)

    if owner.address == '0x0000000000000000000000000000000000000000':
        break

    safes.append((safe_id, safe.address.address, owner.address, str(safe.locked_collateral), str(safe.generated_debt)))

    safe_id += 1

with open(out_file, 'w') as f:
    write = csv.writer(f)
    write.writerow(['safe_id', 'safe', 'owner', 'collateral', 'debt'])
    write.writerows(safes)
