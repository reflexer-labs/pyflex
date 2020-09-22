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


import pytest
from typing import Union
from datetime import datetime
from web3 import Web3

from pyflex import Address
from pyflex.approval import directly, approve_safe_modification_directly
from pyflex.auctions import AuctionContract
from pyflex.auctions import FixedDiscountCollateralAuctionHouse, EnglishCollateralAuctionHouse, DebtAuctionHouse
from pyflex.auctions import PreSettlementSurplusAuctionHouse, PostSettlementSurplusAuctionHouse
from pyflex.auctions import DebtAuctionHouse
from pyflex.deployment import GfDeployment
from pyflex.gf import Collateral, SAFE, OracleRelayer
from pyflex.numeric import Wad, Ray, Rad
from tests.test_gf import wrap_eth, mint_prot, set_collateral_price, wait, wrap_modify_safe_collateralization
from tests.test_gf import cleanup_safe, max_delta_debt

def create_surplus(geb: GfDeployment, surplus_auction_house: Union[PreSettlementSurplusAuctionHouse, PostSettlementSurplusAuctionHouse],
        deployment_address: Address, collateral: Collateral, delta_collateral: int=300, delta_debt: int=1000, can_skip: bool=True):

    assert isinstance(geb, GfDeployment)
    assert isinstance(surplus_auction_house, PreSettlementSurplusAuctionHouse) or \
           isinstance(surplus_auction_house, PostSettlementSurplusAuctionHouse)
    assert isinstance(deployment_address, Address)

    joy = geb.safe_engine.coin_balance(geb.accounting_engine.address)

    if can_skip and joy >= geb.accounting_engine.surplus_buffer() + geb.accounting_engine.surplus_auction_amount_to_sell():
        print(f'Surplus of {joy} already exists; skipping SAFE creation')
        return

    # Create a SAFE with surplus
    print('Creating a SAFE with surplus')
    wrap_eth(geb, deployment_address, Wad.from_number(delta_collateral))
    collateral.approve(deployment_address)

    assert collateral.adapter.join(deployment_address, Wad.from_number(delta_collateral)).transact(from_address=deployment_address)

    wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(delta_collateral),
                                      delta_debt=Wad.from_number(delta_debt))

    assert geb.tax_collector.tax_single(collateral.collateral_type).transact(from_address=deployment_address)
      
    joy = geb.safe_engine.coin_balance(geb.accounting_engine.address)

    assert joy >= geb.accounting_engine.surplus_buffer() + geb.accounting_engine.surplus_auction_amount_to_sell()

def create_debt(web3: Web3, geb: GfDeployment, our_address: Address, deployment_address: Address, collateral: Collateral):
    assert isinstance(web3, Web3)
    assert isinstance(geb, GfDeployment)
    assert isinstance(our_address, Address)
    assert isinstance(deployment_address, Address)

    # Create a SAFE
    collateral_type = collateral.collateral_type
    wrap_eth(geb, deployment_address, Wad.from_number(100))
    collateral.approve(deployment_address)
    assert collateral.adapter.join(deployment_address, Wad.from_number(100)).transact(
        from_address=deployment_address)
    wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(100),
                                      delta_debt=Wad(0))
    delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad.from_number(500)
    wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0),
                                      delta_debt=delta_debt)

    # Ensure the SAFE can't currently be liquidated
    assert not geb.liquidation_engine.can_liquidate(collateral_type, geb.safe_engine.safe(collateral_type, deployment_address))

    # Undercollateralize and liquidation the SAFE
    to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
    set_collateral_price(geb, collateral, to_price)
    safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
    collateral_type = geb.safe_engine.collateral_type(collateral_type.name)
    assert safe.locked_collateral is not None and safe.generated_debt is not None
    assert collateral_type.safety_price is not None
    is_critical = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate > \
            Ray(safe.locked_collateral) * collateral_type.liquidation_price

    assert is_critical
    assert geb.liquidation_engine.can_liquidate(collateral_type, safe)
    assert geb.liquidation_engine.liquidate_safe(collateral_type, safe).transact()

    auction_id = collateral.collateral_auction_house.auctions_started()

    # Raise debt from the queue (note that accounting_engine.pop_debt_delay is 0 on our testchain)
    liquidations = geb.liquidation_engine.past_liquidations(100)
    for liquidation in liquidations:
        era_liquidation = liquidation.era(web3)
        liquidation_age = int(datetime.now().timestamp()) - era_liquidation
        assert era_liquidation > int(datetime.now().timestamp()) - 120

        assert geb.accounting_engine.debt_queue_of(era_liquidation) > Rad(0)
        assert geb.accounting_engine.pop_debt_from_queue(era_liquidation).transact()
        assert geb.accounting_engine.debt_queue_of(era_liquidation) == Rad(0)

    # Cancel out surplus and debt
    acct_engine_coin_balance = geb.safe_engine.coin_balance(geb.accounting_engine.address)

    assert acct_engine_coin_balance <= geb.accounting_engine.unqueued_unauctioned_debt()
    assert geb.accounting_engine.settle_debt(acct_engine_coin_balance).transact()
    assert geb.accounting_engine.unqueued_unauctioned_debt() >= geb.accounting_engine.debt_auction_bid_size()

