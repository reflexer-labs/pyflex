""" script to liquidate a SAFE, starting a collateral auction """
import sys
import os
import time
from web3 import Web3, HTTPProvider
from pyflex import Address
from pyflex.gf import SAFE
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys

if len(sys.argv) != 2:
    print("usage: python liq_safe.py <safe addr>")
    sys.exit()

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

if not geb.liquidation_engine.can_liquidate(collateral_type, SAFE(Address(sys.argv[1]))):
    print("SAFE can't be liquidated. Exiting.")
    sys.exit()

assert geb.liquidation_engine.liquidate_safe(collateral_type, SAFE(Address(sys.argv[1]))).transact()
