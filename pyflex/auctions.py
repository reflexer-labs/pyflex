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
from pyflex.numeric import Wad, Rad, Ray
from pyflex.token import ERC20Token

def toBytes(string: str):
    assert(isinstance(string, str))
    return string.encode('utf-8').ljust(32, bytes(1))

class AuctionContract(Contract):
    """Abstract baseclass shared across all three auction contracts."""

    def __init__(self, web3: Web3, address: Address, abi: list, bids: callable):
        if self.__class__ == AuctionContract:
            raise NotImplemented('Abstract class; please call EnglishCollateralAuctionHouse, FixedDiscountAuctionHouse, \
                                 PreSettlementSurplusAuctionHouse, or DebtAuctionHouse')
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)
        assert isinstance(abi, list)

        self.web3 = web3
        self.address = address
        self.abi = abi
        self._contract = self._get_contract(web3, abi, address)
        self._bids = bids

        # Set ABIs for event names that are present in all auctions 
        self.start_auction_abi = None
        self.settle_auction_abi = None
        for member in abi:
            if not self.start_auction_abi and member.get('name') == 'StartAuction':
                self.start_auction_abi = member
            elif not self.settle_auction_abi and member.get('name') == 'SettleAuction':
                self.settle_auction_abi = member

    def safe_engine(self) -> Address:
        """Returns the `safeEngine` address.
         Returns:
            The address of the `safeEngine` contract.
        """
        return Address(self._contract.functions.safeEngine().call())

    def approve(self, source: Address, approval_function):
        """Approve the auction to access our collateral, system coin, or protocol token so we can participate in auctions.

        For available approval functions (i.e. approval modes) see `directly` and `approve_safe_modifications_directly`
        in `pyflex.approval`.

        Args:
            source: Address of the contract or token relevant to the auction 
                    (for EnglishCollateralAuctionHouse, FixedDiscountCollateralAuctionHouse and DebtAuctionHouse pass SAFEEngine address,
                    for PreSettlementSurplusAuctionHouse pass protocol token address)
            approval_function: Approval function (i.e. approval mode)
        """
        assert isinstance(source, Address)
        assert(callable(approval_function))

        approval_function(token=ERC20Token(web3=self.web3, address=source),
                          spender_address=self.address, spender_name=self.__class__.__name__)

    def active_auctions(self) -> list:
        active_auctions = []
        auction_count = self.auctions_started()
        for index in range(1, auction_count + 1):
            bid = self._bids(index)
            if bid.high_bidder != Address("0x0000000000000000000000000000000000000000"):
                now = datetime.now().timestamp()
                if (bid.bid_expiry == 0 or now < bid.bid_expiry) and now < bid.auction_deadline:
                    active_auctions.append(bid)

        return active_auctions

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

    def settle_auction(self, id: int) -> Transact:
        assert(isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'settleAuction', [id])

    #def get_past_logs(self, number_of_past_blocks: int, abi: list) -> List:
    def get_past_logs(self, number_of_past_blocks: int) -> List:
        assert isinstance(number_of_past_blocks, int)
        #assert isinstance(abi, list)

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