def check_active_auctions(auction: AuctionContract):
    for bid in auction.active_auctions():
        assert bid.id > 0
        assert auction.auctions_started() >= bid.id
        assert isinstance(bid.high_bidder, Address)
        assert bid.high_bidder != Address("0x0000000000000000000000000000000000000000")

class TestEnglishCollateralAuctionHouse:
    @pytest.fixture(scope="session")
    def collateral(self, geb: GfDeployment) -> Collateral:
        return geb.collaterals['ETH-A']

    @pytest.fixture(scope="session")
    def oracle_relayer(self, geb: GfDeployment) -> OracleRelayer:
        return geb.oracle_relayer

    @pytest.fixture(scope="session")
    def english_collateral_auction_house(self, collateral, deployment_address) -> EnglishCollateralAuctionHouse:
        return collateral.collateral_auction_house

    @staticmethod
    def increase_bid_size(english_collateral_auction_house: EnglishCollateralAuctionHouse, oracle_relayer: OracleRelayer, 
                          collateral: Collateral, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(english_collateral_auction_house, EnglishCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        current_bid = english_collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert amount_to_sell == current_bid.amount_to_sell
        assert bid_amount <= current_bid.amount_to_raise
        assert bid_amount > current_bid.bid_amount
        assert (bid_amount >= Rad(english_collateral_auction_house.bid_increase()) * current_bid.bid_amount) or (bid_amount == current_bid.amount_to_raise)

        assert english_collateral_auction_house.increase_bid_size(id, amount_to_sell, bid_amount).transact(from_address=address)

    @staticmethod
    def decrease_sold_amount(english_collateral_auction_house: EnglishCollateralAuctionHouse, id: int, address: Address, amount_to_sell: Wad, bid: Rad):
        assert (isinstance(english_collateral_auction_house, EnglishCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid, Rad))

        current_bid = english_collateral_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid == current_bid.bid_amount
        assert bid == current_bid.amount_to_raise
        assert amount_to_sell < current_bid.amount_to_sell
        assert english_collateral_auction_house.bid_increase() * amount_to_sell <= current_bid.amount_to_sell

        assert english_collateral_auction_house.decrease_sold_amount(id, amount_to_sell, bid).transact(from_address=address)

    def test_getters(self, geb, english_collateral_auction_house):
        if not isinstance(english_collateral_auction_house, EnglishCollateralAuctionHouse):
            return

        assert english_collateral_auction_house.safe_engine() == geb.safe_engine.address
        assert english_collateral_auction_house.bid_increase() > Wad.from_number(1)
        assert english_collateral_auction_house.bid_duration() > 0
        assert english_collateral_auction_house.total_auction_length() > english_collateral_auction_house.bid_duration()
        assert english_collateral_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, collateral, english_collateral_auction_house, our_address, other_address, deployment_address):
        if not isinstance(english_collateral_auction_house, EnglishCollateralAuctionHouse):
            return
        prev_balance = geb.system_coin.balance_of(deployment_address)
        prev_coin_balance = geb.safe_engine.coin_balance(deployment_address)
        # Create a SAFE
        collateral = geb.collaterals['ETH-A']
        auctions_started_before = english_collateral_auction_house.auctions_started()

        # Generate eth and join
        wrap_eth(geb, deployment_address, Wad.from_number(1))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
            from_address=deployment_address)
 
        # generate the maximum debt possible
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(1), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        debt_before = geb.safe_engine.safe(collateral.collateral_type, deployment_address).generated_debt
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        geb.approve_system_coin(deployment_address)
        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        assert geb.system_coin.balance_of(deployment_address) == delta_debt
        assert geb.safe_engine.coin_balance(deployment_address) == Rad(0)

        # Undercollateralize the SAFE
        to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        collateral_type = geb.safe_engine.collateral_type(collateral.collateral_type.name)

        assert collateral_type.accumulated_rate is not None
        assert collateral_type.liquidation_price is not None

        is_critical = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate > \
               Ray(safe.locked_collateral) * collateral_type.liquidation_price
        assert is_critical
        assert len(english_collateral_auction_house.active_auctions()) == 0

        on_auction_before = geb.liquidation_engine.current_on_auction_system_coins()

        # Liquidate the SAFE, which moves debt to the accounting engine and auctions_started the english_collateral_auction_house
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        assert safe.locked_collateral > Wad(0)

        generated_debt = min(safe.generated_debt, Wad(geb.liquidation_engine.liquidation_quantity(collateral_type)))  # Wad

        amount_to_raise = generated_debt * collateral_type.accumulated_rate  # Wad
        assert amount_to_raise == delta_debt
        assert geb.liquidation_engine.can_liquidate(collateral_type, safe)
        assert geb.liquidation_engine.liquidate_safe(collateral_type, safe).transact()

        start_auction = english_collateral_auction_house.auctions_started()
        assert start_auction == auctions_started_before + 1
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)

        # Check safe_engine, accounting_engine, and liquidation_engine
        assert safe.locked_collateral == Wad(0)
        assert safe.generated_debt == delta_debt - generated_debt
        assert geb.safe_engine.global_unbacked_debt() > Rad(0)
        assert geb.accounting_engine.debt_queue() == Rad(amount_to_raise)
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)
        on_auction_after = geb.liquidation_engine.current_on_auction_system_coins()
        assert on_auction_before < on_auction_after

        # Check the english_collateral_auction_house
        current_bid = english_collateral_auction_house.bids(start_auction)
        assert isinstance(current_bid, EnglishCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell > Wad(0)
        assert current_bid.amount_to_raise > Rad(0)
        assert current_bid.bid_amount == Rad(0)

        # LiquidationEngine doesn't incorporate the liquidation penalty, but the EnglishCollateralAuctionHouse includes it.
        #assert last_liquidation.amount_to_raise == current_bid.amount_to_raise
        log = english_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.StartAuctionLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.bid_amount == current_bid.bid_amount
        assert log.amount_to_raise == current_bid.amount_to_raise
        assert log.forgone_collateral_receiver == deployment_address
        assert log.auction_income_recipient == geb.accounting_engine.address

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, english_collateral_auction_house.total_auction_length()+1)
        assert english_collateral_auction_house.restart_auction(start_auction).transact()

        # Wrap some eth and handle approvals before bidding
        eth_required = Wad(current_bid.amount_to_raise / Rad(collateral_type.safety_price)) * Wad.from_number(1.1)
        wrap_eth(geb, other_address, eth_required)
        collateral.approve(other_address)
        assert collateral.adapter.join(other_address, eth_required).transact(from_address=other_address)
        wrap_eth(geb, our_address, eth_required)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, eth_required).transact(from_address=our_address)

        english_collateral_auction_house.approve(geb.safe_engine.address, 
                                         approval_function=approve_safe_modification_directly(from_address=other_address))
        # Add Wad(1) to counter precision error converting amount_to_raise from Rad to Wad
        wrap_modify_safe_collateralization(geb, collateral, other_address, delta_collateral=eth_required,
                                          delta_debt=Wad(current_bid.amount_to_raise) + Wad(1))
        safe = geb.safe_engine.safe(collateral.collateral_type, other_address)
        assert Rad(safe.generated_debt) >= current_bid.amount_to_raise

        # Bid the amount_to_raise to instantly transition to decreaseSoldAmount stage
        TestEnglishCollateralAuctionHouse.increase_bid_size(english_collateral_auction_house, geb.oracle_relayer, collateral, start_auction, other_address,
                                                            current_bid.amount_to_sell, current_bid.amount_to_raise)
        current_bid = english_collateral_auction_house.bids(start_auction)
        assert current_bid.high_bidder == other_address
        assert current_bid.bid_amount == current_bid.amount_to_raise
        assert len(english_collateral_auction_house.active_auctions()) == 1
        check_active_auctions(english_collateral_auction_house)
        log = english_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.IncreaseBidSizeLog)
        assert log.high_bidder == current_bid.high_bidder
        assert log.id == current_bid.id
        assert log.amount_to_buy == current_bid.amount_to_sell
        assert log.rad == current_bid.bid_amount

        # Test the _decreaseSoldAmount_ phase of the auction
        english_collateral_auction_house.approve(geb.safe_engine.address, approval_function=approve_safe_modification_directly(from_address=our_address))
        wrap_modify_safe_collateralization(geb, collateral, our_address, delta_collateral=eth_required,
                                          delta_debt=Wad(current_bid.amount_to_raise) + Wad(1))
        amount_to_sell = current_bid.amount_to_sell - Wad.from_number(0.2)
        assert english_collateral_auction_house.bid_increase() * amount_to_sell <= current_bid.amount_to_sell
        assert geb.safe_engine.safe_rights(our_address, english_collateral_auction_house.address)
        TestEnglishCollateralAuctionHouse.decrease_sold_amount(english_collateral_auction_house, start_auction, our_address,
                                                        amount_to_sell, current_bid.amount_to_raise)
        current_bid = english_collateral_auction_house.bids(start_auction)
        assert current_bid.high_bidder == our_address
        assert current_bid.bid_amount == current_bid.amount_to_raise
        assert current_bid.amount_to_sell == amount_to_sell
        log = english_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.DecreaseSoldAmountLog)
        assert log.high_bidder == current_bid.high_bidder
        assert log.id == current_bid.id
        assert log.amount_to_buy == current_bid.amount_to_sell
        assert log.rad == current_bid.bid_amount

        # Exercise _settleAuction_ after bid has expired
        wait(geb, our_address, english_collateral_auction_house.bid_duration()+1)
        now = datetime.now().timestamp()
        assert 0 < current_bid.bid_expiry < now or current_bid.auction_deadline < now
        assert english_collateral_auction_house.settle_auction(start_auction).transact(from_address=our_address)
        assert len(english_collateral_auction_house.active_auctions()) == 0
        log = english_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, EnglishCollateralAuctionHouse.SettleAuctionLog)

        # Grab our collateral
        collateral_before = collateral.collateral.balance_of(our_address)
        assert collateral.adapter.exit(our_address, current_bid.amount_to_sell).transact(from_address=our_address)
        collateral_after = collateral.collateral.balance_of(our_address)
        assert collateral_before < collateral_after

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_safe(geb, collateral, other_address)

