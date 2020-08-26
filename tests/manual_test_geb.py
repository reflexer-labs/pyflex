# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
from web3 import Web3, HTTPProvider

from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.numeric import Wad

web3 = Web3(HTTPProvider(endpoint_uri=os.environ['ETH_RPC_URL'], request_kwargs={"timeout": 10}))
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
if len(sys.argv) > 2:
    register_keys(web3, [sys.argv[2]])  # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass
    run_transactions = True
else:
    run_transactions = False
geb = GfDeployment.from_node(web3)
our_address = Address(web3.eth.defaultAccount)

# Choose the desired collateral; in this case we'll wrap some Eth
collateral = geb.collaterals['ETH-A']
collateral_type = collateral.collateral_type

# Set an amount of collateral to join and an amount of Dai to draw
collateral_amount = Wad.from_number(0.2)
system_coin_amount = Wad.from_number(20.0)

if collateral.collateral.balance_of(our_address) > collateral_amount:
    if run_transactions and collateral.collateral_type.name.startswith("ETH"):
        # Wrap ETH to produce WETH
        assert collateral.collateral.deposit(collateral_amount).transact()

    if run_transactions:
        # Add collateral and allocate the desired amount of Dai
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, collateral_amount).transact()
        assert geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, delta_collateral=collateral_amount,
                                                           delta_debt=Wad(0)).transact()
        assert geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, delta_collateral=Wad(0),
                                                           delta_debt=system_coin_amount).transact()

    print(f"SAFE balance: {geb.safe_engine.safes(collateral_type, our_address)}")
    print(f"System coin balance: {geb.safe_engine.coin_balance(our_address)}")

    if run_transactions:
        # Mint and withdraw our system coin
        geb.approve_system_coin(our_address)
        assert geb.system_coin_adapter.exit(our_address, system_coin_amount).transact()
        print(f"System coin balance after withdrawal:  {geb.safe_engine.coin_balance(our_address)}")

        # Repay (and burn) our system coin
        assert geb.system_coin_adapter.join(our_address, system_coin_amount).transact()
        print(f"System coin balance after repayment:   {geb.safe_engine.coin_balance(our_address)}")

        # Withdraw our collateral; stability fee accumulation may make these revert
        assert geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, delta_collateral=Wad(0),
                                                           delta_debt=system_coin_amount*-1).transact()
        assert geb.safe_engine.modify_safe_collateralization(collateral_type, our_address, delta_collateral=collateral_amount*-1,
                                                           delta_debt=Wad(0)).transact()
        assert collateral.adapter.exit(our_address, collateral_amount).transact()
        print(f"System coin balance w/o collateral:    {geb.safe_engine.coin_balance(our_address)}")
else:
    print(f"Not enough {collateral_type.name} to join to the safe_engine")

print(f"Collateral balance: {geb.safe_engine.collateral(collateral_type, our_address)}")