class EnglishCollateralAuctionHouse(AuctionContract):
    """A client for the `EnglishCollateralAuctionHouse` contract, used to interact with collateral auctions.

    You can find the source code of the `EnglishCollateralAuctionHouse` contract here:
    <https://github.com/reflexer-labs/geb/blob/master/src/CollateralAuctionHouse.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `EnglishCollateralAuctionHouse` contract.

    Event signatures:
    """

    abi = Contract._load_abi(__name__, 'abi/EnglishCollateralAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/EnglishCollateralAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid_amount: Rad, amount_to_sell: Wad, high_bidder: Address, bid_expiry: int, auction_deadline: int,
                     forgone_collateral_receiver: Address, auction_income_recipient: Address, amount_to_raise: Rad):
            assert(isinstance(id, int))
            assert(isinstance(bid_amount, Rad))
            assert(isinstance(amount_to_sell, Wad))
            assert(isinstance(high_bidder, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))
            assert(isinstance(forgone_collateral_receiver, Address))
            assert(isinstance(auction_income_recipient, Address))
            assert(isinstance(amount_to_raise, Rad))

            self.id = id
            self.bid_amount = bid_amount
            self.amount_to_sell = amount_to_sell
            self.high_bidder = high_bidder
            self.bid_expiry = bid_expiry
            self.auction_deadline = auction_deadline
            self.forgone_collateral_receiver = forgone_collateral_receiver
            self.auction_income_recipient = auction_income_recipient
            self.amount_to_raise = amount_to_raise

        def __repr__(self):
            return f"EnglishCollateralAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.amount_to_sell = Wad(args['amountToSell'])
            self.bid_amount = Rad(args['initialBid'])
            self.amount_to_raise = Rad(args['amountToRaise'])
            self.forgone_collateral_receiver = Address(args['forgoneCollateralReceiver'])
            self.auction_income_recipient = Address(args['auctionIncomeRecipient'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"EnglishCollateralAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class IncreaseBidSizeLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.high_bidder = Address(args['highBidder'])
            self.amount_to_buy = Wad(args['amountToBuy'])
            self.rad = Rad(args['rad'])
            self.bid_expiry = int(args['bidExpiry'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"EnglishCollateralAuctionHouse.IncreaseBidSizeLog({pformat(vars(self))})"

    class DecreaseSoldAmountLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.high_bidder = Address(args['highBidder'])
            self.amount_to_buy = Wad(args['amountToBuy'])
            self.rad = Rad(args['rad'])
            self.bid_expiry = int(args['bidExpiry'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"EnglishCollateralAuctionHouse.DecreaseSoldAmountLog({pformat(vars(self))})"

    class SettleAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"EnglishCollateralAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        # Set ABIs for event names that are not in AuctionContract
        self.increase_bid_size_abi = None
        self.decrease_sold_amount_abi = None

        for member in EnglishCollateralAuctionHouse.abi:
            if not self.increase_bid_size_abi and member.get('name') == 'IncreaseBidSize':
                self.increase_bid_size_abi = member
            elif not self.decrease_sold_amount_abi and member.get('name') == 'DecreaseSoldAmount':
                self.decrease_sold_amount_abi = member

        super(EnglishCollateralAuctionHouse, self).__init__(web3, address, EnglishCollateralAuctionHouse.abi, self.bids)

    def bid_duration(self) -> int:
        """Returns the bid lifetime.

        Returns:
            The bid lifetime (in seconds).
        """
        return int(self._contract.functions.bidDuration().call())

    def bid_to_market_price_ratio(self) -> Wad:
        """Returns the minimum bid to market price ratio for new bids.

        Returns:
            The minimum bid to market price ratio
        """
        return Ray(self._contract.functions.bidToMarketPriceRatio().call())

    def bid_increase(self) -> Wad:
        """Returns the percentage minimum bid increase.

        Returns:
            The percentage minimum bid increase.
        """
        return Wad(self._contract.functions.bidIncrease().call())

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()
        return EnglishCollateralAuctionHouse.Bid(id=id,
                           bid_amount=Rad(array[0]),
                           amount_to_sell=Wad(array[1]),
                           high_bidder=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]),
                           forgone_collateral_receiver=Address(array[5]),
                           auction_income_recipient=Address(array[6]),
                           amount_to_raise=Rad(array[7]))

    def start_auction(self, forgone_collateral_receiver: Address, auction_income_recipient: Address,
                      amount_to_raise: Rad, amount_to_sell: Wad, bid_amount: Rad) -> Transact:
        assert(isinstance(forgoneCollateralReceiver, Address))
        assert(isinstance(auction_income_recipient, Address))
        assert(isinstance(amount_to_raise, Rad))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid_amount, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [forgone_collateral_receiver.address,
                                                                                          auction_income_recipient.address,
                                                                                          amount_to_raise.value,
                                                                                          amount_to_sell.value,
                                                                                          bid_amount.value])

    def increase_bid_size(self, id: int, amount_to_sell: Wad, bid_amount: Rad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid_amount, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'increaseBidSize', [id, amount_to_sell.value, bid_amount.value])

    def decrease_sold_amount(self, id: int, amount_to_sell: Wad, bid_amount: Rad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid_amount, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'decreaseSoldAmount',
                        [id, amount_to_sell.value, bid_amount.value])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)

        #logs = super().get_past_logs(number_of_past_blocks, EnglishCollateralAuctionHouse.abi)
        logs = super().get_past_logs(number_of_past_blocks)

        history = []
        for log in logs:
            if log is None:
                continue
            if isinstance(log, EnglishCollateralAuctionHouse.StartAuctionLog) or \
               isinstance(log, EnglishCollateralAuctionHouse.IncreaseBidSizeLog) or \
               isinstance(log, EnglishCollateralAuctionHouse.DecreaseSoldAmountLog) or \
               isinstance(log, EnglishCollateralAuctionHouse.SettleAuctionLog):
               history.append(log)

        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0xdf7b5cd0ee6547c7389d2ac00ee0c1cd3439542399d6c8c520cc69c7409c0990":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return EnglishCollateralAuctionHouse.StartAuctionLog(event_data)
        elif signature == "0xd87c815d5a67c2e130ad04b714d87a6fb69d5a6df0dbb0f1639cd9fe292201f9":
            event_data = get_event_data(codec, self.increase_bid_size_abi, event)
            return EnglishCollateralAuctionHouse.IncreaseBidSizeLog(event_data)
        elif signature == "0x8c63feacc784a7f735e454365ba433f17d17293b02c57d98dad113977dbf0f13":
            event_data = get_event_data(codec, self.decrease_sold_amount_abi, event)
            return EnglishCollateralAuctionHouse.DecreaseSoldAmountLog(event_data)
        elif signature == "0x03af424b0e12d91ea31fe7f2c199fc02c9ede38f9aa1bdc019a8087b41445f7a":
            event_data = get_event_data(codec, self.settle_auction_abi, event)
            return EnglishCollateralAuctionHouse.SettleAuctionLog(event_data)

    def __repr__(self):
        return f"EnglishCollateralAuctionHouse('{self.address}')"

class PreSettlementSurplusAuctionHouse(AuctionContract):
    """A client for the `PreSettlementSurplusAuctionHouse` contract, used to interact with surplus auctions.

    You can find the source code of the `PreSettlementSurplusAuctionHouse` contract here:
    <https://github.com/reflexer-labs/geb/blob/master/src/SurplusAuctionHouse.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `PreSettlementSurplusAuctionHouse` contract.

    """

    abi = Contract._load_abi(__name__, 'abi/PreSettlementSurplusAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/PreSettlementSurplusAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid_amount: Wad, amount_to_sell: Rad, high_bidder: Address,
                     bid_expiry: int, auction_deadline: int):
            assert(isinstance(id, int))
            assert(isinstance(bid_amount, Wad))        # Gov
            assert(isinstance(amount_to_sell, Rad))        # System coin
            assert(isinstance(high_bidder, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))

            self.id = id
            self.bid_amount = bid_amount
            self.amount_to_sell = amount_to_sell
            self.high_bidder = high_bidder
            self.bid_expiry = bid_expiry
            self.auction_deadline = auction_deadline

        def __repr__(self):
            return f"PreSettlementSurplusAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.auctions_started = int(args['auctionsStarted'])
            self.amount_to_sell = Rad(args['amountToSell'])
            self.initial_bid = Wad(args['initialBid'])
            self.auction_deadline = int(args['auctionDeadline'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"PreSettlementSurplusAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class IncreaseBidSizeLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.high_bidder = Address(args['highBidder'])
            self.amount_to_buy = Rad(args['amountToBuy'])
            self.bid = Wad(args['bid'])
            self.bid_expiry = int(args['bidExpiry'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"PreSettlementSurplusAuctionHouse.IncreaseBidSizeLog({pformat(vars(self))})"

    class SettleAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"PreSettlementSurplusAuctionHouse.SettleAuctionLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        # Set ABIs for event names that are not in AuctionContract
        self.increase_bid_size_abi = None
        for member in PreSettlementSurplusAuctionHouse.abi:
            if not self.increase_bid_size_abi and member.get('name') == 'IncreaseBidSize':
                self.increase_bid_size_abi = member

        super(PreSettlementSurplusAuctionHouse, self).__init__(web3, address, PreSettlementSurplusAuctionHouse.abi, self.bids)

    def bid_duration(self) -> int:
        """Returns the bid lifetime.

        Returns:
            The bid lifetime (in seconds).
        """
        return int(self._contract.functions.bidDuration().call())

    def bid_increase(self) -> Wad:
        """Returns the percentage minimum bid increase.

        Returns:
            The percentage minimum bid increase.
        """
        return Wad(self._contract.functions.bidIncrease().call())

    def contract_enabled(self) -> bool:
        return self._contract.functions.contractEnabled().call() > 0

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()

        return PreSettlementSurplusAuctionHouse.Bid(id=id,
                           bid_amount=Wad(array[0]),
                           amount_to_sell=Rad(array[1]),
                           high_bidder=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]))

    def start_auction(self, amount_to_sell: Rad, bid_amount: Wad) -> Transact:
        assert(isinstance(amount_to_sell, Rad))
        assert(isinstance(bid_amount, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [amount_to_sell.value,
                                                                                          bid_amount.value])

    def increase_bid_size(self, id: int, amount_to_sell: Rad, bid_amount: Wad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Rad))
        assert(isinstance(bid_amount, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'increaseBidSize',
                        [id, amount_to_sell.value, bid_amount.value])

    def restart_auction(self, id: int) -> Transact:
        """Resurrect an auction which expired without any bids."""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'restartAuction', [id])

    def terminate_auction_prematurely(self, id: int) -> Transact:
        """While `disableContract`d, refund current bid to the bidder"""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'terminateAuctionPrematurely', [id])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        #logs = super().get_past_logs(number_of_past_blocks, PreSettlementSurplusAuctionHouse.abi)
        logs = super().get_past_logs(number_of_past_blocks)

        history = []
        for log in logs:
            if log is None:
                continue

            if isinstance(log, PreSettlementSurplusAuctionHouse.StartAuctionLog) or \
               isinstance(log, PreSettlementSurplusAuctionHouse.IncreaseBidSizeLog) or \
               isinstance(log, PreSettlementSurplusAuctionHouse.SettleAuctionLog):
                history.append(log)

        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0xa4863af70e77aecfe2769e0569806782ba7c6f86fc9a307290a3816fb8a563e5":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return PreSettlementSurplusAuctionHouse.StartAuctionLog(event_data)
        elif signature == "0xd87c815d5a67c2e130ad04b714d87a6fb69d5a6df0dbb0f1639cd9fe292201f9":
            event_data = get_event_data(codec, self.increase_bid_size_abi, event)
            return PreSettlementSurplusAuctionHouse.IncreaseBidSizeLog(event_data)
        elif signature == "0x03af424b0e12d91ea31fe7f2c199fc02c9ede38f9aa1bdc019a8087b41445f7a":
            event_data = get_event_data(codec, self.settle_auction_abi, event)
            return PreSettlementSurplusAuctionHouse.SettleAuctionLog(event_data)

    def __repr__(self):
        return f"PreSettlementSurplusAuctionHouse('{self.address}')"


class DebtAuctionHouse(AuctionContract):
    """A client for the `DebtAuctionHouse` contract, used to interact with debt auctions.

    You can find the source code of the `DebtAuctionHouse` contract here:
    <https://github.com/reflexer-labs/geb/blob/master/src/DebtAuctionHouse.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `DebtAuctionHouse` contract.

    """

    abi = Contract._load_abi(__name__, 'abi/DebtAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/DebtAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid_amount: Rad, amount_to_sell: Wad, high_bidder: Address,
                     bid_expiry: int, auction_deadline: int):
            assert(isinstance(id, int))
            assert(isinstance(bid_amount, Rad))
            assert(isinstance(amount_to_sell, Wad))
            assert(isinstance(high_bidder, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))

            self.id = id
            self.bid_amount = bid_amount
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
            self.initial_bid = Rad(args['initialBid'])
            self.income_receiver = Address(args['incomeReceiver'])
            self.auction_deadline = int(args['auctionDeadline'])
            self.active_debt_auctions = int(args['activeDebtAuctions'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"DebtAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class DecreaseSoldAmountLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.high_bidder = Address(args['highBidder'])
            self.amount_to_buy = Wad(args['amountToBuy'])
            self.bid = Rad(args['bid'])
            self.bid_expiry = int(args['bidExpiry'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"DebtAuctionHouse.DecreaseSoldAmountLog({pformat(vars(self))})"

    class SettleAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.active_debt_auctions = int(args['id'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"DebtAuctionHouse.SettleAuctionLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        # Set ABIs for event names that are not in AuctionContract
        self.decrease_sold_amount_abi = None
        for member in DebtAuctionHouse.abi:
            if not self.decrease_sold_amount_abi and member.get('name') == 'DecreaseSoldAmount':
                self.decrease_sold_amount_abi = member

        super(DebtAuctionHouse, self).__init__(web3, address, DebtAuctionHouse.abi, self.bids)

    def bid_duration(self) -> int:
        """Returns the bid lifetime.

        Returns:
            The bid lifetime (in seconds).
        """
        return int(self._contract.functions.bidDuration().call())

    def bid_decrease(self) -> Wad:
        """Returns the percentage minimum bid decrease.

        Returns:
            The percentage minimum bid decrease.
        """
        return Wad(self._contract.functions.bidDecrease().call())

    def contract_enabled(self) -> bool:
        return self._contract.functions.contractEnabled().call() > 0

    def amount_sold_increase(self) -> Wad:
        """Returns the amount_to_sell increase applied after an auction has been `restartAuction`ed."""

        return Wad(self._contract.functions.amountSoldIncrease().call())

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
                           bid_amount=Rad(array[0]),
                           amount_to_sell=Wad(array[1]),
                           high_bidder=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]))

    def start_auction(self, initial_bidder: Address, amount_to_sell: Wad, bid_amount: Wad) -> Transact:
        assert(isinstance(initial_bidder, Address))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid_amount, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [initial_bidder.address,
                                                                                          amount_to_sell.value,
                                                                                          bid_amount.value])

    def decrease_sold_amount(self, id: int, amount_to_sell: Wad, bid_amount: Rad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid_amount, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'decreaseSoldAmount', [id, amount_to_sell.value, bid_amount.value])

    def restart_auction(self, id: int) -> Transact:
        """Resurrect an auction which expired without any bids."""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'restartAuction', [id])

    def terminate_auction_prematurely(self, id: int) -> Transact:
        """While `disableContract`d, refund current bid to the bidder"""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'terminateAuctionPrematurely', [id])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        #logs = super().get_past_logs(number_of_past_blocks, DebtAuctionHouse.abi)
        logs = super().get_past_logs(number_of_past_blocks)

        history = []
        for log in logs:
            if log is None:
                continue
            if isinstance(log, DebtAuctionHouse.StartAuctionLog) or \
               isinstance(log, DebtAuctionHouse.DecreaseSoldAmountLog) or \
               isinstance(log, DebtAuctionHouse.SettleAuctionLog):
                history.append(log)

        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0x9102bd0b66dcb83f469f1122a583dc797657b114141460c59230fc1b41f48229":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return DebtAuctionHouse.StartAuctionLog(event_data)
        elif signature == "0x8c63feacc784a7f735e454365ba433f17d17293b02c57d98dad113977dbf0f13":
            event_data = get_event_data(codec, self.decrease_sold_amount_abi, event)
            return DebtAuctionHouse.DecreaseSoldAmountLog(event_data)
        elif signature == "0xef063949eb6ef5abef19139d9c75a558424ffa759302cfe445f8d2d327376fe4":
            event_data = get_event_data(codec, self.settle_auction_abi, event)
            return DebtAuctionHouse.SettleAuctionLog(event_data)

    def __repr__(self):
        return f"DebtAuctionHouse('{self.address}')"

class PostSettlementSurplusAuctionHouse(AuctionContract):
    """A client for the `PostSettlementSurplusAuctionHouse` contract, used to interact with surplus auctions
       after global settlement.

    You can find the source code of the `PostSettlementSurplusAuctionHouse` contract here:
    <https://github.com/reflexer-labs/geb/blob/master/src/SurplusAuctionHouse.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `PostSettlementSurplusAuctionHouse` contract.

    """

    abi = Contract._load_abi(__name__, 'abi/PostSettlementSurplusAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/PostSettlementSurplusAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, bid_amount: Wad, amount_to_sell: Rad, high_bidder: Address,
                     bid_expiry: int, auction_deadline: int):
            assert(isinstance(id, int))
            assert(isinstance(bid_amount, Wad)) # Gov
            assert(isinstance(amount_to_sell, Rad)) # System coin
            assert(isinstance(high_bidder, Address))
            assert(isinstance(bid_expiry, int))
            assert(isinstance(auction_deadline, int))

            self.id = id
            self.bid_amount = bid_amount
            self.amount_to_sell = amount_to_sell
            self.high_bidder = high_bidder
            self.bid_expiry = bid_expiry
            self.auction_deadline = auction_deadline

        def __repr__(self):
            return f"PostSettlementSurplusAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.auctions_started = int(args['auctionsStarted'])
            self.amount_to_sell = Rad(args['amountToSell'])
            self.initial_bid = Wad(args['initialBid'])
            self.auction_deadline = int(args['auctionDeadline'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"PostSettlementSurplusAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class IncreaseBidSizeLog:
        def __init__(self, log):
            args = log['args']
            self.id = int(args['id'])
            self.high_bidder = Address(args['highBidder'])
            self.amount_to_buy = Rad(args['amountToBuy'])
            self.bid = Wad(args['bid'])
            self.bid_expiry = int(args['bidExpiry'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"PostSettlementSurplusAuctionHouse.IncreaseBidSizeLog({pformat(vars(self))})"

    class SettleAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"PostSettlementSurplusAuctionHouse.SettleAuctionLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        # Set ABIs for event names that are not in AuctionContract
        self.increase_bid_size_abi = None
        for member in PostSettlementSurplusAuctionHouse.abi:
            if not self.increase_bid_size_abi and member.get('name') == 'IncreaseBidSize':
                self.increase_bid_size_abi = member

        super(PostSettlementSurplusAuctionHouse, self).__init__(web3, address, PostSettlementSurplusAuctionHouse.abi, self.bids)

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

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()

        return PostSettlementSurplusAuctionHouse.Bid(id=id,
                           bid_amount=Wad(array[0]),
                           amount_to_sell=Rad(array[1]),
                           high_bidder=Address(array[2]),
                           bid_expiry=int(array[3]),
                           auction_deadline=int(array[4]))

    def start_auction(self, amount_to_sell: Rad, bid_amount: Wad) -> Transact:
        assert(isinstance(amount_to_sell, Rad))
        assert(isinstance(bid_amount, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [amount_to_sell.value,
                                                                                          bid_amount.value])

    def increase_bid_size(self, id: int, amount_to_sell: Rad, bid_amount: Wad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(amount_to_sell, Rad))
        assert(isinstance(bid_amount, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'increaseBidSize',
                        [id, amount_to_sell.value, bid_amount.value])

    def restart_auction(self, id: int) -> Transact:
        """Resurrect an auction which expired without any bids."""
        assert (isinstance(id, int))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'restartAuction', [id])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        #logs = super().get_past_logs(number_of_past_blocks, PostSettlementSurplusAuctionHouse.abi)
        logs = super().get_past_logs(number_of_past_blocks)

        history = []
        for log in logs:
            if log is None:
                continue

            if isinstance(log, PostSettlementSurplusAuctionHouse.StartAuctionLog) or \
               isinstance(log, PostSettlementSurplusAuctionHouse.IncreaseBidSizeLog) or \
               isinstance(log, PostSettlementSurplusAuctionHouse.SettleAuctionLog):
                history.append(log)

        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0xa4863af70e77aecfe2769e0569806782ba7c6f86fc9a307290a3816fb8a563e5":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return PostSettlementSurplusAuctionHouse.StartAuctionLog(event_data)
        elif signature == "0xd87c815d5a67c2e130ad04b714d87a6fb69d5a6df0dbb0f1639cd9fe292201f9":
            event_data = get_event_data(codec, self.increase_bid_size_abi, event)
            return PostSettlementSurplusAuctionHouse.IncreaseBidSizeLog(event_data)
        elif signature == "0x03af424b0e12d91ea31fe7f2c199fc02c9ede38f9aa1bdc019a8087b41445f7a":
            event_data = get_event_data(codec, self.settle_auction_abi, event)
            return PostSettlementSurplusAuctionHouse.SettleAuctionLog(event_data)

    def __repr__(self):
        return f"PostSettlementSurplusAuctionHouse('{self.address}')"


class SettlementSurplusAuctioneer(Contract):
    """A client for the `SettlementSurplusAuctioneer` contract, used to settle surplus auctions after global settlement

    You can find the source code of the `SettlementSurplusAuctioneer` contract here:
    <https://github.com/reflexer-labs/geb/blob/master/src/SettlementSurplusAuctioneer.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `SettlementSurplusAuctioneer` contract.

    """

    abi = Contract._load_abi(__name__, 'abi/SettlementSurplusAuctioneer.abi')
    bin = Contract._load_bin(__name__, 'abi/SettlementSurplusAuctioneer.bin')

    class AuctionSurplusLog:
        """event AuctionSurplus(uint id, uint lastSurplusAuctionTime, uint coinBalance);"""
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.last_surplus_auction_time = args['lastSurplusAuctionTime']
            self.coin_balance = args['coinBalance']
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"SettlementSurplusAuctioneer.AuctionSurplusLog({pformat(vars(self))})"

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        # Set ABIs for event names
        self.auction_surplus_abi = None
        for member in SettlementSurplusAuctioneer.abi:
            if not self.auction_surplus_abi and member.get('name') == 'AuctionSurplus':
                self.auction_surplus_abi = member

        self.web3 = web3
        self.address = address
        self._contract = self._get_contract(web3, self.abi, address)

    def auction_surplus(self) -> int:
        """
        Start a surplus auction

        Returns:
            surplus auction id
        """
        return Transact(self, self.web3, self.abi, self.address, self._contract, 'auctionSurplus', [])

    def last_surplus_auction_time(self) -> int:
        """
        Last surplus auction time in epoch seconds

        Returns:
            time in epoch seconds
        """
        return int(self._contract.functions.lastSurplusAuctionTime().call())

    def accounting_engine(self) -> Address:
        """
        Address of AccountingEngine

        Returns:
            Address
        """
        return Address(self._contract.functions.accountingEngine().call())

    def surplus_auction_house(self) -> Address:
        """
        Address of SurplusAuctionHouse

        Returns:
            Address
        """
        return Address(self._contract.functions.surplusAuctionHouse().call())

    def safe_engine(self) -> Address:
        """
        Address of SAFEEngine

        Returns:
            Address
        """
        return Address(self._contract.functions.safeEngine().call())

class FixedDiscountCollateralAuctionHouse(AuctionContract):
    """A client for the `FixedDiscountCollateralAuctionHouse` contract, used to interact with collateral auctions.

    You can find the source code of the `FixedDiscountCollateralAuctionHouse` contract here:
    <https://github.com/reflexer-labs/geb/blob/master/src/CollateralAuctionHouse.sol>.

    Attributes:
        web3: An instance of `Web` from `web3.py`.
        address: Ethereum address of the `FixedDiscountCollateralAuctionHouse` contract.

    Event signatures:
    """

    abi = Contract._load_abi(__name__, 'abi/FixedDiscountCollateralAuctionHouse.abi')
    bin = Contract._load_bin(__name__, 'abi/FixedDiscountCollateralAuctionHouse.bin')

    class Bid:
        def __init__(self, id: int, raised_amount: Rad, sold_amount: Wad, amount_to_sell: Wad, amount_to_raise: Rad,
                auction_deadline: int, forgone_collateral_receiver: Address, auction_income_recipient: Address):
            assert(isinstance(id, int))
            assert(isinstance(raised_amount, Rad))
            assert(isinstance(sold_amount, Wad))
            assert(isinstance(amount_to_sell, Wad))
            assert(isinstance(amount_to_raise, Rad))
            assert(isinstance(auction_deadline, int))
            assert(isinstance(forgone_collateral_receiver, Address))
            assert(isinstance(auction_income_recipient, Address))

            self.id = id
            self.raised_amount = raised_amount
            self.sold_amount = sold_amount
            self.amount_to_sell = amount_to_sell
            self.amount_to_raise = amount_to_raise
            self.auction_deadline = auction_deadline
            self.forgone_collateral_receiver = forgone_collateral_receiver
            self.auction_income_recipient = auction_income_recipient

        def __repr__(self):
            return f"FixedDiscountCollateralAuctionHouse.Bid({pformat(vars(self))})"

    class StartAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.auctions_started = int(args['auctionsStarted'])
            self.amount_to_sell = Wad(args['amountToSell'])
            self.initial_bid = Rad(args['initialBid'])
            self.amount_to_raise = Rad(args['amountToRaise'])
            self.forgone_collateral_receiver = Address(args['forgoneCollateralReceiver'])
            self.auction_income_recipient = Address(args['auctionIncomeRecipient'])
            self.auction_deadline = int(args['auctionDeadline'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()

        def __repr__(self):
            return f"FixedDiscountCollateralAuctionHouse.StartAuctionLog({pformat(vars(self))})"

    class BuyCollateralLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.wad = Wad(args['wad'])
            self.bought_collateral = Wad(args['boughtCollateral'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()
            self.raw = log

        def __repr__(self):
            return f"FixedDiscountCollateralAuctionHouse.BuyCollateralLog({pformat(vars(self))})"

    class SettleAuctionLog:
        def __init__(self, log):
            args = log['args']
            self.id = args['id']
            self.leftover_collateral = Wad(args['leftoverCollateral'])
            self.block = log['blockNumber']
            self.tx_hash = log['transactionHash'].hex()
            self.raw = log

        def __repr__(self):
            return f"FixedDiscountCollateralAuctionHouse.SettleAuctionLog({pformat(vars(self))})"

    def active_auctions(self) -> list:
        active_auctions = []
        auction_count = self.auctions_started()
        for index in range(1, auction_count + 1):
            bid = self._bids(index)
            if bid.amount_to_sell > Wad(0) and bid.amount_to_raise > Rad(0):
                active_auctions.append(bid)

        return active_auctions

    def __init__(self, web3: Web3, address: Address):
        assert isinstance(web3, Web3)
        assert isinstance(address, Address)

        # Set ABIs for event names that are not in AuctionContract
        self.buy_collateral_abi = None
        for member in FixedDiscountCollateralAuctionHouse.abi:
            if not self.buy_collateral_abi and member.get('name') == 'BuyCollateral':
                self.buy_collateral_abi = member

        super(FixedDiscountCollateralAuctionHouse, self).__init__(web3, address, FixedDiscountCollateralAuctionHouse.abi, self.bids)

    def minimum_bid(self) -> Wad:
        """Returns the minimum bid.

        Returns:
            The minimum
        """
        return Wad(self._contract.functions.minimumBid().call())

    def bid_to_market_price_ratio(self) -> Wad:
        """Returns the minimum bid to market price ratio for new bids.

        Returns:
            The minimum bid to market price ratio
        """
        return Ray(self._contract.functions.bidToMarketPriceRatio().call())

    def bid_increase(self) -> Wad:
        """Returns the percentage minimum bid increase.

        Returns:
            The percentage minimum bid increase.
        """
        return Wad(self._contract.functions.bidIncrease().call())

    def bids(self, id: int) -> Bid:
        """Returns the auction details.

        Args:
            id: Auction identifier.

        Returns:
            The auction details.
        """
        assert(isinstance(id, int))

        array = self._contract.functions.bids(id).call()

        return FixedDiscountCollateralAuctionHouse.Bid(id=id,
                           raised_amount=Rad(array[0]),
                           sold_amount=Wad(array[1]),
                           amount_to_sell=Wad(array[2]),
                           amount_to_raise=Rad(array[3]),
                           auction_deadline=int(array[4]),
                           forgone_collateral_receiver=Address(array[5]),
                           auction_income_recipient=Address(array[6]))

    def start_auction(self, forgone_collateral_receiver: Address, auction_income_recipient: Address,
                      amount_to_raise: Rad, amount_to_sell: Wad, bid_amount: Rad) -> Transact:
        assert(isinstance(forgoneCollateralReceiver, Address))
        assert(isinstance(auction_income_recipient, Address))
        assert(isinstance(amount_to_raise, Rad))
        assert(isinstance(amount_to_sell, Wad))
        assert(isinstance(bid_amount, Rad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'startAuction', [forgone_collateral_receiver.address,
                                                                                          auction_income_recipient.address,
                                                                                          amount_to_raise.value,
                                                                                          amount_to_sell.value,
                                                                                          bid_amount.value])

    def buy_collateral(self, id: int, wad: Wad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(wad, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'buyCollateral', [id, wad.value])

    def get_collateral_bought(self, id: int, wad: Wad) -> Transact:
        assert(isinstance(id, int))
        assert(isinstance(wad, Wad))

        return Transact(self, self.web3, self.abi, self.address, self._contract, 'getCollateralBought', [id, wad.value])

    def past_logs(self, number_of_past_blocks: int):
        assert isinstance(number_of_past_blocks, int)
        #logs = super().get_past_logs(number_of_past_blocks, FixedDiscountCollateralAuctionHouse.abi)
        logs = super().get_past_logs(number_of_past_blocks)

        history = []
        for log in logs:
            if log is None:
                continue
            if isinstance(log, FixedDiscountCollateralAuctionHouse.StartAuctionLog) or \
               isinstance(log, FixedDiscountCollateralAuctionHouse.BuyCollateralLog) or \
               isinstance(log, FixedDiscountCollateralAuctionHouse.SettleAuctionLog):
               history.append(log)

        return history

    def parse_event(self, event):
        signature = Web3.toHex(event['topics'][0])
        codec = ABICodec(default_registry)
        if signature == "0xdf7b5cd0ee6547c7389d2ac00ee0c1cd3439542399d6c8c520cc69c7409c0990":
            event_data = get_event_data(codec, self.start_auction_abi, event)
            return FixedDiscountCollateralAuctionHouse.StartAuctionLog(event_data)
        elif signature == "0xa4a1133e32fac37643a1fe1db4631daadb462c8662ae16004e67f0b8bb608383":
            event_data = get_event_data(codec, self.buy_collateral_abi, event)
            return FixedDiscountCollateralAuctionHouse.BuyCollateralLog(event_data)
        elif signature == "0xef063949eb6ef5abef19139d9c75a558424ffa759302cfe445f8d2d327376fe4":
            event_data = get_event_data(codec, self.settle_auction_abi, event)
            return FixedDiscountCollateralAuctionHouse.SettleAuctionLog(event_data)

    def __repr__(self):
        return f"FixedDiscountCollateralAuctionHouse('{self.address}')"

