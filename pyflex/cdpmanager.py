
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
from pyflex.gf import CollateralType, CDP, CDPEngine
from pyflex.numeric import Wad


class CdpManager(Contract):
    """A client for the `DSCdpManger` contract, which is a wrapper around the cdp system, for easier use.

    Ref. <https://github.com/makerdao/dss-cdp-manager/blob/master/src/DssCdpManager.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/GebCdpManager.abi')
    bin = Contract._load_bin(__name__, 'abi/GebCdpManager.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)
        self.cdp_engine = CDPEngine(self.web3, Address(self._contract.functions.cdpEngine().call()))

    def open_cdp(self, collateral_type: CollateralType, address: Address) -> Transact:
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(address, Address)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'openCDP',
                        [collateral_type.toBytes(), address.address])

    def cdp(self, cdpid: int) -> CDP:
        '''Returns CDP for respective CDP ID'''
        assert isinstance(cdpid, int)

        cdp_address = Address(self._contract.functions.cdps(cdpid).call())
        collateral_type = self.collateral_type(cdpid)
        cdp = self.cdp_engine.cdp(collateral_type, Address(cdp_address))

        return cdp

    def owns_cdp(self, cdpid: int) -> Address:
        '''Returns owner Address of respective CDP ID'''
        assert isinstance(cdpid, int)

        owner = Address(self._contract.functions.ownsCDP(cdpid).call())
        return owner

    def collateral_type(self, cdpid: int) -> CollateralType:
        '''Returns CollateralType for respective CDP ID'''
        assert isinstance(cdpid, int)

        collateral_type = CollateralType.fromBytes(self._contract.functions.collateralTypes(cdpid).call())
        return collateral_type

    def first_cdp_id(self, address: Address) -> int:
        '''Returns first CDP Id created by owner address'''
        assert isinstance(address, Address)

        cdpid = int(self._contract.functions.firstCDPID(address.address).call())
        return cdpid

    def last_cdp_id(self, address: Address) -> int:
        '''Returns last CDP Id created by owner address'''
        assert isinstance(address, Address)

        cdpid = self._contract.functions.lastCDPID(address.address).call()
        return int(cdpid)

    def cdp_count(self, address: Address) -> int:
        '''Returns number of CDP's created using the DS-Cdp-Manager contract specifically'''
        assert isinstance(address, Address)

        count = int(self._contract.functions.cdpCount(address.address).call())
        return count

    def __repr__(self):
        return f"CdpManager('{self.address}')"
