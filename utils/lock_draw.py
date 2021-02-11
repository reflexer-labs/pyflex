""" script to lock collateral and draw rai.
    It is highly recommended to use the Reflexer App https://app.reflexer.finance, or
    geb-js https://docs.reflexer.finance/geb-js/getting-started to interact with the system.
    Pyflex uses unmanaged SAFEs
"""
import sys
import os
import time
from web3 import Web3, HTTPProvider
from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.numeric import Wad
from warn import pyflex_warning


if len(sys.argv) != 3:
    print("usage: python lock_draw.py <ether amount to lock> <rai amount to draw>")
    sys.exit()

def confirm():
    warning = (f'----------------------------------WARNING-----------------------------------------------\n'
              'It is highly recommended to use the Reflexer App or Geb-js to perform SAFE modifications\n'
              'Pyflex uses unmanaged SAFEs, which are not supported by the App or geb-js.\n'
              'If you use pyflex to open or modify a SAFE, it will be unaccessible in the App or geb-js!\n')

    answer = ""
    while answer not in ["y", "n"]:
        print(warning)
        answer = input("OK to continue [Y/N]? ").lower()
    return answer == "y"

pyflex_warning()

new_collateral_amount = Wad.from_number(sys.argv[1])
new_debt_amount = Wad.from_number(sys.argv[2])

ETH_RPC_URL = os.environ['ETH_RPC_URL']

web3 = Web3(HTTPProvider(endpoint_uri=ETH_RPC_URL, request_kwargs={"timeout": 60}))
while web3.eth.syncing:
    print("Node is syncing")
    time.sleep(5)

print(f"Current block number: {web3.eth.blockNumber}")
web3.eth.defaultAccount = os.environ['ETH_ACCOUNT']
register_keys(web3, [os.environ['ETH_KEYPASS']])

geb = GfDeployment.from_node(web3, 'rai')
our_address = Address(web3.eth.defaultAccount)

collateral = geb.collaterals['ETH-A']
collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)



# Get SAFE status before modification
safe = geb.safe_engine.safe(collateral_type, our_address)
if safe.generated_debt > Wad(0):
    coll_ratio = (safe.locked_collateral * collateral_type.liquidation_price * geb.oracle_relayer.liquidation_c_ratio(collateral_type)) / (safe.generated_debt * collateral_type.accumulated_rate) * 100
else:
    coll_ratio = 0

print("")
print("Safe before modification")
print("------------------------")
print(f"locked_collateral: {safe.locked_collateral}")
print(f"generated_debt: {safe.generated_debt}")
print(f"coll ratio: {coll_ratio}")

# validate the SAFE modification. 
try:
    geb.safe_engine.validate_safe_modification(collateral_type, our_address, delta_collateral=new_collateral_amount, delta_debt=new_debt_amount)
except AssertionError:
    print("modification did not pass validation. Exiting.")
    sys.exit()

collateral.approve(our_address)
geb.approve_system_coin(our_address)

## Adding new collateral
collateral.collateral.deposit(new_collateral_amount).transact()
collateral.adapter.join(our_address, new_collateral_amount).transact()

# execute the SAFE modification. 
geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, delta_collateral=new_collateral_amount, delta_debt=new_debt_amount).transact()

# Get SAFE status after modification
safe = geb.safe_engine.safe(collateral_type, our_address)
coll_ratio = (safe.locked_collateral * collateral_type.liquidation_price * geb.oracle_relayer.liquidation_c_ratio(collateral_type)) / (safe.generated_debt * collateral_type.accumulated_rate) * 100
print("")
print("Safe after modification")
print("------------------------")
print(f"locked_collateral: {safe.locked_collateral}")
print(f"generated_debt: {safe.generated_debt}")
print(f"coll ratio: {coll_ratio}")

# Exit our system coin
geb.system_coin_adapter.exit(our_address, new_debt_amount).transact()
