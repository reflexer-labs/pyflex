# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018-2019 bargst, EdNoepel
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
from collections import defaultdict
from datetime import datetime
from pprint import pformat
from typing import Optional, List

from hexbytes import HexBytes
from web3 import Web3

from web3._utils.events import get_event_data

from eth_abi.codec import ABICodec
from eth_abi.registry import registry as default_registry

from pyflex import Address, Contract, Transact
from pyflex.approval import directly, approve_cdp_modification_directly
#from pyflex.auctions import Flapper, Flipper, Flopper
from pyflex.auctions import SurplusAuctionHouse, EnglishCollateralAuctionHouse, DebtAuctionHouse
from pyflex.gas import DefaultGasPrice
from pyflex.logging import LogNote
from pyflex.token import DSToken, ERC20Token
from pyflex.numeric import Wad, Ray, Rad


logger = logging.getLogger()


class CollateralType:
    """Models one collateral type, the combination of a token and a set of risk parameters.
    For example, ETH-A and ETH-B are different collateral types with the same underlying
    token (WETH) but with different risk parameters.
    """

    def __init__(self, name: str, accumulated_rates: Optional[Ray] = None,
                 cdp_collateral: Optional[Wad] = None,
                 cdp_debt: Optional[Wad] = None,
                 safety_price: Optional[Ray] = None,
                 debt_ceiling: Optional[Rad] = None,
                 debt_floor: Optional[Rad] = None):
        assert (isinstance(name, str))
        assert (isinstance(accumulated_rates, Ray) or (accumulated_rates is None))
        assert (isinstance(cdp_collateral, Wad) or (cdp_collateral is None))
        assert (isinstance(cdp_debt, Wad) or (cdp_debt is None))
        assert (isinstance(safety_price, Ray) or (safety_price is None))
        assert (isinstance(debt_ceiling, Rad) or (debt_ceiling is None))
        assert (isinstance(debt_floor, Rad) or (debt_floor is None))

        self.name = name
        self.accumulated_rates = accumulated_rates 
        self.cdp_collateral = cdp_collateral
        self.cdp_debt = cdp_debt
        self.safety_price = safety_price
        self.debt_ceiling = debt_ceiling
        self.debt_floor = debt_floor

    def toBytes(self):
        return Web3.toBytes(text=self.name).ljust(32, bytes(1))

    @staticmethod
    def fromBytes(collateral_type: bytes):
        assert (isinstance(collateral_type, bytes))

        name = Web3.toText(collateral_type.strip(bytes(1)))
        return CollateralType(name)

    def __eq__(self, other):
        assert isinstance(other, CollateralType)

        return (self.name == other.name) \
           and (self.accumulated_rates == other.accumulated_rates) \
           and (self.cdp_collateral == other.cdp_collateral) \
           and (self.cdp_debt == other.cdp_debt) \
           and (self.safety_price == other.safety_price) \
           and (self.debt_ceiling == other.debt_ceiling) \
           and (self.debt_floor == other.debt_floor)

    def __repr__(self):
        repr = ''
        if self.accumulated_rates:
            repr += f' accumulated_rates={self.accumulated_rates}'
        if self.cdp_collateral:
            repr += f' cdp_collateral={self.cdp_collateral}'
        if self.cdp_debt:
            repr += f' cdp_debt={self.cdp_debt}'
        if self.safety_price:
            repr += f' safety_price={self.safety_price}'
        if self.debt_ceiling:
            repr += f' debt_ceiling={self.debt_ceiling}'
        if self.debt_floor:
            repr += f' debt_floor={self.debt_floor}'
        if repr:
            repr = f'[{repr.strip()}]'

        return f"CollateralType('{self.name}'){repr}"


class CDP:
    """Models one CDP for a single collateral type and account.
    Note the "address of the CDP" is merely the address of the CDP holder.
    """

    def __init__(self, address: Address, collateral_type: CollateralType = None,
                 locked_collateral: Wad = None, generated_debt: Wad = None):
        assert isinstance(address, Address)
        assert isinstance(collateral_type, CollateralType) or (collateral_type is None)
        assert isinstance(locked_collateral, Wad) or (locked_collateral is None)
        assert isinstance(generated_debt, Wad) or (generated_debt is None)

        self.address = address
        self.collateral_type = collateral_type
        self.locked_collateral = locked_collateral
        self.generated_debt = generated_debt

    def toBytes(self):
        addr_str = self.address.address
        return Web3.toBytes(hexstr='0x' + addr_str[2:].zfill(64))

    @staticmethod
    def fromBytes(cdp: bytes):
        assert isinstance(cdp, bytes)

        address = Address(Web3.toHex(cdp[-20:]))
        return CDP(address)

    def __eq__(self, other):
        assert isinstance(other, CDP)

        return (self.address == other.address) and (self.collateral_type == other.collateral_type)

    def __repr__(self):
        repr = ''
        if self.collateral_type:
            repr += f'[{self.collateral_type.name}]'
        if self.locked_collateral:
            repr += f' locked_collateral={self.locked_collateral}'
        if self.generated_debt:
            repr += f' generated_debt={self.generated_debt}'
        if repr:
            repr = f'[{repr.strip()}]'
        return f"CDP('{self.address}'){repr}"


