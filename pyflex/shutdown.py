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

import logging
from datetime import datetime
from typing import Optional, List

from web3 import Web3

from pyflex import Address, Contract, Transact
from pyflex.approval import directly, approve_cdp_modification_directly
from pyflex.gf import CollateralType
from pyflex.numeric import Wad, Ray, Rad
from pyflex.token import DSToken, ERC20Token


logger = logging.getLogger()


class ShutdownModule(Contract):
    """A client for the `ESM` contract, which allows users to call `global_settlement.shutdown_system()` and thereby trigger a shutdown.

    Ref. <https://github.com/makerdao/esm/blob/master/src/ESM.sol>

    Attributes:
      web3: An instance of `Web` from `web3.py`.
      address: Ethereum address of the `ESM` contract."""

    abi = Contract._load_abi(__name__, 'abi/ESM.abi')
    bin = Contract._load_bin(__name__, 'abi/ESM.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def sum(self) -> Wad:
        """Total balance of Gov `join`ed to this contract"""
        return Wad(self._contract.functions.Sum().call())

    def sum_of(self, address: Address) -> Wad:
        """Gov `join`ed to this contract by a specific account"""
        assert isinstance(address, Address)

        return Wad(self._contract.functions.sum(address.address).call())

    def min(self) -> Wad:
        """Minimum amount of Gov required to call `fire`"""
        return Wad(self._contract.functions.min().call())

    def fired(self) -> bool:
        """True if `fire` has been called"""
        return bool(self._contract.functions.fired().call())

    def join(self, value: Wad) -> Transact:
        """Before `fire` can be called, sufficient Gov must be `join`ed to this contract"""
        assert isinstance(value, Wad)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'join', [value.value])

    def fire(self):
        """Calls `shutdown_system` on the `GlobalSettlement` contract, initiating a shutdown."""
        logger.info("Calling fire to shutdown the global settlement")
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'fire', [])


class GlobalSettlement(Contract):
    """A client for the `GlobalSettlement` contract, used to orchestrate a shutdown.

    Ref. <https://github.com/makerdao/dss/blob/master/src/end.sol>

    Attributes:
      web3: An instance of `Web` from `web3.py`.
      address: Ethereum address of the `ESM` contract."""

    abi = Contract._load_abi(__name__, 'abi/GlobalSettlement.abi')
    bin = Contract._load_bin(__name__, 'abi/GlobalSettlement.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def contract_enabled(self) -> bool:
        """True when enabled, false when disabled"""
        return self._contract.functions.contractEnabled().call() > 0

    def shutdown_time(self) -> datetime:
        """Time of disable_contract"""
        timestamp = self._contract.functions.shutdownTime().call()
        return datetime.utcfromtimestamp(timestamp)

    def shutdown_cooldown(self) -> int:
        """Processing cooldown length, in seconds"""
        return int(self._contract.functions.shutdownCooldown().call())

    def outstanding_coin_supply(self) -> Rad:
        """total outstanding system coin following processing"""
        return Rad(self._contract.functions.outstandingCoinSupply().call())

    def final_coin_per_collateral_price(self, collateral_type: CollateralType) -> Ray:
        """Shutdown price for the collateral"""
        assert isinstance(collateral_type, CollateralType)
        return Ray(self._contract.functions.finalCoinPerCollateralPrice(collateral_type.toBytes()).call())

    def collateral_shortfall(self, collateral_type: CollateralType) -> Wad:
        """Collateral shortfall (difference of debt and collateral"""
        assert isinstance(collateral_type, CollateralType)
        return Wad(self._contract.functions.collateralShortfall(collateral_type.toBytes()).call())

    def collateral_total_debt(self, collateral_type: CollateralType) -> Wad:
        """Total debt for the collateral"""
        assert isinstance(collateral_type, CollateralType)
        return Wad(self._contract.functions.collateralTotalDebt(collateral_type.toBytes()).call())

    def collateral_cash_price(self, collateral_type: CollateralType) -> Ray:
        """Final cash price for the collateral"""
        assert isinstance(collateral_type, CollateralType)
        return Ray(self._contract.functions.collateralCashPrice(collateral_type.toBytes()).call())

    def coin_bag(self, address: Address) -> Wad:
        """Amount of system `prepare_coins_for_redeeming`ed for retrieving collateral in return"""
        assert isinstance(address, Address)
        return Wad(self._contract.functions.coinBag(address.address).call())

    def coins_used_to_redeem(self, collateral_type: CollateralType, address: Address) -> Wad:
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(address, Address)
        return Wad(self._contract.functions.coinsUsedToRedeem(collateral_type.toBytes(), address.address).call())

    def shutdown_system(self, collateral_type: CollateralType) -> Transact:
        """Set the `shutdownSystem` price for the collateral"""
        assert isinstance(collateral_type, CollateralType)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'shutDownSystem(bytes32)', [collateral_type.toBytes()])

    def fast_track_auction(self, collateral_type: CollateralType, collateral_auction_id: int) -> Transact:
        """Cancel a flip auction and seize it's collateral"""
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(flip_id, int)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'fastTrackAuction', [collateral_type.toBytes(), collateral_auction_id])

    def process_cdp(self, collateral_type: CollateralType, address: Address) -> Transact:
        """Cancels undercollateralized CDP debt to determine collateral shortfall"""
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(address, Address)
        return Transact(self, self.web3, self.abi, self.address, self._contract,
                        'processCDP', [collateral_type.toBytes(), address.address])

    def free_collateral(self, collateral_type: CollateralType) -> Transact:
        """Releases excess collateral after `process_cdp`ing"""
        assert isinstance(collateral_type, CollateralType)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'freeCollateral', [collateral_type.toBytes()])

    def set_outstanding_coin_supply(self):
        """Fix the total outstanding supply of system coin"""
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'setOutstandingCoinSupply', [])

    def calculate_cash_price(self, collateral_type: CollateralType) -> Transact:
        """Calculate the `fix`, the cash price for a given collateral"""
        assert isinstance(collateral_type, CollateralType)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'calculateCashPrice', [collateral_type.toBytes()])

    def prepare_coins_for_redeeming(self, system_coin: Wad) -> Transact:
        """Deposit system coin into the `coin_bag`, from which it cannot be withdrawn"""
        assert isinstance(system_coin, Wad)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'prepareCoinsForRedeeming', [system_coin.value])

    def redeem_collateral(self, collateral_type: CollateralType, system_coin: Wad):
        """Exchange an amount of system coin (already `prepare_coins_for_redeemin`ed in the `coin_bag`) for collateral"""
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(system_coin, Wad)
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'redeemCollateral', [collateral_type.toBytes(), system_coin.value])
