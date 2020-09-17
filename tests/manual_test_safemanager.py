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
#from pyflex.dsr import Dsr

endpoint_uri = f"{os.environ['SERVER_ETH_RPC_HOST']}:{os.environ['SERVER_ETH_RPC_PORT']}"
web3 = Web3(HTTPProvider(endpoint_uri=endpoint_uri,
                         request_kwargs={"timeout": 10}))
web3.eth.defaultAccount = sys.argv[1]   # ex: 0x0000000000000000000000000000000aBcdef123
register_keys(web3, [sys.argv[2]])      # ex: key_file=~keys/default-account.json,pass_file=~keys/default-account.pass
safeid = int(sys.argv[3])

geb = GfDeployment.from_network(web3, "kovan")
our_address = Address(web3.eth.defaultAccount)
#dsr_client = Dsr(mcd, our_address)
print(our_address)

print(f"Default account: {our_address.address}")
if dsr_client.has_proxy():
    proxy = dsr_client.get_proxy()
    print(f"{our_address} has a DS-Proxy - {proxy.address.address}, test will continue")

    print(f"Urn of SAFE ID {safeid} - {mcd.safe_manager.urn(safeid)}")
    print(f"Owner of SAFE ID {safeid} - {mcd.safe_manager.owns(safeid)}")
    print(f"List of SAFE IDs next to and previous to {safeid} - {mcd.safe_manager.list(safeid)}")
    print(f"Ilk of SAFE ID {safeid} - {mcd.safe_manager.ilk(safeid)}")

    print(f"First of SAFE ID for account {proxy.address.address} - {mcd.safe_manager.first(proxy.address)}")
    print(f"Last of SAFE ID for account {proxy.address.address} - {mcd.safe_manager.last(proxy.address)}")
    print(f"Number of all SAFEs created via DS-SAFE-Manager contract {proxy.address.address} - {mcd.safe_manager.count(proxy.address)}")

else:
    print(f"{our_address} does not have a DS-Proxy. Please create a safe on kovan via Oasis.app (to create a proxy) to perform this test")