class TestFixedDiscountCollateralAuctionHouse:
    @pytest.fixture(scope="session")
    def collateral(self, geb: GfDeployment) -> Collateral:
        return geb.collaterals['ETH-A']

    @pytest.fixture(scope="session")
    def oracle_relayer(self, geb: GfDeployment) -> OracleRelayer:
        return geb.oracle_relayer

    @pytest.fixture(scope="session")
    def fixed_collateral_auction_house(self, collateral, deployment_address) -> FixedDiscountCollateralAuctionHouse:
        return collateral.collateral_auction_house

    @staticmethod
    def buy_collateral(fixed_collateral_auction_house: FixedDiscountCollateralAuctionHouse, id: int,
                       address: Address, wad: Rad):

        assert (isinstance(fixed_collateral_auction_house, FixedDiscountCollateralAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(address, Address))
        assert (isinstance(wad, Wad))

        assert wad >= fixed_collateral_auction_house.minimum_bid()

        current_bid = fixed_collateral_auction_house.bids(id)
        assert current_bid.amount_to_sell > Wad(0)
        assert current_bid.amount_to_raise > Rad(0)
        assert current_bid.auction_deadline > datetime.now().timestamp()
        assert wad > Wad(0)

        assert fixed_collateral_auction_house.get_collateral_bought(id, wad).transact(from_address=address)
        assert fixed_collateral_auction_house.buy_collateral(id, wad).transact(from_address=address)

    def test_getters(self, geb, fixed_collateral_auction_house):
        if not isinstance(fixed_collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return
        assert fixed_collateral_auction_house.safe_engine() == geb.safe_engine.address
        assert fixed_collateral_auction_house.total_auction_length() > 0
        assert fixed_collateral_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, collateral, fixed_collateral_auction_house, our_address, other_address, deployment_address):
        if not isinstance(fixed_collateral_auction_house, FixedDiscountCollateralAuctionHouse):
            return

        collateral = geb.collaterals['ETH-A']
        auctions_started_before = fixed_collateral_auction_house.auctions_started()
        collateral_type = collateral.collateral_type

        # Generate eth and join
        wrap_eth(geb, deployment_address, Wad.from_number(100))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(100)).transact(
            from_address=deployment_address)
 
        # generate the maximum debt possible
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad.from_number(100), delta_debt=Wad(0))
        delta_debt = max_delta_debt(geb, collateral, deployment_address) - Wad(1)
        debt_before = geb.safe_engine.safe(collateral_type, deployment_address).generated_debt
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, delta_collateral=Wad(0), delta_debt=delta_debt)

        # Mint and withdraw all the system coin
        geb.approve_system_coin(deployment_address)
        assert geb.system_coin_adapter.exit(deployment_address, delta_debt).transact(from_address=deployment_address)

        assert geb.system_coin.balance_of(deployment_address) == delta_debt
        assert geb.safe_engine.coin_balance(deployment_address) == Rad(0)

        # Undercollateralize the SAFE
        to_price = Wad(Web3.toInt(collateral.osm.read())) / Wad.from_number(2)
        set_collateral_price(geb, collateral, to_price)
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        collateral_type = geb.safe_engine.collateral_type(collateral_type.name)

        # Make sure the SAFE is not safe
        assert collateral_type.accumulated_rate is not None
        assert collateral_type.safety_price is not None
        safe = Ray(safe.generated_debt) * geb.safe_engine.collateral_type(collateral_type.name).accumulated_rate <= \
               Ray(safe.locked_collateral) * collateral_type.safety_price

        assert not safe
        assert len(fixed_collateral_auction_house.active_auctions()) == 0
        on_auction_before = geb.liquidation_engine.current_on_auction_system_coins()

        # Ensure there is no saviour
        saviour = geb.liquidation_engine.safe_saviours(collateral.collateral_type, deployment_address)
        assert saviour == Address('0x0000000000000000000000000000000000000000')

        # Liquidate the SAFE, which moves debt to the accounting engine and starts auction in the fixed_collateral_auction_house
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)
        assert safe.locked_collateral > Wad(0)
        generated_debt = min(safe.generated_debt, Wad(geb.liquidation_engine.liquidation_quantity(collateral_type)))  # Wad
        amount_to_raise = generated_debt * collateral_type.accumulated_rate  # Wad
        assert amount_to_raise == delta_debt

        assert geb.liquidation_engine.can_liquidate(collateral_type, safe)
        assert geb.liquidation_engine.liquidate_safe(collateral_type, safe).transact()

        # Ensure auction has been started
        assert fixed_collateral_auction_house.auctions_started() == auctions_started_before + 1
        assert len(fixed_collateral_auction_house.active_auctions()) == 1
        auction_id = fixed_collateral_auction_house.auctions_started()
        assert auction_id == auctions_started_before + 1
        safe = geb.safe_engine.safe(collateral.collateral_type, deployment_address)

        # Check safe_engine, accounting_engine, and liquidation_engine
        assert safe.locked_collateral == Wad(0)
        assert safe.generated_debt == delta_debt - generated_debt
        assert geb.safe_engine.global_unbacked_debt() > Rad(0)
        assert geb.accounting_engine.debt_queue() == Rad(amount_to_raise)
        liquidations = geb.liquidation_engine.past_liquidations(1)
        assert len(liquidations) == 1
        last_liquidation = liquidations[0]
        assert last_liquidation.amount_to_raise > Rad(0)

        on_auction_after = geb.liquidation_engine.current_on_auction_system_coins()
        assert on_auction_before < on_auction_after

        # Check the fixed_collateral_auction_house
        current_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(current_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert current_bid.amount_to_sell > Wad(0)
        assert current_bid.amount_to_raise > Rad(0)
        assert current_bid.raised_amount == Rad(0)
        assert current_bid.sold_amount == Wad(0)

        log = fixed_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, FixedDiscountCollateralAuctionHouse.StartAuctionLog)
        assert log.id == auction_id
        assert log.initial_bid == Rad(0)
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.amount_to_raise == current_bid.amount_to_raise
        assert log.auction_deadline == current_bid.auction_deadline
        assert log.forgone_collateral_receiver == deployment_address
        assert log.auction_income_recipient == geb.accounting_engine.address

        # Wrap some eth and handle approvals before bidding
        eth_required = Wad(current_bid.amount_to_raise / Rad(collateral_type.safety_price)) * Wad.from_number(2)

        wrap_eth(geb, other_address, eth_required)
        collateral.approve(other_address)
        assert collateral.adapter.join(other_address, eth_required).transact(from_address=other_address)

        wrap_eth(geb, our_address, eth_required)
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, eth_required).transact(from_address=our_address)

        # Approval
        fixed_collateral_auction_house.approve(geb.safe_engine.address, 
                                         approval_function=approve_safe_modification_directly(from_address=other_address))

        assert geb.safe_engine.coin_balance(other_address) == Rad(0)

        # Add Wad(1) to counter precision error converting amount_to_raise from Rad to Wad
        wrap_modify_safe_collateralization(geb, collateral, other_address, delta_collateral=eth_required,
                                          delta_debt=Wad(current_bid.amount_to_raise) + Wad(1))

        assert geb.safe_engine.coin_balance(other_address) > current_bid.amount_to_raise

        safe = geb.safe_engine.safe(collateral.collateral_type, other_address)
        assert Rad(safe.generated_debt) >= current_bid.amount_to_raise

        # First bid 
        first_bid_amount = Wad(current_bid.amount_to_raise) / Wad.from_number(2)

        TestFixedDiscountCollateralAuctionHouse.buy_collateral(fixed_collateral_auction_house, auction_id,
                                                               other_address, first_bid_amount)

        log = fixed_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, FixedDiscountCollateralAuctionHouse.BuyCollateralLog)
        assert log.id == auction_id
        assert log.wad == first_bid_amount
        assert log.bought_collateral > Wad(0)

        # Ensure it's still running
        assert len(fixed_collateral_auction_house.active_auctions()) == 1

        # Check results of first bid
        after_first_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(after_first_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert after_first_bid.amount_to_sell > Wad(0)
        assert after_first_bid.amount_to_raise > Rad(0) 
        assert after_first_bid.raised_amount == Rad(first_bid_amount)
        assert after_first_bid.sold_amount == log.bought_collateral

        # Second bid to buy the remaining collateral
        second_bid_amount = Wad(after_first_bid.amount_to_raise) - first_bid_amount
        assert second_bid_amount > fixed_collateral_auction_house.minimum_bid()
        assert geb.safe_engine.coin_balance(other_address) > Rad(second_bid_amount)
        TestFixedDiscountCollateralAuctionHouse.buy_collateral(fixed_collateral_auction_house, auction_id,
                                                               other_address, second_bid_amount)

        # Ensure auction has ended
        assert len(fixed_collateral_auction_house.active_auctions()) == 0

        # Check results of second bid
        after_second_bid = fixed_collateral_auction_house.bids(auction_id)
        assert isinstance(after_second_bid, FixedDiscountCollateralAuctionHouse.Bid)
        assert after_second_bid.amount_to_sell == Wad(0)
        assert after_second_bid.amount_to_raise == Rad(0)
        assert after_second_bid.raised_amount == Rad(0)
        assert after_second_bid.sold_amount == Wad(0)

        log = fixed_collateral_auction_house.past_logs(1)[1]
        assert isinstance(log, FixedDiscountCollateralAuctionHouse.BuyCollateralLog)
        assert log.id == auction_id
        assert log.wad == second_bid_amount
        assert log.bought_collateral > Wad(0)

        log = fixed_collateral_auction_house.past_logs(1)[0]
        assert isinstance(log, FixedDiscountCollateralAuctionHouse.SettleAuctionLog)
        assert log.id == auction_id
        assert log.leftover_collateral == Wad(0)

        # Grab our collateral
        collateral_before = collateral.collateral.balance_of(other_address)
        assert collateral.adapter.exit(other_address, current_bid.amount_to_sell).transact(from_address=other_address)
        collateral_after = collateral.collateral.balance_of(other_address)
        assert collateral_before < collateral_after

        # Cleanup
        set_collateral_price(geb, collateral, Wad.from_number(230))
        cleanup_safe(geb, collateral, other_address)

class TestPreSettlementSurplusAuctionHouse:
    @pytest.fixture(scope="session")
    def surplus_auction_house(self, geb: GfDeployment) -> PreSettlementSurplusAuctionHouse:
        return geb.surplus_auction_house

    @staticmethod
    def increase_bid_size(surplus_auction_house: PreSettlementSurplusAuctionHouse, id: int, address: Address,
                          amount_to_sell: Rad, bid_amount: Wad):
        assert (isinstance(surplus_auction_house, PreSettlementSurplusAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Rad))
        assert (isinstance(bid_amount, Wad))

        assert surplus_auction_house.contract_enabled() == 1

        current_bid = surplus_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert amount_to_sell == current_bid.amount_to_sell
        assert bid_amount > current_bid.bid_amount
        assert bid_amount >= surplus_auction_house.bid_increase() * current_bid.bid_amount

        assert surplus_auction_house.increase_bid_size(id, amount_to_sell, bid_amount).transact(from_address=address)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, PreSettlementSurplusAuctionHouse.IncreaseBidSizeLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.amount_to_buy == amount_to_sell
        assert log.bid == bid_amount

    def test_getters(self, geb, surplus_auction_house):
        assert surplus_auction_house.safe_engine() == geb.safe_engine.address
        assert surplus_auction_house.bid_increase() > Wad.from_number(1)
        assert surplus_auction_house.bid_duration() > 0
        assert surplus_auction_house.total_auction_length() > surplus_auction_house.bid_duration()
        assert surplus_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, surplus_auction_house, our_address, other_address, deployment_address):
        create_surplus(geb, surplus_auction_house, deployment_address, geb.collaterals['ETH-A'], 1, 10)

        joy_before = geb.safe_engine.coin_balance(geb.accounting_engine.address)

        # total surplus > total debt + surplus auction amount_to_sell size + surplus buffer

        assert joy_before > geb.safe_engine.debt_balance(geb.accounting_engine.address) + geb.accounting_engine.surplus_auction_amount_to_sell() + geb.accounting_engine.surplus_buffer()
        assert (geb.safe_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.debt_queue()) - \
                geb.accounting_engine.total_on_auction_debt() == Rad(0)
        assert geb.accounting_engine.auction_surplus().transact()
        start_auction = surplus_auction_house.auctions_started()
        assert start_auction == 1
        assert len(surplus_auction_house.active_auctions()) == 1
        check_active_auctions(surplus_auction_house)
        current_bid = surplus_auction_house.bids(1)
        assert current_bid.amount_to_sell > Rad(0)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, PreSettlementSurplusAuctionHouse.StartAuctionLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.initial_bid == current_bid.bid_amount

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, surplus_auction_house.total_auction_length()+1)
        assert surplus_auction_house.restart_auction(start_auction).transact()

        # Bid on the resurrected auction
        mint_prot(geb.prot, our_address, Wad.from_number(10))
        surplus_auction_house.approve(geb.prot.address, directly(from_address=our_address))
        bid_amount = Wad.from_number(0.001)
        assert geb.prot.balance_of(our_address) > bid_amount
        TestPreSettlementSurplusAuctionHouse.increase_bid_size(surplus_auction_house, start_auction, our_address, current_bid.amount_to_sell, bid_amount)
        current_bid = surplus_auction_house.bids(start_auction)
        assert current_bid.bid_amount == bid_amount
        assert current_bid.high_bidder == our_address

        # Exercise _settleAuction_ after bid has expired
        wait(geb, our_address, surplus_auction_house.bid_duration()+1)
        now = datetime.now().timestamp()
        assert 0 < current_bid.bid_expiry < now or current_bid.auction_deadline < now
        assert surplus_auction_house.settle_auction(start_auction).transact(from_address=our_address)
        joy_after = geb.safe_engine.coin_balance(geb.accounting_engine.address)
        assert joy_before - joy_after == geb.accounting_engine.surplus_auction_amount_to_sell()
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, PreSettlementSurplusAuctionHouse.SettleAuctionLog)
        assert log.id == start_auction

        # Grab our system_coin
        geb.approve_system_coin(our_address)
        assert geb.system_coin_adapter.exit(our_address, Wad(current_bid.amount_to_sell)).transact(from_address=our_address)
        assert geb.system_coin.balance_of(our_address) >= Wad(current_bid.amount_to_sell)
        assert (geb.safe_engine.debt_balance(geb.accounting_engine.address) - geb.accounting_engine.debt_queue()) - \
                geb.accounting_engine.total_on_auction_debt() == Rad(0)

        cleanup_safe(geb, geb.collaterals['ETH-A'], deployment_address)

