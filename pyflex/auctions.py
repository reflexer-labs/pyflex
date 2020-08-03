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

from datetime import datetime
from pprint import pformat
from typing import List
from web3 import Web3

from web3._utils.events import get_event_data

from eth_abi.codec import ABICodec
from eth_abi.registry import registry as default_registry

from pyflex import Contract, Address, Transact
from pyflex.logging import LogNote
from pyflex.numeric import Wad, Rad, Ray
from pyflex.token import ERC20Token


def toBytes(string: str):
    assert(isinstance(string, str))
    return string.encode('utf-8').ljust(32, bytes(1))


class AuctionContract(Contract):
    """Abstract baseclass shared across all three auction contracts."""

    class SettleAuctionLog:
        def __init__(self, lognote: LogNote):
            # This is whoever called `settleAuction`, which could differ from the `high_bigger` who won the auction
            self.usr = Address(lognote.usr)
            self.id = Web3.toInt(lognote.arg1)
            self.block = lognote.block
            self.tx_hash = lognote.tx_hash

        def __repr__(self):
            return f"AuctionContract.SettleAuctionLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address, abi: list, bids: callable):
        if self.__class__ == AuctionContract:
            raise NotImplemented('Abstract class; please call CollateralAuctionHouse, SurplusAuctionHouse, or DebtAuctionHouse')
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)
        assert isinstance(abi, list)

        self.web3 = web3
        self.address = address
        self.abi = abi
        self._contract = self._get_contract(web3, abi, address)
        self._bids = bids

        self.log_note_abi = None
        self.start_auction_abi = None
        for member in abi:
            if not self.log_note_abi and member.get('name') == 'LogNote':
                self.log_note_abi = member
            elif not self.start_auction_abi and member.get('name') == 'StartAuction':
                self.start_auction_abi = member

    def authorized_accounts(self, address: Address) -> bool:
        assert isinstance(address, Address)

        return bool(self._contract.functions.authorizedAccounts(address.address).call())

    def cdp_engine(self) -> Address:
        """Returns the `cdpEngine` address.
         Returns:
            The address of the `cdpEngine` contract.
        """
        return Address(self._contract.functions.cdpEngine().call())

    def approve(self, source: Address, approval_function):
        """Approve the auction to access our collateral, Dai, or MKR so we can participate in auctions.

        For available approval functions (i.e. approval modes) see `directly` and `hope_directly`
        in `pyflex.approval`.

        Args:
            source: Address of the contract or token relevant to the auction (for Flipper and DebtAuctionHouse pass Vat address,
            for SurplusAuctionHouse pass MKR token address)
            approval_function: Approval function (i.e. approval mode)
        """
        assert isinstance(source, Address)
        assert(callable(approval_function))

        approval_function(token=ERC20Token(web3=self.web3, address=source),
                          spender_address=self.address, spender_name=self.__class__.__name__)

    def active_auctions(self) -> list:
        active_auctions = []
        auction_count = self.auctionsStarted()+1
        for index in range(1, auction_count):
            bid = self._bids(index)
            if bid.guy != Address("0x0000000000000000000000000000000000000000"):
                now = datetime.now().timestamp()
                if (bid.bid_expiry == 0 or now < bid.bid_expiry) and now < bid.auction_deadline:
                    active_auctions.append(bid)
            index += 1
        return active_auctions

    def bid_increase(self) -> Wad:
        """Returns the percentage minimum bid increase.

        Returns:
            The percentage minimum bid increase.
        """
        return Wad(self._contract.functions.bidIncrease().call())

    def bid_duration(self) -> int:
        """Returns the bid lifetime.

        Returns:
            The bid lifetime (in seconds).
        """
        return int(self._contract.functions.bidDuration().call())

    def total_auction_length(self) -> int:
        """Returns the total auction length.

        Returns:
            The total auction length (in seconds).
        """
        return int(self._contract.functions.totalAuctionLength().call())

    def auctions_started(self) -> int:
        """Returns the number of auctions started so far.

        Returns:
            The number of auctions started so far.
        """
        return int(self._contract.functions.auctionsStarted().call())

    def settle_auctions(self, id: int) -> Transact:
        assert(isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'settleAuction', [id])

    def get_past_lognotes(self, number_of_past_blocks: int, abi: list) -> List[LogNote]:
        assert isinstance(number_of_past_blocks, int)
        assert isinstance(abi, list)

        block_number = self._contract.web3.eth.blockNumber
        filter_params = {
            'address': self.address.address,
            'fromBlock': max(block_number - number_of_past_blocks, 0),
            'toBlock': block_number
        }

        logs = self.web3.eth.getLogs(filter_params)
        events = list(map(lambda l: self.parse_event(l), logs))
        return list(filter(lambda l: l is not None, events))

    def parse_event(self, event):
        raise NotImplemented()