class BasicTokenAdapter(Contract):
    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)
        self._token: DSToken = None

    def approve(self, approval_function, source: Address):
        assert(callable(approval_function))
        assert isinstance(source, Address)

        approval_function(ERC20Token(web3=self.web3, address=source), self.address, self.__class__.__name__)

    def approve_token(self, approval_function, **kwargs):
        return self.approve(approval_function, self._token.address, **kwargs)

    def join(self, usr: Address, value: Wad) -> Transact:
        assert isinstance(usr, Address)
        assert isinstance(value, Wad)

        return Transact(self, self.web3, self.abi, self.address, self._contract,
                        'join', [usr.address, value.value])

    def exit(self, usr: Address, value: Wad) -> Transact:
        assert isinstance(usr, Address)
        assert isinstance(value, Wad)

        return Transact(self, self.web3, self.abi, self.address, self._contract,
                        'exit', [usr.address, value.value])


class CoinJoin(BasicTokenAdapter):
    """A client for the `CoinJoin` contract, which allows the CDP holder to draw Dai from their CDP and repay it.

    Ref. <https://github.com/makerdao/dss/blob/master/src/join.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/CoinJoin.abi')
    bin = Contract._load_bin(__name__, 'abi/CoinJoin.bin')

    def __init__(self, web3: Web3, address: Address):
        super(CoinJoin, self).__init__(web3, address)
        self._token = self.system_coin()

    def system_coin(self) -> DSToken:
        address = Address(self._contract.functions.systemCoin().call())
        return DSToken(self.web3, address)


class CollateralJoin(BasicTokenAdapter):
    """A client for the `CollateralJoin` contract, which allows the user to deposit collateral into a new or existing vault.

    Ref. <https://github.com/makerdao/dss/blob/master/src/join.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/BasicCollateralJoin.abi')
    bin = Contract._load_bin(__name__, 'abi/BasicCollateralJoin.bin')

    def __init__(self, web3: Web3, address: Address):
        super(CollateralJoin, self).__init__(web3, address)
        self._token = self.collateral()

    def collateral_type(self):
        return CollateralType.fromBytes(self._contract.functions.collateralType().call())

    def collateral(self) -> DSToken:
        address = Address(self._contract.functions.collateral().call())
        return DSToken(self.web3, address)

    def decimals(self) -> int:
        return 18

class CollateralJoin5(CollateralJoin):
    """A client for the `CollateralJoin5` contract, which allows the user to deposit collateral into a new or existing vault.

    Ref. <https://github.com/makerdao/dss-deploy/blob/master/src/join.sol#L274>
    """
    abi = Contract._load_abi(__name__, 'abi/CollateralJoin5.abi')
    bin = Contract._load_bin(__name__, 'abi/CollateralJoin5.bin')

    def __init__(self, web3: Web3, address: Address):
        super(CollateralJoin5, self).__init__(web3, address)
        self._token = self.collateral()

    def dec(self) -> int:
        return int(self._contract.functions.dec().call())

class Collateral:
    """The `Collateral` object wraps accounting information in the CollateralType with token-wide artifacts shared across
    multiple collateral types for the same token.  For example, ETH-A and ETH-B are represented by different CollateralTypes,
    but will share the same collateral (WETH token), CollateralJoin instance, and Flipper contract.
    """

    def __init__(self, collateral_type: CollateralType, collateral: ERC20Token, adapter: CollateralJoin,
                 collateral_auction_house: EnglishCollateralAuctionHouse, pip):
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(collateral, ERC20Token)
        assert isinstance(adapter, CollateralJoin)
        assert isinstance(collateral_auction_house, EnglishCollateralAuctionHouse)

        self.collateral_type = collateral_type
        self.collateral = collateral
        self.adapter = adapter
        self.collateral_auction_house = collateral_auction_house
        # Points to `median` for official deployments, `DSValue` for testing purposes.
        # Users generally have no need to interact with the pip.
        self.pip = pip

    def approve(self, usr: Address, **kwargs):
        """
        Allows the user to move this collateral into and out of their CDP.

        Args
            usr: User making transactions with this collateral
        """
        gas_price = kwargs['gas_price'] if 'gas_price' in kwargs else DefaultGasPrice()
        self.adapter.approve(approve_cdp_modification_directly(from_address=usr, gas_price=gas_price), self.collateral_auction_house.cdp_engine())
        self.adapter.approve_token(directly(from_address=usr, gas_price=gas_price))