class TestDebtAuctionHouse:
    @pytest.fixture(scope="session")
    def debt_auction_house(self, geb: GfDeployment) -> DebtAuctionHouse:
        return geb.debt_auction_house

    @staticmethod
    def decrease_sold_amount(debt_auction_house: DebtAuctionHouse, id: int, address: Address, amount_to_sell: Wad, bid_amount: Rad):
        assert (isinstance(debt_auction_house, DebtAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Wad))
        assert (isinstance(bid_amount, Rad))

        assert debt_auction_house.contract_enabled() == 1

        current_bid = debt_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert bid_amount == current_bid.bid_amount
        assert Wad(0) < amount_to_sell < current_bid.amount_to_sell
        assert debt_auction_house.bid_decrease() * amount_to_sell <= current_bid.amount_to_sell

        assert debt_auction_house.decrease_sold_amount(id, amount_to_sell, bid_amount).transact(from_address=address)
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.DecreaseSoldAmountLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.amount_to_buy == amount_to_sell
        assert log.bid == bid_amount

    def test_getters(self, geb, debt_auction_house):
        assert debt_auction_house.safe_engine() == geb.safe_engine.address
        assert debt_auction_house.bid_decrease() > Wad.from_number(1)
        assert debt_auction_house.bid_duration() > 0
        assert debt_auction_house.total_auction_length() > debt_auction_house.bid_duration()
        assert debt_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, debt_auction_house, our_address, other_address, deployment_address):
        collateral = geb.collaterals['ETH-A']
        create_debt(web3, geb, our_address, deployment_address, collateral)

        # start the debt auction
        assert debt_auction_house.auctions_started() == 0
        assert len(debt_auction_house.active_auctions()) == 0
        assert geb.safe_engine.coin_balance(geb.accounting_engine.address) == Rad(0)
        assert geb.accounting_engine.auction_debt().transact()
        start_auction = debt_auction_house.auctions_started()
        assert start_auction == 1
        assert len(debt_auction_house.active_auctions()) == 1
        check_active_auctions(debt_auction_house)
        current_bid = debt_auction_house.bids(start_auction)
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.StartAuctionLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.initial_bid == current_bid.bid_amount
        assert log.income_receiver == geb.accounting_engine.address

        # Allow the auction to expire, and then resurrect it
        wait(geb, our_address, debt_auction_house.total_auction_length()+1)
        assert debt_auction_house.restart_auction(start_auction).transact()
        assert debt_auction_house.bids(start_auction).amount_to_sell == current_bid.amount_to_sell * debt_auction_house.amount_sold_increase()

        # Generate some system coin
        wrap_eth(geb, our_address, Wad.from_number(10))
        collateral.approve(our_address)
        assert collateral.adapter.join(our_address, Wad.from_number(10)).transact(from_address=our_address)

        web3.eth.defaultAccount = our_address.address
        wrap_modify_safe_collateralization(geb, collateral, our_address, delta_collateral=Wad.from_number(10),
                                      delta_debt=Wad.from_number(50))

        # Bid on the resurrected auction
        bid_amount = Wad.from_number(0.000005)
        debt_auction_house.approve(geb.safe_engine.address, approve_safe_modification_directly(from_address=our_address))
        assert geb.safe_engine.safe_rights(our_address, debt_auction_house.address)
        TestDebtAuctionHouse.decrease_sold_amount(debt_auction_house, start_auction, our_address, bid_amount, current_bid.bid_amount)
        current_bid = debt_auction_house.bids(start_auction)
        assert current_bid.high_bidder == our_address

        # Confirm victory
        wait(geb, our_address, debt_auction_house.bid_duration()+1)
        assert debt_auction_house.contract_enabled()
        now = int(datetime.now().timestamp())
        assert (current_bid.bid_expiry < now and current_bid.bid_expiry != 0) or current_bid.auction_deadline < now
        prot_before = geb.prot.balance_of(our_address)
        assert debt_auction_house.settle_auction(start_auction).transact(from_address=our_address)
        prot_after = geb.prot.balance_of(our_address)
        assert prot_after > prot_before
        log = debt_auction_house.past_logs(1)[0]
        assert isinstance(log, DebtAuctionHouse.SettleAuctionLog)
        # Not present in SettleAuctionLog
        #assert log.forgone_collateral_receiver == our_address
        assert log.id == start_auction
        cleanup_safe(geb, collateral, our_address)
        cleanup_safe(geb, collateral, deployment_address)

