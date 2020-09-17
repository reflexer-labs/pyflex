
# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2017-2020 ith-harvey
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


from web3 import Web3
from pyflex import Address, Contract, Transact
from pyflex.gf import CollateralType, SAFE, SAFEEngine
from pyflex.numeric import Wad


class SAFEManager(Contract):
    """A client for the `GebSAFEManger` contract, which is a wrapper around the safe system, for easier use.

    Ref. <https://github.com/reflexer-labs/geb-safe-manager/blob/master/src/GebSAFEManager.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/GebSAFEManager.abi')
    bin = Contract._load_bin(__name__, 'abi/GebSAFEManager.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)
        self.safe_engine = SAFEEngine(self.web3, Address(self._contract.functions.safeEngine().call()))

    def open_safe(self, collateral_type: CollateralType, address: Address) -> Transact:
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(address, Address)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'openSAFE',
                        [collateral_type.toBytes(), address.address])

    def safe(self, safeid: int) -> SAFE:
        '''Returns SAFE for respective SAFE ID'''
        assert isinstance(safeid, int)

        safe_address = Address(self._contract.functions.safes(safeid).call())
        collateral_type = self.collateral_type(safeid)
        safe = self.safe_engine.safe(collateral_type, Address(safe_address))

        return safe

    def owns_safe(self, safeid: int) -> Address:
        '''Returns owner Address of respective SAFE ID'''
        assert isinstance(safeid, int)

        owner = Address(self._contract.functions.ownsSAFE(safeid).call())
        return owner

    def collateral_type(self, safeid: int) -> CollateralType:
        '''Returns CollateralType for respective SAFE ID'''
        assert isinstance(safeid, int)

        collateral_type = CollateralType.fromBytes(self._contract.functions.collateralTypes(safeid).call())
        return collateral_type

    def first_safe_id(self, address: Address) -> int:
        '''Returns first SAFE Id created by owner address'''
        assert isinstance(address, Address)

        safeid = int(self._contract.functions.firstSAFEID(address.address).call())
        return safeid

    def last_safe_id(self, address: Address) -> int:
        '''Returns last SAFE Id created by owner address'''
        assert isinstance(address, Address)

        safeid = self._contract.functions.lastSAFEID(address.address).call()
        return int(safeid)

    def safe_count(self, address: Address) -> int:
        '''Returns number of SAFE's created using the Geb-SAFE-Manager contract specifically'''
        assert isinstance(address, Address)

        count = int(self._contract.functions.safeCount(address.address).call())
        return count

    def __repr__(self):
        return f"SAFEManager('{self.address}')"