class CollateralAuctionHouse(AuctionContract):
    """A client for the `CollateralAuctionHouse` contract, used to interact with collateral auctions.

    You can find the source code of the `CollateralAuctionHouse` contract here:
    <https://github.com/makerdao/dss/blob/master/src/flip.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `CollateralAuctionHouse` contract.

    Event signatures:
        0x65fae35e: (deployment-related)
        0x9c52a7f1: (deployment-related)
        0x29ae8114: file
        0xc84ce3a1172f0dec3173f04caaa6005151a4bfe40d4c9f3ea28dba5f719b2a7a: kick
        0x4b43ed12: tend
        0x5ff3a382: dent
        0xc959c42b: deal
    """

    abi = Contract._load_abi(__name__, 'abi/CollateralAuctionHouse.abi')
    #bin = Contract._load_bin(__name__, 'abi/CollateralAuctionHouse.bin')
    bin = Contract._load_bin(__name__, 'abi/EnglishCollateralAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid: Rad, amount_to_sell: Wad, high_bidder: Address, bid_expiry: int, auction_deadline: int,
                     usr: Address, gal: Address, tab: Rad):
            assert(isinstance(id, int))
            assert(isinstance(bid, Rad))
            assert(isinstance(amount_to_sell, Wad))
            assert(isinstance(high_bigger, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))
            assert(isinstance(usr, Address))
            assert(isinstance(gal, Address))
            assert(isinstance(tab, Rad))

            self.id = id
            self.bid = bid
            self.amount_to_sell = amount_to_sell
            self.high_bigger = high_bigger
            self.bid_expiry = bid_expiry
            self.auction_deadline = auction_deadline
            self.usr = usr
            self.gal = gal
            self.tab = tab

        def __repr__(self):
            return f"CollateralAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.amount_to_sell = Wad(args['amountToSell'])
            self.bid = Rad(args['bid'])
            self.tab = Rad(args['tab'])
            self.usr = Address(args['usr'])
            self.gal = Address(args['gal'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"CollateralAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class IncreaseBidSizeLog:
        def __init__(self, lognote: LogNote):
            self.high_bigger = Address(lognote.usr)
            self.id = Web3.toInt(lognote.arg1)
            self.amount_to_sell = Wad(Web3.toInt(lognote.arg2))
            self.bid = Rad(Web3.toInt(lognote.get_bytes_at_index(2)))
            self.block = lognote.block
            self.tx_hash = lognote.tx_hash

        def __repr__(self):
            return f"CollateralAuctionHouse.IncreaseBidSizeLog({pformat(vars(self))})"

    class DecreaseSoldAmountLog:
        def __init__(self, lognote: LogNote):
            self.high_bigger = Address(lognote.usr)
            self.id = Web3.toInt(lognote.arg1)
            self.amount_to_sell = Wad(Web3.toInt(lognote.arg2))
            self.bid = Rad(Web3.toInt(lognote.get_bytes_at_index(2)))
            self.block = lognote.block
            self.tx_hash = lognote.tx_hash

        def __repr__(self):
            return f"CollateralAuctionHouse.DecreaseSoldAmountLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        super(CollateralAuctionHouse, self).__init__(web3, address, CollateralAuctionHouse.abi, self.bids)

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()

        return CollateralAuctionHouse.Bid(id=id,
                           bid=Rad(array[0]),
                           amount_to_sell=Wad(array[1]),
                           high_bigger=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]),
                           usr=Address(array[5]),
                           gal=Address(array[6]),
                           tab=Rad(array[7]))

    def startAuction(self, usr: Address, gal: Address, tab: Rad, amount_to_sell: Wad, bid: Rad) -> Transact:
        assert(isinstance(usr, Address))
        assert(isinstance(gal, Address))
        assert(isinstance(tab, Rad))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [usr.address,
                                                                                          gal.address,
                                                                                          tab.value,
                                                                                          amount_to_sell.value,
                                                                                          bid.value])

    def increaseBidSize(self, id: int, amount_to_sell: Wad, bid: Rad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'increaseBidSize', [id, amount_to_sell.value, bid.value])

    def decreaseSoldAmount(self, id: int, amount_to_sell: Wad, bid: Rad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'decreaseSoldAmount', [id, amount_to_sell.value, bid.value])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        logs = super().get_past_lognotes(number_of_past_blocks, CollateralAuctionHouse.abi)

        history = []
        for log in logs:
            if log is None:
                continue
            elif isinstance(log, CollateralAuctionHouse.StartAuctionLog):
                history.append(log)
            elif log.sig == '0x4b43ed12':
                history.append(CollateralAuctionHouse.IncreaseBidSizeLog(log))
            elif log.sig == '0x5ff3a382':
                history.append(Flipper.DecreaseSoldAmountLog(log))
            elif log.sig == '0xc959c42b':
                history.append(AuctionContract.SettleAuctionLog(log))
        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0xc84ce3a1172f0dec3173f04caaa6005151a4bfe40d4c9f3ea28dba5f719b2a7a":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return CollateralAuctionHouse.StartAuctionLog(event_data)
        else:
            event_data = get_event_data(codec, self.log_note_abi, event)
            return LogNote(event_data)

    def __repr__(self):
        return f"CollateralAuctionHouse('{self.address}')"