class TestPostSettlementSurplusAuctionHouse:
    @pytest.fixture(scope="session")
    def post_surplus_auction_house(self, geb: GfDeployment) -> PostSettlementSurplusAuctionHouse:
        return geb.post_surplus_auction_house

    @staticmethod
    def increase_bid_size(surplus_auction_house: PostSettlementSurplusAuctionHouse, id: int, address: Address,
                          amount_to_sell: Rad, bid_amount: Wad):
        assert (isinstance(surplus_auction_house, PostSettlementSurplusAuctionHouse))
        assert (isinstance(id, int))
        assert (isinstance(amount_to_sell, Rad))
        assert (isinstance(bid_amount, Wad))

        current_bid = surplus_auction_house.bids(id)
        assert current_bid.high_bidder != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.bid_expiry > datetime.now().timestamp() or current_bid.bid_expiry == 0
        assert current_bid.auction_deadline > datetime.now().timestamp()

        assert amount_to_sell == current_bid.amount_to_sell
        assert bid_amount > current_bid.bid_amount
        assert bid_amount >= surplus_auction_house.bid_increase() * current_bid.bid_amount

        assert surplus_auction_house.increase_bid_size(id, amount_to_sell, bid_amount).transact(from_address=address)
        log = surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, PostSettlementSurplusAuctionHouse.IncreaseBidSizeLog)
        assert log.high_bidder == address
        assert log.id == id
        assert log.amount_to_buy == amount_to_sell
        assert log.bid == bid_amount

    def test_getters(self, geb, post_surplus_auction_house):
        assert post_surplus_auction_house.safe_engine() == geb.safe_engine.address
        assert post_surplus_auction_house.bid_increase() > Wad.from_number(1)
        assert post_surplus_auction_house.bid_duration() > 0
        assert post_surplus_auction_house.total_auction_length() > post_surplus_auction_house.bid_duration()
        assert post_surplus_auction_house.auctions_started() >= 0

    def test_scenario(self, web3, geb, post_surplus_auction_house, our_address, other_address, deployment_address):
        # Generate some system coin with deployment_addresses so we can start an auction
        collateral = geb.collaterals['ETH-A']
        wrap_eth(geb, deployment_address, Wad.from_number(100))
        collateral.approve(deployment_address)

        assert collateral.adapter.join(deployment_address, Wad.from_number(100)).transact(from_address=deployment_address)
        wrap_modify_safe_collateralization(geb, collateral, deployment_address, Wad.from_number(100), Wad.from_number(100))

        # No auctions started. No system coins yet
        assert post_surplus_auction_house.auctions_started() == 0
        assert geb.safe_engine.coin_balance(post_surplus_auction_house.address) == Rad(0)

        # Auction house needs to transfer internal coins from us when startAuction is called
        geb.safe_engine.approve_safe_modification(post_surplus_auction_house.address).transact(from_address=deployment_address)

        # Start auction
        assert post_surplus_auction_house.start_auction(Rad(Wad.from_number(90)), Wad(0)).transact(from_address=deployment_address)

        # System coins have been transferred
        assert geb.safe_engine.coin_balance(post_surplus_auction_house.address) == Rad(Wad.from_number(90))

        # There is one auction now
        assert len(post_surplus_auction_house.active_auctions()) == 1

        # Get auction id
        start_auction = post_surplus_auction_house.auctions_started()
        assert start_auction == 1

        # basic bid checks
        check_active_auctions(post_surplus_auction_house)

        # check our bid and StartAuctionLog
        current_bid = post_surplus_auction_house.bids(1)
        assert current_bid.amount_to_sell > Rad(0)
        log = post_surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, PostSettlementSurplusAuctionHouse.StartAuctionLog)
        assert log.id == start_auction
        assert log.amount_to_sell == current_bid.amount_to_sell
        assert log.initial_bid == current_bid.bid_amount

        # Allow the auction to expire
        print("Waiting %d seconds for auction to expire" % post_surplus_auction_house.total_auction_length())
        wait(geb, our_address, post_surplus_auction_house.total_auction_length() + 1)

        # Can't settle with no other bids
        assert geb.post_surplus_auction_house.settle_auction(1).transact() == None

        # Restart auction
        assert post_surplus_auction_house.restart_auction(start_auction).transact()

        # Mint so we can bid on the resurrected auction
        mint_prot(geb.prot, our_address, Wad.from_number(10))
        post_surplus_auction_house.approve(geb.prot.address, directly(from_address=our_address))

        prev = geb.prot.balance_of(post_surplus_auction_house.address)
        # bid
        bid_amount = Wad.from_number(0.001)
        assert geb.prot.balance_of(our_address) > bid_amount
        TestPostSettlementSurplusAuctionHouse.increase_bid_size(post_surplus_auction_house, start_auction, our_address,
                                                                current_bid.amount_to_sell, bid_amount)

        # Ensure we have enough system coins to pay winning bidder.
        assert current_bid.amount_to_sell <= geb.safe_engine.coin_balance(post_surplus_auction_house.address)

        #after = geb.prot.balance_of(surplus_auction_house.address)

        assert geb.prot.balance_of(post_surplus_auction_house.address) >= bid_amount

        # Check new bid
        current_bid = post_surplus_auction_house.bids(start_auction)
        assert current_bid.bid_amount == bid_amount
        assert current_bid.high_bidder == our_address

        # Exercise _settleAuction_ after bid has expired
        print("Waiting %d seconds for bid to expire" % post_surplus_auction_house.bid_duration())
        wait(geb, our_address, post_surplus_auction_house.bid_duration() + 1)
        now = datetime.now().timestamp()

        # Check that bid is expired or auction is past deadline
        assert (0 != current_bid.bid_expiry) and (current_bid.bid_expiry < now or current_bid.auction_deadline < now)

        # Anyone can settle. 
        assert post_surplus_auction_house.settle_auction(start_auction).transact()
        log = post_surplus_auction_house.past_logs(1)[0]
        assert isinstance(log, PostSettlementSurplusAuctionHouse.SettleAuctionLog)
        assert log.id == start_auction

        # Grab our system_coin
        geb.approve_system_coin(our_address)
        assert geb.system_coin_adapter.exit(our_address, Wad(current_bid.amount_to_sell)).transact(from_address=our_address)
        assert geb.system_coin.balance_of(our_address) >= Wad(current_bid.amount_to_sell)
