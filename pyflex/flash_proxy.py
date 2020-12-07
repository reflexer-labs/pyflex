# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 reverendus, bargst, EdNoepel
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

from pprint import pformat
from typing import Union
from web3 import Web3

from pyflex import Contract, Address, Transact

class GebKeeperFlashProxy(Contract):
    """A client for the `GebKeeperFlashProxy` contract, used to interact with collateral auctions.

    You can find the source code of the `GebKeeperFlashProxy` contract here:
    <https://github.com/reflexer-labs/geb-keeper-flash-proxy/blob/master/src/GebKeeperFlashProxy.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `GebKeeperFlashProxy` contract.

    """

    abi = Contract._load_abi(__name__, 'abi/GebKeeperFlashProxy.abi')
    #bin = Contract._load_bin(__name__, 'abi/GebKeeperFlashProxy.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def liquidate_and_settle_safe(self, safe_address: Address) -> Transact:
        assert isinstance(safe_address, Address)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'liquidateAndSettleSAFE', [safe_address.address])

    def settle_auction(self, auction_id: Union[int, list]):
        assert isinstance(auction_id, int) or isinstance(auction_id, list)
        if isinstance(auction_id, int):
            return Transact(self, self.web3, self.abi, self.address, self._contract, 'settleAuction(uint256)', [auction_id])

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'settleAuction(uint256[])', [auction_id])

    def __repr__(self):
        return f"GebKeeperFlashProxy('{self.address}')"