class SurplusAuctionHouse(AuctionContract):
    """A client for the `SurplusAuctionHouse` contract, used to interact with surplus auctions.

    You can find the source code of the `SurplusAuctionHouse` contract here:
    <https://github.com/makerdao/dss/blob/master/src/flap.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `SurplusAuctionHouse` contract.

    Event signatures:
        0x65fae35e: (deployment-related)
        0x9c52a7f1: (deployment-related)
        0xe6dde59cbc017becba89714a037778d234a84ce7f0a137487142a007e580d609: kick
        0x29ae8114: file
        0x4b43ed12: tend
        0xc959c42b: deal
    """

    abi = Contract._load_abi(__name__, 'abi/PreSettlementSurplusAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/PreSettlementSurplusAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid: Wad, amount_to_sell: Rad, high_bidder: Address, bid_expiry: int, auction_deadline: int):
            assert(isinstance(id, int))
            assert(isinstance(bid, Wad))        # MKR
            assert(isinstance(amount_to_sell, Rad))        # DAI
            assert(isinstance(high_bidder, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))

            self.id = id
            self.bid = bid
            self.amount_to_sell = amount_to_sell
            self.high_bidder = high_bidder
            self.bid_expiry = bid_expiry
            self.auction_deadline = auction_deadline

        def __repr__(self):
            return f"SurplusAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.amount_to_sell = Rad(args['amountToSell'])
            self.bid = Wad(args['bid'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"SurplusAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class IncreaseBidSizeLog:
        def __init__(self, lognote: LogNote):
            self.high_bidder = Address(lognote.usr)
            self.id = Web3.toInt(lognote.arg1)
            self.amount_to_sell = Rad(Web3.toInt(lognote.arg2))
            self.bid = Wad(Web3.toInt(lognote.get_bytes_at_index(2)))
            self.block = lognote.block
            self.tx_hash = lognote.tx_hash

        def __repr__(self):
            return f"SurplusAuctionHouse.IncreaseBidSizeLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        super(SurplusAuctionHouse, self).__init__(web3, address, Flapper.abi, self.bids)

    def live(self) -> bool:
        return self._contract.functions.live().call() > 0

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()

        return SurplusAuctionHouse.Bid(id=id,
                           bid=Wad(array[0]),
                           amount_to_sell=Rad(array[1]),
                           high_bidder=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]))

    def start_auction(self, amount_to_sell: Rad, bid: Wad) -> Transact:
        assert(isinstance(amount_to_sell, Rad))
        assert(isinstance(bid, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [amount_to_sell.value,
                                                                                          bid.value])

    def increase_bid_size(self, id: int, amount_to_sell: Rad, bid: Wad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Rad))
        assert(isinstance(bid, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'increaseBidSize', [id, amount_to_sell.value, bid.value])

    def restart_auction(self, id: int) -> Transact:
        """Resurrect an auction which expired without any bids."""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'restartAuction', [id])

    def yank(self, id: int) -> Transact:
        """While `cage`d, refund current bid to the bidder"""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'yank', [id])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        logs = super().get_past_lognotes(number_of_past_blocks, SurplusAuctionHouse.abi)

        history = []
        for log in logs:
            if log is None:
                continue
            elif isinstance(log, SurplusAuctionHouse.StartAuctionLog):
                history.append(log)
            elif log.sig == '0x4b43ed12':
                history.append(SurplusAuctionHouse.IncreaseBidSizeLog(log))
            elif log.sig == '0xc959c42b':
                history.append(AuctionContract.SettleAuctionLog(log))
        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0xe6dde59cbc017becba89714a037778d234a84ce7f0a137487142a007e580d609":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return SurplusAuctionHouse.StartAuctionLog(event_data)
        else:
            event_data = get_event_data(codec, self.log_note_abi, event)
            return LogNote(event_data)

    def __repr__(self):
        return f"SurplusAuctionHouse('{self.address}')"


