""" Call tax_single() """
import os
import time
from web3 import Web3, HTTPProvider
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys

ETH_RPC_URL = os.environ['ETH_RPC_URL']

web3 = Web3(HTTPProvider(endpoint_uri=ETH_RPC_URL, request_kwargs={"timeout": 60}))
while web3.eth.syncing:
    print("Node is syncing")
    time.sleep(5)

print(f"Current block number: {web3.eth.blockNumber}")

web3.eth.defaultAccount = os.environ['ETH_ACCOUNT']
register_keys(web3, [os.environ['ETH_KEYPASS']])

geb = GfDeployment.from_node(web3, 'rai')

collateral = geb.collaterals['ETH-A']
collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)
geb.tax_collector.tax_single(collateral_type).transact()
