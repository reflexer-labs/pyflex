import sys
import os
from web3 import Web3, HTTPProvider
from pyflex.deployment import GfDeployment

ETH_RPC_URL = os.environ['ETH_RPC_URL']
web3 = Web3(HTTPProvider(endpoint_uri=ETH_RPC_URL,
                         request_kwargs={"timeout": 10}))

start_safeid = int(sys.argv[1])
end_safeid = int(sys.argv[2])

geb = GfDeployment.from_node(web3, 'rai')

for safeid in range(start_safeid, end_safeid +1):
    print(f"Owner of SAFE ID {safeid} - {geb.safe_manager.owns_safe(safeid)}")
    print(f"SAFE of Safe ID {safeid} - {geb.safe_manager.safe(safeid)}")