class CDPEngine(Contract):
    """A client for the `CDPEngine` contract, which manages accounting for all CDPs (CDPs).

    Ref. <https://github.com/makerdao/dss/blob/master/src/vat.sol>
    """

    '''
    # Identifies CDP holders and collateral types they have frobbed
    class LogModifyCDPCollateralizationOld():
        def __init__(self, lognote: LogNote):
            assert isinstance(lognote, LogNote)

            self.collateral_type = str(Web3.toText(lognote.arg1)).replace('\x00', '')
            self.cdp = Address(Web3.toHex(lognote.arg2)[26:])
            self.collateral_owner = Address(Web3.toHex(lognote.arg3)[26:])
            self.system_coin_recipient = Address(Web3.toHex(lognote.get_bytes_at_index(3))[26:])
            self.delta_collateral = Wad(int.from_bytes(lognote.get_bytes_at_index(4), byteorder="big", signed=True))
            self.delta_debt = Wad(int.from_bytes(lognote.get_bytes_at_index(5), byteorder="big", signed=True))
            self.block = lognote.block
            self.tx_hash = lognote.tx_hash

        def __repr__(self):
            return f"LogModifyCDPCollateralizationOld({pformat(vars(self))})"
    '''


    # This information is read from the `LogModifyCDPCollateralization` event emitted from `CDPEngine.modifyCDPCollateralization`
    class LogModifyCDPCollateralization:
        """
            event ModifyCDPCollateralization(
            bytes32 collateralType,
            address cdp,
            address collateralSource,
            address debtDestination,
            int deltaCollateral,
            int deltaDebt,
            uint lockedCollateral,
            uint generatedDebt,
            uint globalDebt
        );"""
        def __init__(self, log):
            self.collateral_type = CollateralType.fromBytes(log['args']['collateralType']).name
            self.cdp = Address(log['args']['cdp'])
            self.collateral_source = Address(log['args']['collateralSource'])
            self.debt_destination = Address(log['args']['debtDestination'])
            self.delta_collateral = Wad(log['args']['deltaCollateral'])
            self.delta_debt = Wad(log['args']['deltaDebt'])
            self.locked_collateral = Wad(log['args']['lockedCollateral'])
            self.generated_debt = Wad(log['args']['generatedDebt'])
            # Not sure here TODO Verify
            self.global_debt = Wad(log['args']['globalDebt'])

            #self.debt_amount = Wad(log['args']['debtAmount'])
            #self.amount_to_raise = Rad(log['args']['amountToRaise'])
            self.raw = log

        @classmethod
        def from_event(cls, event: dict):
            assert isinstance(event, dict)

            topics = event.get('topics')
            if topics and topics[0] == HexBytes('0xa14f3fdc5acb5eabb83dd585b63d8a914644435bdc0895c66e3c724dac497b9f'):
                log_abi = [abi for abi in CDPEngine.abi if abi.get('name') == 'ModifyCDPCollateralization'][0]
                codec = ABICodec(default_registry)
                event_data = get_event_data(codec, log_abi, event)

                return CDPEngine.LogModifyCDPCollateralization(event_data)
            else:
                logging.warning(f'[from_event] Invalid topic in {event}')

        def __eq__(self, other):
            assert isinstance(other, CDPEngine.LogModifyCDPCollateralization)
            return self.__dict__ == other.__dict__

        def __repr__(self):
            return f"LogModifyCDPCollateralization({pformat(vars(self))})"

    abi = Contract._load_abi(__name__, 'abi/CDPEngine.abi')
    bin = Contract._load_bin(__name__, 'abi/CDPEngine.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def init(self, collateral_type: CollateralType) -> Transact:
        assert isinstance(collateral_type, CollateralType)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'init', [collateral_type.toBytes()])

    def contract_enabled(self) -> bool:
        return self._contract.functions.contractEnabled().call() > 0

    def authorized_accounts(self, address: Address):
        assert isinstance(address, Address)

        return bool(self._contract.functions.authorizedAccounts(address.address).call())

    def approve_cdp_modification(self, address: Address):
        assert isinstance(address, Address)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'approveCDPModification', [address.address])

    def cdp_rights(self, sender: Address, usr: Address):
        assert isinstance(sender, Address)
        assert isinstance(usr, Address)

        return bool(self._contract.functions.cdpRights(sender.address, usr.address).call())

    def collateral_type(self, name: str) -> CollateralType:
        assert isinstance(name, str)

        b32_collateral_type = CollateralType(name).toBytes()
        (cdp_debt, rate, safety_price, d_ceiling, d_floor, liq_price) = self._contract.functions.collateralTypes(b32_collateral_type).call()

        # We could get "locked_collateral" from the CDP, but caller must provide an address.

        return CollateralType(name, accumulated_rates=Ray(rate), cdp_collateral=Wad(0), cdp_debt=Wad(cdp_debt),
                safety_price=Ray(safety_price), debt_ceiling=Rad(d_ceiling), debt_floor=Rad(d_floor))

    def token_collateral(self, collateral_type: CollateralType, cdp: Address) -> Wad:
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(cdp, Address)

        return Wad(self._contract.functions.tokenCollateral(collateral_type.toBytes(), cdp.address).call())

    def coin_balance(self, cdp: Address) -> Rad:
        assert isinstance(cdp, Address)

        return Rad(self._contract.functions.coinBalance(cdp.address).call())

    def debt_balance(self, cdp: Address) -> Rad:
        assert isinstance(cdp, Address)

        return Rad(self._contract.functions.debtBalance(cdp.address).call())

    def cdp(self, collateral_type: CollateralType, address: Address) -> CDP:
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(address, Address)

        (locked_collateral, generated_debt) = self._contract.functions.cdps(collateral_type.toBytes(), address.address).call()
        return CDP(address, collateral_type, Wad(locked_collateral), Wad(generated_debt))

    def global_debt(self) -> Rad:
        return Rad(self._contract.functions.globalDebt().call())

    def global_unbacked_debt(self) -> Rad:
        return Rad(self._contract.functions.globalUnbackedDebt().call())

    def global_debt_ceiling(self) -> Rad:
        """ Total debt ceiling """
        return Rad(self._contract.functions.globalDebtCeiling().call())

    def transfer_collateral(self, collateral_type: CollateralType, src: Address, dst: Address, wad: Wad) -> Transact:
        """Move CollateralType balance in CDPEngine from source address to destiny address

        Args:
            collateral_type: Identifies the type of collateral.
            src: Source of the collateral (address of the source).
            dst: Destiny of the collateral (address of the recipient).
            wad: Amount of collateral to move.
        """
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(src, Address)
        assert isinstance(dst, Address)
        assert isinstance(wad, Wad)

        transfer_args = [collateral_type.toBytes(), src.address, dst.address, wad.value]
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'transferCollateral', transfer_args)

    def transfer_internal_coins(self, src: Address, dst: Address, rad: Rad) -> Transact:
        """Move system coin balance in CDPEngine from source address to destiny address

        Args:
            src: Source of the system coin (address of the source).
            dst: Destiny of the system coin (address of the recipient).
            rad: Amount of system coin to move.
        """
        assert isinstance(src, Address)
        assert isinstance(dst, Address)
        assert isinstance(rad, Rad)

        move_args = [src.address, dst.address, rad.value]
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'transferInternalCoins', move_args)

    def transfer_cdp_collateral_and_debt(self, collateral_type: CollateralType, src: Address,
                                        dst: Address, delta_collateral: Wad, delta_debt: Wad) -> Transact:
        """Split a Vault - binary approval or splitting/merging Vault's

        Args:
            collateral_type: Identifies the type of collateral.
            src: Address of the source CDP.
            dst: Address of the destiny CDP.
            delta_collateral: Amount of collateral to exchange.
            delta_debt: Amount of stable coin debt to exchange.
        """
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(src, Address)
        assert isinstance(dst, Address)
        assert isinstance(delta_collateral, Wad)
        assert isinstance(delta_debt, Wad)

        transfer_args = [collateral_type.toBytes(), src.address, dst.address, delta_collateral.value, delta_debt.value]
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'transferCDPCollateralAndDebt', transfer_args)

    def modify_cdp_collateralization(self, collateral_type: CollateralType, cdp_address: Address, delta_collateral: Wad, delta_debt: Wad,
                                   collateral_owner=None, system_coin_recipient=None):
        """Adjust amount of collateral and reserved amount of system coin for the CDP

        Args:
            collateral_type: Identifies the type of collateral.
            cdp_address: CDP holder (address of the CDP).
            delta_collateral: Amount of collateral to add/remove.
            delta_debt: Adjust CDP debt (amount of system coin available for borrowing).
            collateral_owner: Holder of the collateral used to fund the CDP.
            dai_recipient: Party receiving the system coin 
        """
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(cdp_address, Address)
        assert isinstance(delta_collateral, Wad)
        assert isinstance(delta_debt, Wad)
        assert isinstance(collateral_owner, Address) or (collateral_owner is None)
        assert isinstance(system_coin_recipient, Address) or (system_coin_recipient is None)

        # Usually these addresses are the same as the account holding the cdp
        v = collateral_owner or cdp_address
        w = system_coin_recipient or cdp_address
        assert isinstance(v, Address)
        assert isinstance(w, Address)

        self.validate_cdp_modification(collateral_type, cdp_address, delta_collateral, delta_debt)

        if v == cdp_address and w == cdp_address:
            logger.info(f"modifying {collateral_type.name} cdp {cdp_address.address} with "
                        f"delta_collateral={delta_collateral}, delta_debt={delta_debt}")
        else:
            logger.info(f"modifying {collateral_type.name} cdp {cdp_address.address} "
                        f"with delta_collateral={delta_collateral} from {v.address}, "
                        f"delta_debt={delta_debt} for {w.address}")

        return Transact(self, self.web3, self.abi, self.address, self._contract,
                        'modifyCDPCollateralization',
                        [collateral_type.toBytes(), cdp_address.address, v.address, w.address, delta_collateral.value, delta_debt.value])

    def validate_cdp_modification(self, collateral_type: CollateralType, address: Address, delta_collateral: Wad, delta_debt: Wad):
        """Helps diagnose `frob` transaction failures by asserting on `require` conditions in the contract"""

        def r(value, decimals=1):  # rounding function
            return round(float(value), decimals)

        def f(value, decimals=1):  # formatting function
            return f"{r(value):16,.{decimals}f}"

        assert isinstance(collateral_type, CollateralType)
        assert isinstance(address, Address)
        assert isinstance(delta_collateral, Wad)
        assert isinstance(delta_debt, Wad)

        assert self.contract_enabled()  # system is live

        cdp = self.cdp(collateral_type, address)
        collateral_type = self.collateral_type(collateral_type.name)
        assert collateral_type.accumulated_rates != Ray(0)  # collateral_type has been initialised

        locked_collateral = cdp.locked_collateral + delta_collateral
        generated_debt = cdp.generated_debt + delta_debt
        collateral_type_cdp_debt = collateral_type.cdp_debt + delta_debt

        logger.debug(f"System     | debt {f(self.global_debt())} | ceiling {f(self.global_debt_ceiling())}")
        logger.debug(f"Collateral | debt {f(Ray(collateral_type_cdp_debt) * collateral_type.accumulated_rates)} "
                     f"| ceiling {f(collateral_type.debt_ceiling)}")

        dtab = Rad(collateral_type.accumulated_rates * Ray(delta_debt))
        tab = collateral_type.accumulated_rates * generated_debt
        debt = self.global_debt() + dtab
        logger.debug(f"Modifying CDP collateralization debt={r(collateral_type_cdp_debt)}, "
                     f"locked_collateral={r(locked_collateral)}, delta_collateral={r(delta_collateral)}, "
                     f"delta_debt={r(delta_debt)}, " f"collateral_type.rate={r(collateral_type.accumulated_rates,8)}, "
                     f"tab={r(tab)}, safety_price={r(collateral_type.safety_price, 4)}, debt={r(debt)}")

        # either debt has decreased, or debt ceilings are not exceeded
        under_collateral_debt_ceiling = Rad(Ray(collateral_type_cdp_debt) * collateral_type.accumulated_rates) <= collateral_type.debt_ceiling
        under_system_debt_ceiling = debt < self.global_debt_ceiling()
        calm = delta_debt <= Wad(0) or (under_collateral_debt_ceiling and under_system_debt_ceiling)

        # cdp is either less risky than before, or it is safe
        safe = (delta_debt <= Wad(0) and delta_collateral >= Wad(0)) or \
                tab <= Ray(locked_collateral) * collateral_type.safety_price

        # cdp has no debt, or a non-dusty amount
        neat = generated_debt == Wad(0) or Rad(tab) >= collateral_type.debt_floor

        if not under_collateral_debt_ceiling:
            logger.warning("collateral debt ceiling would be exceeded")
        if not under_system_debt_ceiling:
            logger.warning("system debt ceiling would be exceeded")
        if not safe:
            logger.warning("cdp would be unsafe")
        if not neat:
            logger.warning("debt would not exceed debt_floor cutoff")
        assert calm and safe and neat

    def past_cdp_modifications(self, from_block: int, to_block: int = None, collateral_type: CollateralType = None,
                               chunk_size=20000) -> List[LogModifyCDPCollateralization]:
        """Synchronously retrieve a list showing which collateral types and cdps have been modified.
         Args:
            from_block: Oldest Ethereum block to retrieve the events from.
            to_block: Optional newest Ethereum block to retrieve the events from, defaults to current block
            collateral_type: Optionally filter cdp modification by collateral_type.name
            chunk_size: Number of blocks to fetch from chain at one time, for performance tuning
         Returns:
            List of past `LogModifyCDPCollateralization` events represented as 
            :py:class:`pyflex.gf.CDPEngine.LogModifyCDPCollateralization` class.
        """
        current_block = self._contract.web3.eth.blockNumber
        assert isinstance(from_block, int)
        assert from_block < current_block
        if to_block is None:
            to_block = current_block
        else:
            assert isinstance(to_block, int)
            assert to_block >= from_block
            assert to_block <= current_block
        assert isinstance(collateral_type, CollateralType) or collateral_type is None
        assert chunk_size > 0

        logger.debug(f"Consumer requested cdp modification data from block {from_block} to {to_block}")
        start = from_block
        end = None
        chunks_queried = 0
        retval = []
        while end is None or start <= to_block:
            chunks_queried += 1
            end = min(to_block, start+chunk_size)

            filter_params = {
                'address': self.address.address,
                'fromBlock': start,
                'toBlock': end
            }
            logger.debug(f"Querying cdp modifications from block {start} to {end} ({end-start} blocks); "
                         f"accumulated {len(retval)} cdp modification in {chunks_queried-1} requests")

            logs = self.web3.eth.getLogs(filter_params)
            logger.debug(f"Found {len(logs)} total logs from block {start} to {end}")
            logger.debug(logs)

            log_modifications = list(map(lambda l: CDPEngine.LogModifyCDPCollateralization.from_event(l), logs))

            log_modifications = [l for l in log_modifications if l is not None]

            logger.debug(f"Found {len(log_modifications)} total mod cdp logs from block {start} to {end}")
            # '0x6f1493f7' is CDPEngine.modifyCDPCollateralization
            #log_modifications = list(filter(lambda l: l.sig == '0x6f1493f7', lognotes))
            #logger.debug(f"Found {len(log_modifications)} total sig matching logs from block {start} to {end}")
            #log_modifications = list(map(lambda l: CDPEngine.LogModifyCDPCollateralization(l), log_modifications))
            if collateral_type is not None:
                log_modifications = list(filter(lambda l: l.collateral_type == collateral_type.name, log_modifications))

            retval.extend(log_modifications)
            start += chunk_size

        logger.debug(f"Found {len(retval)} cdp modifications in {chunks_queried} requests")
        return retval

    def settle_debt(self, vice: Rad) -> Transact:
        assert isinstance(vice, Rad)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'settleDebt', [vice.value])

    def __eq__(self, other):
        assert isinstance(other, CDPEngine)
        return self.address == other.address

    def __repr__(self):
        return f"CDPEngine('{self.address}')"