class DebtAuctionHouse(AuctionContract):
    """A client for the `DebtAuctionHouse` contract, used to interact with debt auctions.

    You can find the source code of the `DebtAuctionHouse` contract here:
    <https://github.com/makerdao/dss/blob/master/src/flop.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `DebtAuctionHouse` contract.

    Event signatures:
        0x65fae35e: (deployment-related)
        0x9c52a7f1: (deployment-related)
        0x29ae8114: file
        0x7e8881001566f9f89aedb9c5dc3d856a2b81e5235a8196413ed484be91cc0df6: kick
        0x5ff3a382: dent
        0xc959c42b: deal
    """

    abi = Contract._load_abi(__name__, 'abi/DebtAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/DebtAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid: Rad, amount_to_sell: Wad, high_bidder: Address, bid_expiry: int, auction_deadline: int):
            assert(isinstance(id, int))
            assert(isinstance(bid, Rad))
            assert(isinstance(amount_to_sell, Wad))
            assert(isinstance(high_bidder, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))

            self.id = id
            self.bid = bid
            self.amount_to_sell = amount_to_sell
            self.high_bidder = high_bidder
            self.bid_expiry = bid_expiry
            self.auction_deadline = auction_deadline

        def __repr__(self):
            return f"DebtAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.amount_to_sell = Wad(args['amountToSell'])
            self.bid = Rad(args['bid'])
            self.gal = Address(args['gal'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"DebtAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class DecreaseSoldAmountLog:
        def __init__(self, lognote: LogNote):
            self.high_bidder = Address(lognote.usr)
            self.id = Web3.toInt(lognote.arg1)
            self.amount_to_sell = Wad(Web3.toInt(lognote.arg2))
            self.bid = Rad(Web3.toInt(lognote.get_bytes_at_index(2)))
            self.block = lognote.block
            self.tx_hash = lognote.tx_hash

        def __repr__(self):
            return f"DebtAuctionHouse.DecreaseSoldAmountLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        super(DebtAuctionHouse, self).__init__(web3, address, DebtAuctionHouse.abi, self.bids)

    def live(self) -> bool:
        return self._contract.functions.live().call() > 0

    def pad(self) -> Wad:
        """Returns the amount_to_sell increase applied after an auction has been `restartAuction`ed."""

        return Wad(self._contract.functions.pad().call())

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()

        return DebtAuctionHouse.Bid(id=id,
                           bid=Rad(array[0]),
                           amount_to_sell=Wad(array[1]),
                           high_bidder=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]))

    def start_auction(self, gal: Address, amount_to_sell: Wad, bid: Wad) -> Transact:
        assert(isinstance(gal, Address))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [gal.address,
                                                                                          amount_to_sell.value,
                                                                                          bid.value])

    def decrease_sold_amount(self, id: int, amount_to_sell: Wad, bid: Rad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'decreaseSoldAmount', [id, amount_to_sell.value, bid.value])

    def restart_auction(self, id: int) -> Transact:
        """Resurrect an auction which expired without any bids."""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'restartAuction', [id])

    def yank(self, id: int) -> Transact:
        """While `cage`d, refund current bid to the bidder"""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'yank', [id])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        logs = super().get_past_lognotes(number_of_past_blocks, DebtAuctionHouse.abi)

        history = []
        for log in logs:
            if log is None:
                continue
            elif isinstance(log, DebtAuctionHouse.StartAuctionLog):
                history.append(log)
            elif log.sig == '0x5ff3a382':
                history.append(DebtAuctionHouse.DecreaseSoldAmountLog(log))
            elif log.sig == '0xc959c42b':
                history.append(AuctionContract.SettleAuctionLog(log))
        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0x7e8881001566f9f89aedb9c5dc3d856a2b81e5235a8196413ed484be91cc0df6":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return DebtAuctionHouse.StartAuctionLog(event_data)
        else:
            event_data = get_event_data(codec, self.log_note_abi, event)
            return LogNote(event_data)

    def __repr__(self):
        return f"DebtAuctionHouse('{self.address}')"
