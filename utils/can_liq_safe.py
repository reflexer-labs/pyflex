""" Check if a SAFE can be iquidated """
import sys
import os
import time
from web3 import Web3, HTTPProvider
from pyflex import Address
from pyflex.gf import SAFE
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys

if len(sys.argv) != 2:
    print("usage: python can_liq_safe.py <safe addr>")
    sys.exit()

ETH_RPC_URL = os.environ['ETH_RPC_URL']

web3 = Web3(HTTPProvider(endpoint_uri=ETH_RPC_URL, request_kwargs={"timeout": 60}))
while web3.eth.syncing:
    print("Node is syncing")
    time.sleep(5)

geb = GfDeployment.from_node(web3, 'rai')

collateral = geb.collaterals['ETH-A']
collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)
rate = collateral_type.accumulated_rate

safe = geb.safe_engine.safe(collateral_type, Address(sys.argv[1]))

if not geb.liquidation_engine.can_liquidate(collateral_type, safe):
    print("SAFE can't be liquidated.")
else:
    print("SAFE can be liquidated.")