class OracleRelayer(Contract):
    """A client for the `OracleRelayer` contract, which interacts with CDPEngine for the purpose of managing collateral prices.
    Users generally have no need to interact with this contract; it is included for unit testing purposes.

    Ref. <https://github.com/makerdao/dss-deploy/blob/master/src/poke.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/OracleRelayer.abi')
    bin = Contract._load_bin(__name__, 'abi/OracleRelayer.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def update_collateral_price(self, collateral_type: CollateralType) -> Transact:
        assert isinstance(collateral_type, CollateralType)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'updateCollateralPrice', [collateral_type.toBytes()])

    def cdp_engine(self) -> Address:
        return Address(self._contract.functions.cdpEngine().call())

    def redemption_price(self) -> Ray:
        return Ray(self._contract.functions.redemptionPrice().call())

    def safety_c_ratio(self, collateral_type: CollateralType) -> Ray:
        assert isinstance(collateral_type, CollateralType)
        (orcl, safety_c_ratio, liquidation_c_ratio) = self._contract.functions.collateralTypes(collateral_type.toBytes()).call()

        return Ray(safety_c_ratio)

    def liquidation_c_ratio(self, collateral_type: CollateralType) -> Ray:
        assert isinstance(collateral_type, CollateralType)
        (orcl, safety_c_ratio, liquidation_c_ratio) = self._contract.functions.collateralTypes(collateral_type.toBytes()).call()

        return Ray(liquidation_c_ratio)

    def __repr__(self):
        return f"OracleRelayer('{self.address}')"


class AccountingEngine(Contract):
    """A client for the `AccountingEngine` contract, which manages liquidation of surplus systemc coin and settlement of collateral debt.
    Specifically, this contract is useful for SurplusAuctionHouse and DebtAuctionHouse auctions.

    Ref. <https://github.com/makerdao/dss/blob/master/src/heal.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/AccountingEngine.abi')
    bin = Contract._load_bin(__name__, 'abi/AccountingEngine.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)
        self.cdp_engine = CDPEngine(web3, Address(self._contract.functions.cdpEngine().call()))

    def add_authorization(self, guy: Address) -> Transact:
        assert isinstance(guy, Address)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'addAuthorization', [guy.address])

    def contract_enabled(self) -> bool:
        return self._contract.functions.contractEnabled().call() > 0

    def surplus_auction_house(self) -> Address:
        return Address(self._contract.functions.surplusAuctionHouse().call())

    def debt_auction_house(self) -> Address:
        return Address(self._contract.functions.debtAuctionHouse().call())

    def debt_queue(self) -> Rad:
        return Rad(self._contract.functions.totalQueuedDebt().call())

    def debt_queue_of(self, era: int) -> Rad:
        return Rad(self._contract.functions.debtQueue(era).call())

    def total_on_auction_debt(self) -> Rad:
        return Rad(self._contract.functions.totalOnAuctionDebt().call())

    def unqueued_unauctioned_debt(self) -> Rad:
        return (self.cdp_engine.debt_balance(self.address) - self.debt_queue()) - self.total_on_auction_debt()

    def pop_debt_delay(self) -> int:
        return int(self._contract.functions.popDebtDelay().call())

    def initial_debt_auction_minted_tokens(self) -> Wad:
        return Wad(self._contract.functions.initialDebtAuctionMintedTokens().call())

    def debt_auction_bid_size(self) -> Rad:
        return Rad(self._contract.functions.debtAuctionBidSize().call())

    def surplus_auction_amount_to_sell(self) -> Rad:
        return Rad(self._contract.functions.surplusAuctionAmountToSell().call())

    def surplus_buffer(self) -> Rad:
        return Rad(self._contract.functions.surplusBuffer().call())

    def pop_debt_from_queue(self, era: int) -> Transact:
        assert isinstance(era, int)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'popDebtFromQueue', [era])

    def settle_debt(self, rad: Rad) -> Transact:
        assert isinstance(rad, Rad)
        logger.info(f"Settling debt joy={self.cdp_engine.coin_balance(self.address)} unqueued_enauctioned_debt={self.unqueued_unauctioned_debt()}")

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'settleDebt', [rad.value])

    def cancel_auctioned_debt_with_surplus(self, rad: Rad) -> Transact:
        assert isinstance(rad, Rad)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'cancelAuctionedDebtWithSurplus', [rad.value])

    def auction_debt(self) -> Transact:
        """Initiate a debt auction"""
        logger.info(f"Initiating a debt auction with unqueued_unauctioned_debt={self.unqueued_unauctioned_debt()}")

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'auctionDebt', [])

    def auction_surplus(self) -> Transact:
        """Initiate a surplus auction"""
        logger.info(f"Initiating a surplus auction with joy={self.cdp_engine.coinBalance(self.address)}")

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'auctionSurplus', [])

    def __repr__(self):
        return f"AccountingEngine('{self.address}')"


