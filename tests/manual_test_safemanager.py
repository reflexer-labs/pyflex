# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2020 ith-harvey
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


import sys
import os
from web3 import Web3, HTTPProvider

from pyflex import Address
from pyflex.deployment import GfDeployment
from pyflex.keys import register_keys
from pyflex.numeric import Wad
from pyflex.proxy import DSProxy

endpoint_uri = f"{os.environ['SERVER_ETH_RPC_HOST']}:{os.environ['SERVER_ETH_RPC_PORT']}"
web3 = Web3(HTTPProvider(endpoint_uri=endpoint_uri,
                         request_kwargs={"timeout": 10}))
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
register_keys(web3, [sys.argv[2]])      # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass
safeid = int(sys.argv[3])

geb = GfDeployment.from_network(web3, "kovan")
our_address = Address(web3.eth.defaultAccount)

proxy = geb.proxy_registry.proxies(our_address)
if proxy == Address("0x0000000000000000000000000000000000000000"):
    print(f"No proxy exists for our address. Building one first")
    geb.proxy_registry.build(our_address).transact()

proxy = DSProxy(web3, Address(geb.proxy_registry.proxies(our_address)))

print(f"Default account: {our_address.address}")
print(f"{our_address} has a DS-Proxy - {proxy.address.address}, test will continue")

print(f"SAFE of Safe ID {safeid} - {geb.safe_manager.safe(safeid)}")
print(f"Owner of SAFE ID {safeid} - {geb.safe_manager.owns_safe(safeid)}")
print(f"CollateralType of SAFE ID {safeid} - {geb.safe_manager.collateral_type(safeid)}")

print(f"First of Safe ID for account {proxy.address.address} - {geb.safe_manager.first_safe_id(proxy.address)}")
print(f"Last of Safe ID for account {proxy.address.address} - {geb.safe_manager.last_safe_id(proxy.address)}")
print(f"Number of all SAFEs created via DSProxy contract {proxy.address.address} - {geb.safe_manager.safe_count(proxy.address)}")
