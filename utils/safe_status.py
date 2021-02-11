""" Print out stats on a SAFE """
import sys
import os
import time
from web3 import Web3, HTTPProvider
from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.numeric import Wad, Ray

if len(sys.argv) != 2:
    print("usage: python safe_stats.py <safe address>")
    sys.exit()

safe_addr = sys.argv[1]

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
liq_price = collateral_type.liquidation_price

safe = geb.safe_engine.safe(collateral_type, Address(safe_addr))
print(f"SAFE {safe_addr}")
print("-----------------------------------------------------------------------------")
print(f"collateral_type                              {str(safe.collateral_type.name)}")
print(f"locked_collateral                            {str(safe.locked_collateral)}")
print(f"generated_debt                               {str(safe.generated_debt)}")

if safe.generated_debt != Wad(0):
    is_critical = (Ray(safe.locked_collateral) * collateral_type.liquidation_price) < Ray(safe.generated_debt) * collateral_type.accumulated_rate
    coll_ratio = (safe.locked_collateral * collateral_type.liquidation_price * geb.oracle_relayer.liquidation_c_ratio(collateral_type)) / (safe.generated_debt * collateral_type.accumulated_rate) * 100
    print(f"coll_ratio                                   {coll_ratio}")