class TaxCollector(Contract):
    """A client for the `TaxCollector` contract, which manages stability fees.

    Ref. <https://github.com/makerdao/dss/blob/master/src/jug.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/TaxCollector.abi')
    bin = Contract._load_bin(__name__, 'abi/TaxCollector.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)
        self.cdp_engine = CDPEngine(web3, Address(self._contract.functions.cdpEngine().call()))
        self.accounting_engine = AccountingEngine(web3, Address(self._contract.functions.primaryTaxReceiver().call()))

    def initialize_collateral_type(self, collateral_type: CollateralType) -> Transact:
        assert isinstance(collateral_type, CollateralType)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'initializeCollateralType', [collateral_type.toBytes()])

    def authorized_accounts(self, address: Address):
        assert isinstance(address, Address)

        return bool(self._contract.functions.authorizedAccounts(address.address).call())

    def tax_single(self, collateral_type: CollateralType) -> Transact:
        assert isinstance(collateral_type, CollateralType)

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'taxSingle', [collateral_type.toBytes()])

    def global_stability_fee(self) -> Ray:
        return Ray(self._contract.functions.globalStabilityFee().call())

    def stability_fee(self, collateral_type: CollateralType) -> Ray:
        assert isinstance(collateral_type, CollateralType)

        return Ray(self._contract.functions.collateralTypes(collateral_type.toBytes()).call()[0])

    def update_time(self, collateral_type: CollateralType) -> int:
        assert isinstance(collateral_type, CollateralType)

        return Web3.toInt(self._contract.functions.collateralTypes(collateral_type.toBytes()).call()[1])

    def __repr__(self):
        return f"TaxCollector('{self.address}')"


class LiquidationEngine(Contract):
    """A client for the `LiquidationEngine` contract, used to liquidate unsafe CDPs (CDPs).
    Specifically, this contract is useful for EnglishCollateralAuctionHouse auctions.

    Ref. <https://github.com/makerdao/dss/blob/master/src/cat.sol>
    """

    # This information is read from the `Liquidate` event emitted from `LiquidationEngine.liquidateCDP`
    class LogLiquidate:
        def __init__(self, log):
            self.collateral_type = CollateralType.fromBytes(log['args']['collateralType'])
            self.cdp = CDP(Address(log['args']['cdp']))
            self.collateral_amount = Wad(log['args']['collateralAmount'])
            self.debt_amount = Wad(log['args']['debtAmount'])
            self.amount_to_raise = Rad(log['args']['amountToRaise'])
            self.collateral_auctioneer = Address(log['args']['collateralAuctioneer'])
            self.raw = log

        @classmethod
        def from_event(cls, event: dict):
            assert isinstance(event, dict)

            topics = event.get('topics')
            # TO DO Fix
            if topics and topics[0] == HexBytes('0x99b5620489b6ef926d4518936cfec15d305452712b88bd59da2d9c10fb0953e8'):
                log_liquidate_abi = [abi for abi in LiquidationEngine.abi if abi.get('name') == 'Liquidate'][0]
                codec = ABICodec(default_registry)
                event_data = get_event_data(codec, log_liquidate_abi, event)

                return LiquidationEngine.LogLiquidate(event_data)
            else:
                logging.warning(f'[from_event] Invalid topic in {event}')

        def era(self, web3: Web3):
            return web3.eth.getBlock(self.raw['blockNumber'])['timestamp']

        def __eq__(self, other):
            assert isinstance(other, LiquidationEngine.LogLiquidate)
            return self.__dict__ == other.__dict__

        def __repr__(self):
            return pformat(vars(self))

    abi = Contract._load_abi(__name__, 'abi/LiquidationEngine.abi')
    bin = Contract._load_bin(__name__, 'abi/LiquidationEngine.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)
        self.cdp_engine = CDPEngine(web3, Address(self._contract.functions.cdpEngine().call()))
        self.accounting_engine = AccountingEngine(web3, Address(self._contract.functions.accountingEngine().call()))

    def contract_enabled(self) -> bool:
        return self._contract.functions.contractEnabled().call() > 0

    def liquidate_cdp(self, collateral_type: CollateralType, cdp: CDP) -> Transact:
        """ Initiate liquidation of a CDP, kicking off a collateral auction

        Args:
            collateral_type: Identifies the type of collateral.
            cdp: CDP
        """
        assert isinstance(collateral_type, CollateralType)
        assert isinstance(cdp, CDP)

        collateral_type = self.cdp_engine.collateral_type(collateral_type.name)
        cdp = self.cdp_engine.cdp(collateral_type, cdp.address)
        rate = self.cdp_engine.collateral_type(collateral_type.name).accumulated_rates
        logger.info(f'Liquidating {collateral_type.name} CDP {cdp.address.address} with locked_collateral={cdp.locked_collateral} safety_price={collateral_type.safety_price} '
                    f'generated_debt={cdp.generated_debt} accumulatedRates={rate}')

        return Transact(self, self.web3, self.abi, self.address, self._contract,
                        'liquidateCDP', [collateral_type.toBytes(), cdp.address.address])

    def collateral_auction_house(self, collateral_type: CollateralType) -> Address:
        assert isinstance(collateral_type, CollateralType)

        (collateral_auction_house, _, _) = self._contract.functions.collateralTypes(collateral_type.toBytes()).call()

        return Address(collateral_auction_house)

    def liquidation_penalty(self, collateral_type: CollateralType) -> Ray:
        assert isinstance(collateral_type, CollateralType)

        (_, liquidation_penalty, _) = self._contract.functions.collateralTypes(collateral_type.toBytes()).call()
        return Ray(liquidation_penalty)

    def collateral_to_sell(self, collateral_type: CollateralType) -> Wad:
        assert isinstance(collateral_type, CollateralType)

        (_, _, collateral_to_sell) = self._contract.functions.collateralTypes(collateral_type.toBytes()).call()
        return Wad(collateral_to_sell)

    def modify_parameters_accountingEngine(self, acctEngine: AccountingEngine) -> Transact:
        assert isinstance(acctEngine, AccountingEngine)

        return Transact(self, self.web3, self.abi, self.address, self._contract,
                        'modifyParameters(bytes32,address)', [Web3.toBytes(text="accountingEngine"), acctEngine.address.address])


    def past_liquidations(self, number_of_past_blocks: int, event_filter: dict = None) -> List[LogLiquidate]:
        """Synchronously retrieve past LogLiquidate events.

        `LogLiquidate` events are emitted every time someone liquidates a CDP.

        Args:
            number_of_past_blocks: Number of past Ethereum blocks to retrieve the events from.
            event_filter: Filter which will be applied to returned events.

        Returns:
            List of past `LogLiquidate` events represented as :py:class:`pyflex.dss.LiquidationEngine.LogLiquidate` class.
        """
        assert isinstance(number_of_past_blocks, int)
        assert isinstance(event_filter, dict) or (event_filter is None)

        return self._past_events(self._contract, 'Liquidate', LiquidationEngine.LogLiquidate, number_of_past_blocks, event_filter)

    def __repr__(self):
        return f"LiquidationEngine('{self.address}')"


class CoinSavingsAccount(Contract):
    """A client for the `CoinSavingsAccount` contract, which implements the DSR.

    Ref. <https://github.com/makerdao/dss/blob/master/src/pot.sol>
    """

    abi = Contract._load_abi(__name__, 'abi/CoinSavingsAccount.abi')
    bin = Contract._load_bin(__name__, 'abi/CoinSavingsAccount.bin')

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def approve(self, source: Address, approval_function, **kwargs):
        """Approve the CoinSavingsAccount to access systemCoin from our CDPs"""
        assert isinstance(source, Address)
        assert(callable(approval_function))

        approval_function(ERC20Token(web3=self.web3, address=source), self.address, self.__class__.__name__, **kwargs)

    def savings_of(self, address: Address) -> Wad:
        assert isinstance(address, Address)
        return Wad(self._contract.functions.savings(address.address).call())

    def total_savings(self) -> Wad:
        pie = self._contract.functions.totalSavings().call()
        return Wad(pie)

    def savings_rate(self) -> Ray:
        dsr = self._contract.functions.savingsRate().call()
        return Ray(dsr)

    def accumulated_rates(self) -> Ray:
        chi = self._contract.functions.accumulatedRates().call()
        return Ray(chi)

    def update_time(self) -> datetime:
        rho = self._contract.functions.updateTime().call()
        return datetime.fromtimestamp(rho)

    def update_accumulated_rate(self) -> Transact:
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'updateAccumulatedRate', [])

    """ Join/Exit in CoinSavingsAccount can be invoked through pyflex/dsrmanager.py and pyflex/dsr.py """

    def __repr__(self):
        return f"CoinSavingsAccount('{self.address}')"
